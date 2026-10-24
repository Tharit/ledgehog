"""The removal routine (spec §5.6 'Removing an entry and its consequences')."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from app.core.domain.errors import IngestError
from app.core.ingest import removal
from app.core.ingest.removal import remove_entries
from tests.core.ingest.dup_helpers import Ledger


def test_partner_loses_counterpart_and_the_counter_account_the_pair_set(ledger: Ledger) -> None:
    a_src, a, _, b = ledger.transfer_pair()
    with ledger.engine.begin() as conn:
        affected = remove_entries(conn, [a])
        ledger.mark_dup(conn, a_src)  # the caller's half: the row must not be left entry-less
    assert ledger.q("SELECT id FROM ledger_entry WHERE id = :i", i=a) == []
    partner = ledger.one("SELECT * FROM ledger_entry WHERE id = :i", i=b)
    assert partner.counterpart_entry_id is None and partner.counter_account_id is None
    assert "counter_account" not in partner.derivation
    # everything else is kept, the system-created counter-leg stays
    assert (partner.type, partner.description, partner.note) == ("transfer", "in", "keep b")
    assert affected.removed_entry_ids == (a,)
    assert affected.partner_entry_ids == (b,)
    assert affected.account_ids == (ledger.checking, ledger.savings)
    ledger.assert_checks_clean()


def test_a_counter_account_the_leg_had_before_the_pair_stays(ledger: Ledger) -> None:
    a_src, a, _, b = ledger.transfer_pair()
    own = json.dumps({"counter_account": {"pass": "rule", "basis": {"rule_id": 3}}})
    with ledger.engine.begin() as conn:
        conn.execute(
            text("UPDATE ledger_entry SET derivation = CAST(:d AS jsonb) WHERE id = :i"),
            {"d": own, "i": b},
        )
        remove_entries(conn, [a])
        ledger.mark_dup(conn, a_src)
    partner = ledger.one("SELECT * FROM ledger_entry WHERE id = :i", i=b)
    assert partner.counterpart_entry_id is None
    assert partner.counter_account_id == ledger.checking
    assert partner.derivation["counter_account"]["pass"] == "rule"
    ledger.assert_checks_clean()


def test_a_carried_document_is_freed_and_tags_go(ledger: Ledger) -> None:
    src, e = ledger.movement(amount=-900)
    with ledger.engine.begin() as conn:
        doc = conn.execute(
            text(
                "INSERT INTO external_document (provider, external_id, occurred_on, total, currency, raw)"
                " VALUES ('shop', 'o1', :d, -900, 'EUR', '{}') RETURNING id"
            ),
            {"d": ledger.one("SELECT booked_on FROM source_transaction WHERE id = :s", s=src).booked_on},
        ).scalar_one()
        tag = conn.execute(text("INSERT INTO tag (name) VALUES ('t') RETURNING id")).scalar_one()
        conn.execute(text("UPDATE ledger_entry SET document_id = :d WHERE id = :e"), {"d": doc, "e": e})
        conn.execute(text("INSERT INTO ledger_entry_tag VALUES (:e, :t)"), {"e": e, "t": tag})
    with ledger.engine.begin() as conn:
        # the routine leaves the source row's fate to the caller: here the row goes too (a revert)
        affected = remove_entries(conn, [e])
        conn.execute(text("DELETE FROM source_transaction WHERE id = :s"), {"s": src})
    assert affected.freed_document_ids == (doc,)
    assert ledger.one("SELECT count(*) FROM ledger_entry WHERE document_id = :d", d=doc)[0] == 0
    assert ledger.q("SELECT * FROM ledger_entry_tag") == []
    ledger.assert_checks_clean()


def test_removing_both_legs_of_a_pair_leaves_no_partner(ledger: Ledger) -> None:
    a_src, a, b_src, b = ledger.transfer_pair()
    with ledger.engine.begin() as conn:
        affected = remove_entries(conn, [b, a])
        ledger.mark_dup(conn, a_src)
        conn.execute(text("DELETE FROM source_transaction WHERE id = :s"), {"s": b_src})
    assert affected.removed_entry_ids == (a, b)
    assert affected.partner_entry_ids == ()
    assert ledger.q("SELECT id FROM ledger_entry WHERE id IN (:a, :b)", a=a, b=b) == []
    ledger.assert_checks_clean()


def test_a_split_is_removed_whole_and_nothing_else_is_touched(ledger: Ledger) -> None:
    keep_src, keep = ledger.movement(amount=-70)
    src, (e1, e2) = ledger.split(-1000, -2000)
    with ledger.engine.begin() as conn:
        affected = remove_entries(conn, [e2, e1])
        conn.execute(
            text("UPDATE source_transaction SET duplicate_of = :k WHERE id = :s"),
            {"k": keep_src, "s": src},
        )
    assert affected.removed_entry_ids == (e1, e2) and affected.partner_entry_ids == ()
    assert [r.id for r in ledger.q("SELECT id FROM ledger_entry")] == [keep]
    ledger.assert_checks_clean()


def test_the_derived_entries_of_every_affected_account_are_recomputed(
    ledger: Ledger, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[int] = []
    monkeypatch.setattr(removal, "recompute_derived", lambda conn, account_id: seen.append(account_id))
    a_src, a, _, _ = ledger.transfer_pair()
    with ledger.engine.begin() as conn:
        removal.remove_entries(conn, [a])
        ledger.mark_dup(conn, a_src)
    assert seen == [ledger.checking, ledger.savings]


# ---- unpair: the unpair half of the routine, deleting nothing -------------------------------------


def _version(ledger: Ledger, entry_id: int) -> int:
    return int(ledger.one("SELECT version FROM ledger_entry WHERE id = :i", i=entry_id).version)


def test_unpair_frees_both_legs_and_clears_what_the_pair_set(ledger: Ledger) -> None:
    _, a, _, b = ledger.transfer_pair()
    before = {a: _version(ledger, a), b: _version(ledger, b)}
    with ledger.engine.begin() as conn:
        affected = removal.unpair(conn, [a])
    for entry_id, other in ((a, "out"), (b, "in")):
        row = ledger.one("SELECT * FROM ledger_entry WHERE id = :i", i=entry_id)
        assert row.counterpart_entry_id is None and row.counter_account_id is None
        assert "counter_account" not in row.derivation
        assert row.type == "transfer" and row.description == other  # everything else stays
        assert row.version == before[entry_id] + 1  # the link is structural
    assert affected.partner_entry_ids == (b,)
    assert affected.unpaired_entry_ids == (a, b)
    assert affected.removed_entry_ids == ()
    assert affected.account_ids == (ledger.checking, ledger.savings)
    ledger.assert_checks_clean()


def test_unpair_keeps_a_counter_account_the_leg_had_before_it_was_paired(ledger: Ledger) -> None:
    _, a, _, b = ledger.transfer_pair()
    own = json.dumps({"counter_account": {"pass": "rule", "basis": {"rule_id": 3}}})
    with ledger.engine.begin() as conn:
        conn.execute(
            text("UPDATE ledger_entry SET derivation = CAST(:d AS jsonb) WHERE id = :i"), {"d": own, "i": b}
        )
        removal.unpair(conn, [a])
    own_side = ledger.one("SELECT * FROM ledger_entry WHERE id = :i", i=b)
    assert (
        own_side.counter_account_id == ledger.checking
        and own_side.derivation["counter_account"]["pass"] == "rule"
    )
    assert (
        ledger.one("SELECT counter_account_id FROM ledger_entry WHERE id = :i", i=a).counter_account_id
        is None
    )


def test_unpair_drops_the_pair_key_from_both_legs(ledger: Ledger) -> None:
    _, a, _, b = ledger.transfer_pair()
    key = json.dumps({"counterpart": {"pass": "matcher_decision"}, "payee": {"pass": "user"}})
    with ledger.engine.begin() as conn:
        for e in (a, b):
            conn.execute(
                text("UPDATE ledger_entry SET derivation = derivation || CAST(:d AS jsonb) WHERE id = :i"),
                {"d": key, "i": e},
            )
        removal.unpair(conn, [b])
    for e in (a, b):
        derivation = ledger.one("SELECT derivation FROM ledger_entry WHERE id = :i", i=e).derivation
        assert "counterpart" not in derivation and derivation["payee"] == {"pass": "user"}


def test_unpair_of_both_legs_and_of_an_unpaired_entry(ledger: Ledger) -> None:
    _, a, _, b = ledger.transfer_pair()
    _, lone = ledger.movement(amount=-70)
    with ledger.engine.begin() as conn:
        both = removal.unpair(conn, [b, a])
        nothing = removal.unpair(conn, [lone])
        none = removal.unpair(conn, [])
    assert both.partner_entry_ids == () and both.unpaired_entry_ids == (a, b)
    assert nothing.unpaired_entry_ids == () and nothing.partner_entry_ids == ()
    assert none == removal.Affected()
    assert ledger.one("SELECT version FROM ledger_entry WHERE id = :i", i=lone).version == 1
    ledger.assert_checks_clean()


def test_unpair_refuses_an_unknown_entry_and_deletes_nothing(ledger: Ledger) -> None:
    _, a, _, b = ledger.transfer_pair()
    with pytest.raises(IngestError, match="no such entries"), ledger.engine.begin() as conn:
        removal.unpair(conn, [a, 999_999])
    assert (
        ledger.one("SELECT counterpart_entry_id FROM ledger_entry WHERE id = :i", i=a).counterpart_entry_id
        == b
    )
