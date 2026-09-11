"""Tamper-evident hash chain -- the primitive shared by every domain
state machine that has to be auditable (`incident.Incident`,
`emergency.EmergencyRequest`).

Each entry's hash is SHA-256 over its own recorded fields plus the previous
entry's hash, so any edit to any field, or any reordering, changes that entry
and every entry after it. `verify_links` recomputes the whole chain from
`GENESIS_HASH`.

Pure: `hashlib` / `json` only, no clock, no I/O.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

# 64 hex zeros -- the prev_hash of the first entry, so "is this the start of a
# real chain" is a value check, not a None check.
GENESIS_HASH = "0" * 64


def _canonical(obj: object) -> bytes:
    """Deterministic bytes for hashing: sorted keys, no insignificant
    whitespace, NaN / Infinity rejected (json default)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def entry_hash(fields: Mapping[str, object], prev_hash: str) -> str:
    """SHA-256 of `fields` flattened with `prev_hash`. `fields` must contain
    only JSON-primitive values (str / int / float / bool / None) -- callers
    convert enums to their `.value` first."""
    return hashlib.sha256(_canonical({**dict(fields), "prev_hash": prev_hash})).hexdigest()


def verify_links(entries: Sequence[tuple[Mapping[str, object], str, str]]) -> bool:
    """`entries` is an ordered sequence of `(fields, prev_hash, entry_hash)`.
    Returns True iff every `prev_hash` matches its predecessor's `entry_hash`
    (the first must be `GENESIS_HASH`) and every `entry_hash` recomputes from
    its `fields` + `prev_hash`. An empty sequence verifies vacuously."""
    prev = GENESIS_HASH
    for fields, prev_hash, recorded_hash in entries:
        if prev_hash != prev:
            return False
        if recorded_hash != entry_hash(fields, prev_hash):
            return False
        prev = recorded_hash
    return True
