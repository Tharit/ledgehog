"""The review state of a unit in pure Python (spec §6, I20, I22)."""

from __future__ import annotations

from typing import Any

import pytest

from app.core.units.closure import UnitEntry
from app.core.units.state import unit_state


def e(
    id: int,
    *,
    type: str | None = "flow",
    category: int | None = 1,
    partner: int | None = None,
    derivation: dict[str, Any] | None = None,
    src: int | None = 10,
) -> UnitEntry:
    return UnitEntry(
        id=id,
        source_transaction_id=src,
        type=type,
        category_id=category,
        counterpart_entry_id=partner,
        derivation=derivation or {},
    )


def test_a_complete_unit_with_standing_keys_is_confirmed() -> None:
    s = unit_state([e(1, derivation={"category": {"pass": "rule"}, "type": {"pass": "user"}}), e(2)])
    assert s.confirmed and s.reasons == () and s.flags == {1: (), 2: ()}


@pytest.mark.parametrize("p", ["history", "llm", "", "bogus"])
def test_a_proposal_key_holds_up_the_whole_unit(p: str) -> None:
    s = unit_state([e(1, derivation={"category": {"pass": p}}), e(2)])
    assert not s.confirmed and s.reasons == ("non_standing_keys",)
    assert s.flags == {1: ("unconfirmed",), 2: ("unconfirmed",)}


def test_a_key_without_a_pass_or_not_an_object_is_not_standing() -> None:
    assert unit_state([e(1, derivation={"category": {}})]).reasons == ("non_standing_keys",)
    assert unit_state([e(1, derivation={"category": "rule"})]).reasons == ("non_standing_keys",)


def test_an_incomplete_sibling_holds_up_the_unit_without_marking_the_complete_one() -> None:
    s = unit_state([e(1), e(2, category=None)])
    assert not s.confirmed and s.reasons == ("incomplete",)
    assert s.flags == {1: (), 2: ("unclassified",)}


def test_no_type_is_unclassified() -> None:
    s = unit_state([e(1, type=None, category=None)])
    assert s.reasons == ("incomplete",) and s.flags == {1: ("unclassified",)}


def test_an_unpaired_transfer_is_not_confirmed_and_carries_no_flag() -> None:
    s = unit_state([e(1, type="transfer", category=None)])
    assert not s.confirmed and s.reasons == ("unpaired_transfer",) and s.flags == {1: ()}


def test_a_paired_transfer_is_confirmed() -> None:
    legs = [
        e(1, type="transfer", category=None, partner=2),
        e(2, type="transfer", category=None, src=20, partner=1),
    ]
    assert unit_state(legs).confirmed


def test_a_partner_with_a_proposal_marks_both_legs_and_the_siblings() -> None:
    legs = [
        e(1, type="transfer", category=None, partner=3),
        e(2),
        e(
            3,
            type="transfer",
            category=None,
            partner=1,
            src=20,
            derivation={"counter_account": {"pass": "history"}},
        ),
    ]
    s = unit_state(legs)
    assert s.flags == {1: ("unconfirmed",), 2: ("unconfirmed",), 3: ("unconfirmed",)}


def test_reasons_come_in_a_fixed_order_and_flags_sorted() -> None:
    s = unit_state(
        [e(1, category=None, derivation={"x": {"pass": "llm"}}), e(2, type="transfer", category=None)]
    )
    assert s.reasons == ("incomplete", "unpaired_transfer", "non_standing_keys")
    assert s.flags[1] == ("unclassified", "unconfirmed")


def test_a_derived_entry_is_in_no_unit() -> None:
    with pytest.raises(ValueError):
        unit_state([e(1, src=None, type="opening", category=None)])
