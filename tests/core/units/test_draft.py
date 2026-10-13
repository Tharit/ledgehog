"""The draft model is pure: its shape is checked at construction (spec §6, architecture §4.1)."""

from __future__ import annotations

import pytest

from app.core.units.draft import KEEP, UNSET, DraftEntry, DraftError, FieldDraft, ShownBasis, UnitDraft


def code(fn) -> str:  # noqa: ANN001
    with pytest.raises(DraftError) as exc:
        fn()
    return exc.value.code


def test_a_field_draft_defaults_to_keep_and_only_fixed_carries_a_value() -> None:
    assert KEEP == FieldDraft("keep", None, None)
    assert FieldDraft("fixed", None).value is None  # fixed empty: the user clears the field
    assert code(lambda: FieldDraft("keep", 3)) == "invalid_field"
    assert code(lambda: FieldDraft("reresolve", None, ShownBasis("llm", {}))) == "invalid_field"
    assert code(lambda: FieldDraft("sometimes")) == "invalid_mode"  # type: ignore[arg-type]


@pytest.mark.parametrize("name", ["history", "llm", "matcher_proposal"])
def test_a_client_may_name_a_proposal_pass_as_a_basis(name: str) -> None:
    assert ShownBasis(name, {"n": 1}).pass_name == name


@pytest.mark.parametrize("name", ["rule", "own_account", "matcher_decision", "user", "", "History"])
def test_no_other_pass_is_a_basis(name: str) -> None:
    assert code(lambda: ShownBasis(name)) == "invalid_basis"


def test_a_stored_entry_has_no_source_and_a_new_one_names_it() -> None:
    assert DraftEntry(5).is_new is False and DraftEntry(-1, amount=-5, source_entry_id=5).is_new
    assert code(lambda: DraftEntry(5, source_entry_id=5)) == "invalid_new_entry"
    assert code(lambda: DraftEntry(-1, amount=-5)) == "invalid_new_entry"
    assert code(lambda: DraftEntry(-1, source_entry_id=5)) == "amount_missing"
    assert code(lambda: DraftEntry(0)) == "invalid_entry_id"
    assert code(lambda: DraftEntry(5, amount=0)) == "amount_zero"


def test_text_is_unset_unless_the_draft_says_so() -> None:
    e = DraftEntry(5)
    assert e.description is UNSET and e.note is UNSET
    assert DraftEntry(5, note=None).note is None  # empty it, not leave it


def test_values_are_checked_per_field() -> None:
    assert code(lambda: DraftEntry(5, type=FieldDraft("fixed", "flux"))) == "invalid_type"
    assert code(lambda: DraftEntry(5, type=FieldDraft("fixed", None))) == "invalid_type"
    assert code(lambda: DraftEntry(5, category=FieldDraft("fixed", -3))) == "invalid_value"
    assert code(lambda: DraftEntry(5, payee=FieldDraft("fixed", "x"))) == "invalid_value"
    assert DraftEntry(5, category=FieldDraft("fixed", None)).category.value is None


def test_a_unit_draft_names_each_entry_once() -> None:
    assert code(lambda: UnitDraft(1, [DraftEntry(1), DraftEntry(1)])) == "duplicate_entry"
    assert code(lambda: UnitDraft(1, removed_entry_ids=[2, 2])) == "duplicate_entry"
    assert code(lambda: UnitDraft(1, [DraftEntry(2)], removed_entry_ids=[2])) == "removed_and_edited"
    assert code(lambda: UnitDraft(1, removed_entry_ids=[1])) == "anchor_removed"
    assert code(lambda: UnitDraft(1, removed_entry_ids=[-1])) == "unknown_entry"
    assert code(lambda: UnitDraft(0)) == "invalid_anchor"


def test_entry_lookup_by_id_and_field_by_name() -> None:
    e = DraftEntry(2, category=FieldDraft("fixed", 9))
    d = UnitDraft(1, [e])
    assert d.entry(2) is e and d.entry(3) is None
    assert e.field("category").value == 9 and e.field("payee") is KEEP
