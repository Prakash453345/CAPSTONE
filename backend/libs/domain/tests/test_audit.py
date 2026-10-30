"""`itms_domain.audit` -- the shared hash-chain primitive."""

from __future__ import annotations

from itms_domain.audit import GENESIS_HASH, entry_hash, verify_links


def _chain(fields_list: list[dict]) -> list[tuple[dict, str, str]]:
    out: list[tuple[dict, str, str]] = []
    prev = GENESIS_HASH
    for fields in fields_list:
        h = entry_hash(fields, prev)
        out.append((fields, prev, h))
        prev = h
    return out


def test_entry_hash_is_deterministic_and_order_independent_in_fields():
    a = entry_hash({"x": 1, "y": "two"}, GENESIS_HASH)
    b = entry_hash({"y": "two", "x": 1}, GENESIS_HASH)
    assert a == b
    assert a == entry_hash({"x": 1, "y": "two"}, GENESIS_HASH)


def test_a_different_prev_hash_changes_the_entry_hash():
    assert entry_hash({"x": 1}, GENESIS_HASH) != entry_hash({"x": 1}, "a" * 64)


def test_a_clean_chain_verifies():
    chain = _chain([{"n": 1}, {"n": 2}, {"n": 3}])
    assert verify_links(chain)


def test_empty_chain_verifies_vacuously():
    assert verify_links([])


def test_editing_a_field_breaks_verification():
    chain = _chain([{"n": 1}, {"n": 2}])
    tampered = [(chain[0][0], chain[0][1], chain[0][2]), ({"n": 99}, chain[1][1], chain[1][2])]
    assert not verify_links(tampered)


def test_reordering_breaks_verification():
    chain = _chain([{"n": 1}, {"n": 2}, {"n": 3}])
    assert not verify_links([chain[0], chain[2], chain[1]])


def test_a_broken_prev_link_breaks_verification():
    chain = _chain([{"n": 1}, {"n": 2}])
    assert not verify_links([chain[0], ({"n": 2}, "b" * 64, chain[1][2])])
