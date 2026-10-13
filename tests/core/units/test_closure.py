"""The closure of a unit in pure Python (spec §6, I31)."""

from __future__ import annotations

from app.core.units.closure import UnitEntry, unit_keys, units_of


def e(id: int, src: int | None, *, type: str | None = "flow", partner: int | None = None) -> UnitEntry:
    return UnitEntry(
        id=id,
        source_transaction_id=src,
        type=type,
        category_id=1 if type == "flow" else None,
        counterpart_entry_id=partner,
    )


def test_a_plain_entry_is_its_own_unit() -> None:
    assert unit_keys([e(1, 10)]) == {1: 10}


def test_the_entries_of_one_source_share_a_unit() -> None:
    assert unit_keys([e(1, 10), e(2, 10), e(3, 11)]) == {1: 10, 2: 10, 3: 11}


def test_a_pair_joins_the_two_sources_under_the_lower_one() -> None:
    legs = [e(1, 20, type="transfer", partner=2), e(2, 10, type="transfer", partner=1)]
    assert unit_keys(legs) == {1: 10, 2: 10}


def test_siblings_of_both_legs_join_the_pair() -> None:
    entries = [
        e(1, 10, type="transfer", partner=4),
        e(2, 10),
        e(3, 20),
        e(4, 20, type="transfer", partner=1),
        e(5, 30),
    ]
    assert unit_keys(entries) == {1: 10, 2: 10, 3: 10, 4: 10, 5: 30}
    grouped = units_of(entries)
    assert {k: [x.id for x in v] for k, v in grouped.items()} == {10: [1, 2, 3, 4], 30: [5]}


def test_derived_entries_are_in_no_unit() -> None:
    assert unit_keys([e(1, None, type="opening"), e(2, 10)]) == {2: 10}
    assert 1 not in {x.id for u in units_of([e(1, None, type="opening")]).values() for x in u}


def test_an_unpaired_transfer_is_alone() -> None:
    assert unit_keys([e(1, 10, type="transfer"), e(2, 10)]) == {1: 10, 2: 10}


def test_a_partner_outside_the_given_entries_is_not_followed() -> None:
    assert unit_keys([e(1, 20, type="transfer", partner=99)]) == {1: 20}


def test_a_chain_is_followed_transitively() -> None:
    # not reachable under I31 (one transfer per source) but the function does not rely on it
    entries = [
        e(1, 30, type="transfer", partner=2),
        e(2, 20, type="transfer", partner=1),
        e(3, 20, type="transfer", partner=4),
        e(4, 10, type="transfer", partner=3),
    ]
    assert set(unit_keys(entries).values()) == {10}
