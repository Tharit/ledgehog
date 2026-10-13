"""The preview of a rule write: matches, shadowing, confirmable units, lists A and B (spec §5.9, D204)."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest
from sqlalchemy import Engine, text

from app.core.domain.source import SourceFields
from app.core.ledger.rules import RuleDraft, create_rule, delete_rule, update_rule
from tests.fixtures import ledger_seed as seed
from tests.fixtures import rule_seed as rs


@pytest.fixture
def w(isolated_engine: Engine) -> dict[str, Any]:
    with isolated_engine.begin() as conn:
        return {
            "acct": seed.account(conn, "Giro"),
            "cash": seed.account(conn, "Cash"),
            "usd": seed.account(conn, "Dollars", currency="USD"),
            "food": seed.category(conn, "Food"),
            "fun": seed.category(conn, "Fun"),
            "rewe": rs.payee(conn, "Rewe"),
            "other": rs.payee(conn, "Other"),
        }


def cat_draft(w: dict[str, Any], **kw: Any) -> RuleDraft:
    base: dict[str, Any] = {
        "name": "Rewe",
        "sets": "category",
        "category_id": w["food"],
        "conditions": (rs.name_is("REWE"),),
    }
    base.update(kw)
    return RuleDraft(**base)


def payee_draft(w: dict[str, Any], **kw: Any) -> RuleDraft:
    base: dict[str, Any] = {
        "name": "Rewe payee",
        "sets": "payee",
        "payee_id": w["rewe"],
        "conditions": (rs.name_is("REWE"),),
    }
    base.update(kw)
    return RuleDraft(**base)


def ids(rows: Any) -> set[int]:
    return {r.entry_id for r in rows}


# ---- (a) matches -----------------------------------------------------------------------------


def test_matches_are_exact_and_include_confirmed_entries(isolated_engine: Engine, w: dict[str, Any]):
    with isolated_engine.begin() as conn:
        a = rs.new_entry(conn, w["acct"], counterparty_name="REWE")
        b = rs.confirmed_entry(conn, w["acct"], category=w["fun"], counterparty_name="rewe ")
        rs.new_entry(conn, w["acct"], counterparty_name="LIDL")
        rs.new_entry(conn, w["acct"], counterparty_name="REWE", amount=-2500, booked_on=date(2026, 3, 1))
    p = create_rule(isolated_engine, cat_draft(w), dry_run=True).preview
    assert p.matches.total == 3
    assert [r.booked_on for r in p.matches.rows] == sorted(
        (r.booked_on for r in p.matches.rows), reverse=True
    )
    by = {r.entry_id: r for r in p.matches.rows}
    assert {a, b} <= set(by)
    assert by[b].confirmed and not by[a].confirmed
    assert (by[b].current_value, by[a].current_value) == (w["fun"], None)
    assert by[b].current_key == {"pass": "user"} and by[a].current_key is None
    assert (by[a].amount, by[a].currency) == (-1000, "EUR")
    assert by[a].source is not None and by[a].source.counterparty_name == "REWE"
    assert all(r.shadowed_by_rule_id is None for r in p.matches.rows)


def test_paging_of_the_lists(isolated_engine: Engine, w: dict[str, Any]):
    with isolated_engine.begin() as conn:
        for day in range(1, 6):  # confirmed with another value: settling will leave them, so A lists them
            rs.confirmed_entry(
                conn, w["acct"], category=w["fun"], counterparty_name="REWE", booked_on=date(2026, 3, day)
            )
    full = create_rule(isolated_engine, cat_draft(w), dry_run=True).preview
    page = create_rule(isolated_engine, cat_draft(w), dry_run=True, limit=2, offset=2).preview
    assert page.matches.total == page.different_value.total == 5
    assert [r.entry_id for r in page.matches.rows] == [r.entry_id for r in full.matches.rows][2:4]
    assert len(page.different_value.rows) == 2


def test_shadowed_by_an_earlier_rule_of_the_same_kind(isolated_engine: Engine, w: dict[str, Any]):
    with isolated_engine.begin() as conn:
        e = rs.new_entry(conn, w["acct"], counterparty_name="REWE")
        first = rs.rule(conn, "first", "category", w["fun"], conditions=(rs.name_is("REWE"),), priority=10)
        rs.rule(conn, "unrelated", "category", w["fun"], conditions=(rs.name_is("LIDL"),), priority=1)
    p = create_rule(isolated_engine, cat_draft(w, priority=50), dry_run=True).preview
    assert [(r.entry_id, r.shadowed_by_rule_id) for r in p.matches.rows] == [(e, first)]
    # a lower priority number goes first: the new rule is not shadowed then
    p = create_rule(isolated_engine, cat_draft(w, priority=5), dry_run=True).preview
    assert p.matches.rows[0].shadowed_by_rule_id is None
    # equal priority: the older id wins
    p = create_rule(isolated_engine, cat_draft(w, priority=10), dry_run=True).preview
    assert p.matches.rows[0].shadowed_by_rule_id == first


def test_shadowing_is_per_field_and_a_counter_account_rule_shadows_every_group(
    isolated_engine: Engine, w: dict[str, Any]
):
    with isolated_engine.begin() as conn:
        rs.new_entry(conn, w["acct"], counterparty_name="REWE")
        payee_rule = rs.rule(
            conn, "payee first", "payee", w["rewe"], conditions=(rs.name_is("REWE"),), priority=1
        )
        transfer = rs.rule(
            conn, "to cash", "counter_account", w["cash"], conditions=(rs.name_is("REWE"),), priority=500
        )
    # a payee rule does not shadow a category rule: they set different fields
    other = create_rule(isolated_engine, cat_draft(w, name="other cat"), dry_run=True).preview
    assert other.matches.rows[0].shadowed_by_rule_id == transfer
    with isolated_engine.begin() as conn:
        conn.execute(text("DELETE FROM rule WHERE id = :i"), {"i": transfer})
    p = create_rule(isolated_engine, cat_draft(w, name="other cat 2"), dry_run=True).preview
    assert p.matches.rows[0].shadowed_by_rule_id is None
    # a later payee rule is shadowed by the earlier payee rule
    q = create_rule(isolated_engine, payee_draft(w, name="second payee"), dry_run=True).preview
    assert q.matches.rows[0].shadowed_by_rule_id == payee_rule


def test_a_counter_account_rule_must_pass_the_currency_and_closing_tests(
    isolated_engine: Engine, w: dict[str, Any]
):
    with isolated_engine.begin() as conn:
        ok = rs.new_entry(conn, w["acct"], counterparty_name="ATM")
        rs.new_entry(
            conn,
            w["acct"],
            counterparty_name="ATM",
            instructed_currency="USD",
            instructed_amount=-5500,
            amount=-5000,
        )
        rs.new_entry(conn, w["cash"], counterparty_name="ATM", booked_on=date(2026, 2, 11))  # its own account
        late = rs.new_entry(conn, w["acct"], counterparty_name="ATM", booked_on=date(2026, 5, 1))
    d = RuleDraft(
        name="atm", sets="counter_account", counter_account_id=w["cash"], conditions=(rs.name_is("ATM"),)
    )
    p = create_rule(isolated_engine, d, dry_run=True).preview
    # not the USD one (currency rule), not the cash account's own entry
    assert ids(p.matches.rows) == {ok, late} and p.matches.total == 2
    with isolated_engine.begin() as conn:
        conn.execute(text("UPDATE account SET closed_on = '2026-03-01' WHERE id = :i"), {"i": w["cash"]})
    p = create_rule(isolated_engine, d, dry_run=True).preview
    assert ids(p.matches.rows) == {ok}
    d_usd = RuleDraft(
        name="atm usd", sets="counter_account", counter_account_id=w["usd"], conditions=(rs.name_is("ATM"),)
    )
    assert (
        create_rule(isolated_engine, d_usd, dry_run=True).preview.matches.total == 1
    )  # the instructed USD one


def test_a_category_rule_with_a_payee_condition_reads_the_stored_payee(
    isolated_engine: Engine, w: dict[str, Any]
):
    with isolated_engine.begin() as conn:
        a = rs.confirmed_entry(conn, w["acct"], category=w["fun"], payee=w["rewe"], counterparty_name="X")
        rs.confirmed_entry(conn, w["acct"], category=w["fun"], payee=w["other"], counterparty_name="X")
        rs.new_entry(conn, w["acct"], counterparty_name="X")  # no payee stored
    d = RuleDraft(name="by payee", sets="category", category_id=w["food"], condition_payee_id=w["rewe"])
    p = create_rule(isolated_engine, d, dry_run=True).preview
    assert ids(p.matches.rows) == {a} and p.matches.total == 1


# ---- (b) would_confirm -----------------------------------------------------------------------


def test_would_confirm_counts_the_units_the_rule_set_completes(isolated_engine: Engine, w: dict[str, Any]):
    with isolated_engine.begin() as conn:
        rs.new_entry(conn, w["acct"], counterparty_name="REWE")
        rs.new_entry(conn, w["acct"], counterparty_name="REWE", amount=-300)
        rs.confirmed_entry(conn, w["acct"], category=w["fun"], counterparty_name="REWE")  # not unconfirmed
    # a payee rule alone leaves the category open: both stay in review
    p = create_rule(isolated_engine, payee_draft(w), dry_run=True).preview
    assert (p.matches.total, p.would_confirm, p.stay_in_review) == (3, 0, 2)
    # a category rule completes a flow
    p = create_rule(isolated_engine, cat_draft(w), dry_run=True).preview
    assert (p.matches.total, p.would_confirm, p.stay_in_review) == (3, 2, 0)
    # with the category rule saved, the payee rule's units complete too (the post-change rule set)
    with isolated_engine.begin() as conn:
        rs.rule(conn, "cat", "category", w["food"], conditions=(rs.name_is("REWE"),))
    p = create_rule(isolated_engine, payee_draft(w), dry_run=True).preview
    assert (p.would_confirm, p.stay_in_review) == (2, 0)


def test_a_transfer_is_not_confirmable_before_pairing_and_a_split_unit_waits_for_all_its_entries(
    isolated_engine: Engine, w: dict[str, Any]
):
    from tests.invariants.helpers import make_entry

    with isolated_engine.begin() as conn:
        rs.new_entry(conn, w["acct"], counterparty_name="ATM")
        src = rs.source(conn, w["acct"], counterparty_name="REWE", amount=-1000)
        make_entry(conn, src, type=None, amount=-600)
        make_entry(conn, src, type=None, amount=-400)
    d = RuleDraft(
        name="atm", sets="counter_account", counter_account_id=w["cash"], conditions=(rs.name_is("ATM"),)
    )
    p = create_rule(isolated_engine, d, dry_run=True).preview
    assert (p.matches.total, p.would_confirm, p.stay_in_review) == (1, 0, 1)
    # both entries of the split match, and both are decided by the rule: the unit is confirmed
    with isolated_engine.begin() as conn:
        rs.rule(conn, "payee", "payee", w["rewe"], conditions=(rs.name_is("REWE"),))
    p = create_rule(isolated_engine, cat_draft(w), dry_run=True).preview
    assert (p.matches.total, p.would_confirm) == (2, 2)


def test_a_history_proposal_is_not_standing(isolated_engine: Engine, w: dict[str, Any]):
    with isolated_engine.begin() as conn:
        for _ in range(3):  # voters: REWE is Fun
            rs.confirmed_entry(
                conn, w["acct"], category=w["fun"], counterparty_name="REWE", counterparty_ref="DE01"
            )
        rs.new_entry(conn, w["acct"], counterparty_name="REWE", counterparty_ref="DE01")
    # the payee rule decides the type, history proposes the category: complete but not standing
    p = create_rule(
        isolated_engine,
        payee_draft(w, conditions=(rs.cond("counterparty_ref", "equals", "DE01"),)),
        dry_run=True,
    ).preview
    assert (p.would_confirm, p.stay_in_review) == (0, 1)


# ---- (c) list A ------------------------------------------------------------------------------


def test_list_a_holds_matched_entries_whose_different_value_settling_keeps(
    isolated_engine: Engine, w: dict[str, Any]
):
    with isolated_engine.begin() as conn:
        rid = rs.rule(conn, "rewe", "category", w["food"], conditions=(rs.name_is("REWE"),))
        same = rs.confirmed_entry(
            conn,
            w["acct"],
            category=w["food"],
            keys={"type": rs.key(rid), "category": rs.key(rid)},
            counterparty_name="REWE",
        )
        differs = rs.confirmed_entry(conn, w["acct"], category=w["fun"], counterparty_name="REWE")
        blank = rs.new_entry(conn, w["acct"], counterparty_name="REWE")  # nothing yet: settling decides it
        proposal = rs.confirmed_entry(  # a proposal: the settle that follows replaces it
            conn,
            w["acct"],
            category=w["fun"],
            keys={"type": {"pass": "history"}, "category": {"pass": "history"}},
            counterparty_name="REWE",
        )
        rs.confirmed_entry(conn, w["acct"], category=w["fun"], counterparty_name="LIDL")
    # create (a second rule of the same value): only the entries settling will leave alone
    p = create_rule(isolated_engine, cat_draft(w, name="again"), dry_run=True).preview
    assert ids(p.different_value.rows) == {differs} and p.different_value.total == 1
    assert {blank, proposal} <= ids(p.matches.rows)  # matched, but not for checking by hand
    assert all(r.shadowed_by_rule_id is None for r in p.different_value.rows)
    # edit: the target changes, so the entry that held the old value lands in A
    p = update_rule(isolated_engine, rid, cat_draft(w, category_id=w["fun"]), dry_run=True).preview
    assert ids(p.different_value.rows) == {same}  # the old value under a standing key stays
    row = next(r for r in p.different_value.rows if r.entry_id == same)
    assert row.current_value == w["food"] and row.current_key == rs.key(rid)
    # delete: there is no value to differ from
    p = delete_rule(isolated_engine, rid, dry_run=True).preview
    assert p.different_value.total == 0 and p.would_confirm == 0
    assert p.matches.total == 4  # what the rule matched


def test_list_a_of_a_counter_account_and_a_payee_rule(isolated_engine: Engine, w: dict[str, Any]):
    with isolated_engine.begin() as conn:
        rs.new_entry(conn, w["acct"], counterparty_name="ATM")
        b = rs.confirmed_entry(conn, w["acct"], category=w["fun"], payee=w["other"], counterparty_name="ATM")
    p = create_rule(isolated_engine, payee_draft(w, conditions=(rs.name_is("ATM"),)), dry_run=True).preview
    assert ids(p.different_value.rows) == {b}
    assert next(r for r in p.different_value.rows if r.entry_id == b).current_value == w["other"]


# ---- (c) list B ------------------------------------------------------------------------------


def test_list_b_holds_keyed_entries_the_edited_rule_no_longer_matches(
    isolated_engine: Engine, w: dict[str, Any]
):
    with isolated_engine.begin() as conn:
        rid = rs.rule(conn, "rewe", "payee", w["rewe"], conditions=(rs.name_starts("REWE"),))
        other = rs.rule(conn, "other", "payee", w["other"], conditions=(rs.name_starts("LIDL"),))
        keep = rs.confirmed_entry(
            conn,
            w["acct"],
            category=w["food"],
            payee=w["rewe"],
            keys={"payee": rs.key(rid)},
            counterparty_name="REWE MARKT",
        )
        lose = rs.confirmed_entry(
            conn,
            w["acct"],
            category=w["food"],
            payee=w["rewe"],
            keys={"type": rs.key(rid), "payee": rs.key(rid), "category": {"pass": "user"}},
            counterparty_name="REWE CITY",
        )
        type_only = rs.confirmed_entry(
            conn, w["acct"], category=w["food"], keys={"type": rs.key(rid)}, counterparty_name="REWE CITY"
        )
        rs.confirmed_entry(
            conn,
            w["acct"],
            category=w["food"],
            payee=w["other"],
            keys={"payee": rs.key(other)},
            counterparty_name="LIDL",
        )
    # unchanged conditions: nothing lost
    same = update_rule(
        isolated_engine,
        rid,
        payee_draft(w, name="rewe", conditions=(rs.name_starts("REWE"),)),
        dry_run=True,
    )
    assert same.preview.lost_key.total == 0
    # narrowed
    p = update_rule(
        isolated_engine,
        rid,
        payee_draft(w, name="rewe", conditions=(rs.name_starts("REWE MARKT"),)),
        dry_run=True,
    ).preview
    assert ids(p.lost_key.rows) == {lose, type_only} and p.lost_key.total == 2
    assert keep not in ids(p.lost_key.rows)
    fields = {r.entry_id: r.keyed_fields for r in p.lost_key.rows}
    assert fields[lose] == ("type", "payee") and fields[type_only] == ("type",)
    # delete: every entry carrying the key, and only this rule's
    p = delete_rule(isolated_engine, rid, dry_run=True).preview
    assert ids(p.lost_key.rows) == {keep, lose, type_only}
    # create: nothing carries a key yet
    assert create_rule(isolated_engine, payee_draft(w, name="new"), dry_run=True).preview.lost_key.total == 0


def test_list_b_counts_an_entry_the_rule_matches_by_conditions_but_not_by_account(
    isolated_engine: Engine, w: dict[str, Any]
):
    with isolated_engine.begin() as conn:
        rid = rs.rule(conn, "atm", "counter_account", w["cash"], conditions=(rs.name_is("ATM"),))
        e = rs.confirmed_entry(
            conn,
            w["acct"],
            category=w["food"],
            keys={"type": rs.key(rid), "counter_account": rs.key(rid)},
            counterparty_name="ATM",
        )
        conn.execute(text("UPDATE account SET closed_on = '2026-01-01' WHERE id = :i"), {"i": w["cash"]})
    d = RuleDraft(
        name="atm", sets="counter_account", counter_account_id=w["cash"], conditions=(rs.name_is("ATM"),)
    )
    p = update_rule(isolated_engine, rid, d, dry_run=True).preview
    assert ids(p.lost_key.rows) == {e}  # the closed wallet no longer matches


def test_every_row_list_carries_the_entry_source_without_extra_queries(
    isolated_engine: Engine, w: dict[str, Any]
):
    with isolated_engine.begin() as conn:
        a = rs.new_entry(
            conn,
            w["acct"],
            counterparty_name="REWE",
            counterparty_ref="DE01",
            counterparty_bic="BYLADEM1",
            purpose="Einkauf",
            booking_text="Kartenzahlung",
            end_to_end_id="E2E-1",
            mandate_ref="M-1",
            instructed_amount=-900,
            instructed_currency="USD",
        )
        # a user-authored row: no importer, run or format; it has only a purpose
        user = rs.new_entry(
            conn, w["acct"], importer=None, import_run_id=None, source_format=None, purpose="REWE Einkauf"
        )
        lost = rs.rule(conn, "old", "category", w["fun"], conditions=(rs.name_is("REWE"),))
        conn.execute(
            text("UPDATE ledger_entry SET derivation = CAST(:d AS jsonb) WHERE id = :i"),
            {"d": json.dumps({"category": rs.key(lost)}), "i": a},
        )
    draft = cat_draft(w, conditions=(rs.cond("purpose", "contains", "einkauf"), rs.name_is("REWE")))
    p = update_rule(isolated_engine, lost, draft, dry_run=True).preview
    assert [r.entry_id for r in p.matches.rows] == [a]
    src = p.matches.rows[0].source
    assert src == SourceFields(
        counterparty_name="REWE",
        counterparty_ref="DE01",
        counterparty_bic="BYLADEM1",
        purpose="Einkauf",
        booking_text="Kartenzahlung",
        end_to_end_id="E2E-1",
        mandate_ref="M-1",
        instructed_amount=-900,
        instructed_currency="USD",
        source_format="csv",
    )
    assert not hasattr(src, "raw") and not hasattr(src, "content_hash")
    # a condition on the purpose matches the user-authored row too, and it has no source
    only_purpose = cat_draft(w, name="by purpose", conditions=(rs.cond("purpose", "contains", "rewe"),))
    q = create_rule(isolated_engine, only_purpose, dry_run=True).preview
    by = {r.entry_id: r for r in q.matches.rows}
    assert set(by) == {user}  # the imported row's purpose is "Einkauf"
    assert by[user].source is None
    # list B (the old rule's key on an entry it no longer matches) carries it too
    assert [r.entry_id for r in create_rule(isolated_engine, draft, dry_run=True).preview.lost_key.rows] == []
    narrowed = update_rule(
        isolated_engine, lost, cat_draft(w, conditions=(rs.name_is("NOBODY"),)), dry_run=True
    )
    assert [r.entry_id for r in narrowed.preview.lost_key.rows] == [a]
    assert narrowed.preview.lost_key.rows[0].source == src


def test_the_preview_reads_the_sources_in_one_batch(isolated_engine: Engine, w: dict[str, Any]):
    """The number of statements does not grow with the number of rows (no query per row)."""
    from sqlalchemy import event

    def statements_for_preview() -> int:
        seen: list[str] = []

        def count(conn: Any, cursor: Any, statement: str, *rest: Any) -> None:
            seen.append(statement)

        event.listen(isolated_engine, "before_cursor_execute", count)
        try:
            create_rule(isolated_engine, cat_draft(w), dry_run=True)
        finally:
            event.remove(isolated_engine, "before_cursor_execute", count)
        return len(seen)

    with isolated_engine.begin() as conn:
        rs.new_entry(conn, w["acct"], counterparty_name="REWE")
    few = statements_for_preview()
    with isolated_engine.begin() as conn:
        for _ in range(12):
            rs.new_entry(conn, w["acct"], counterparty_name="REWE", purpose="x")
    assert statements_for_preview() == few
