"""Normalise a schema ``timestamp-millis`` field back to epoch milliseconds.

fastavro decodes ``timestamp-millis`` logical-type fields to a timezone-aware
``datetime`` on the way *in*. A command payload's ``requested_at`` -- which the
operator UI sends as an epoch-ms number and ``encode_envelope`` writes as
``timestamp-millis`` -- therefore arrives at the live command handlers as a
``datetime``, not the ``int`` they expect. This is the one place that
conversion lives.
"""

from __future__ import annotations

from datetime import UTC, datetime


def epoch_ms(value: object, default: float) -> int:
    """Epoch milliseconds from ``value`` (a ``datetime`` from a decoded Avro
    ``timestamp-millis`` field, or a raw int/float ms), falling back to
    ``default`` when it is ``None`` or an unrecognised type."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return int(aware.timestamp() * 1000)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    return int(default)
