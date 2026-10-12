"""Envelope + payload (de)serialization against the schemas in contracts/events/.

[ARCH ADR-001]: one event language for every producer. This module is the only
place that should call fastavro directly — services import encode_envelope /
decode_envelope and never touch a schema file themselves. That's what keeps
"every service imports from contracts/" true in practice rather than in a diagram.
"""

from __future__ import annotations

import datetime as dt
import io
import re
import time
import uuid
from functools import cache
from typing import Any, cast

import fastavro
from itms_domain.paths import CONTRACTS_DIR

# packages/common/itms_common/events.py -> repo root is three parents up.
_CONTRACTS_DIR = CONTRACTS_DIR

_CAMEL_TO_SNAKE_RE = re.compile(r"(?<!^)(?=[A-Z])")


def _schema_filename(event_type: str) -> str:
    """'SystemHeartbeat' -> 'system_heartbeat.avsc'."""
    return _CAMEL_TO_SNAKE_RE.sub("_", event_type).lower() + ".avsc"


@cache
def _load_schema(filename: str) -> dict:
    path = _CONTRACTS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(
            f"no schema at {path} — add contracts/events/{filename} before "
            f"publishing/consuming this event type"
        )
    # fastavro's Schema type alias is a broad union (str | list | dict); every
    # schema file we load is a top-level record, i.e. always a dict, at runtime.
    return cast(dict, fastavro.schema.load_schema(str(path)))


def _envelope_schema() -> dict:
    return _load_schema("envelope.avsc")


def _payload_schema(event_type: str) -> dict:
    return _load_schema(_schema_filename(event_type))


def encode_envelope(
    event_type: str,
    source: str,
    payload: dict[str, Any],
    *,
    partition_key: str | None = None,
) -> bytes:
    """Build an EventEnvelope carrying `payload`, encoded per event_type's schema.

    Returns Avro-encoded bytes of the *envelope* (payload is nested inside as
    its own Avro-encoded bytes) — this is what goes on the bus verbatim.
    """
    payload_bytes = io.BytesIO()
    fastavro.schemaless_writer(payload_bytes, _payload_schema(event_type), payload)

    envelope = {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "schema_version": 1,
        "occurred_at": int(time.time() * 1000),
        "source": source,
        "partition_key": partition_key,
        "payload": payload_bytes.getvalue(),
    }

    out = io.BytesIO()
    fastavro.schemaless_writer(out, _envelope_schema(), envelope)
    return out.getvalue()


def decode_envelope(raw: bytes) -> dict[str, Any]:
    """Inverse of encode_envelope. Returns the envelope dict with `payload`
    replaced by the decoded payload dict (not raw bytes)."""
    # fastavro's AvroMessage return type is a broad union; both calls decode a
    # record schema, so both are always dicts at runtime.
    envelope = cast(
        dict[str, Any], fastavro.schemaless_reader(io.BytesIO(raw), _envelope_schema())
    )

    payload_schema = _payload_schema(envelope["event_type"])
    payload = cast(
        dict[str, Any],
        fastavro.schemaless_reader(io.BytesIO(envelope["payload"]), payload_schema),
    )
    envelope["payload"] = payload
    return envelope


def occurred_at_s(envelope: dict[str, Any]) -> float | None:
    """When the event happened, as Unix seconds -- or None if the envelope
    does not say. `occurred_at` is written as integer milliseconds but is an
    Avro `timestamp-millis`, so `decode_envelope` hands it back as a
    timezone-aware `datetime`; anything comparing it with a clock must go
    through here rather than divide it by 1000."""
    v = envelope.get("occurred_at")
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=dt.UTC)
        return v.timestamp()
    return float(v) / 1000.0
