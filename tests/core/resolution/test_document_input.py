"""A document as an input to resolution, from the database (spec §5.8, §5.9): what the loader hands rules and
history, and the history snapshot's key `document_merchant`."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import Connection, text

from app.core.plugins.classifier import EntryInput
from app.core.resolution.load import load_movements, load_unconfirmed
from app.core.resolution.snapshot import HistorySnapshot, load_snapshot, load_votes, touches
from tests.core.units.doc_helpers import make_document
from tests.invariants.helpers import make_category, make_entry, make_source

MakeAccount = Callable[..., int]
STANDING = {"type": {"pass": "user"}, "category": {"pass": "user"}, "payee": {"pass": "user"}}
DAY = date(2026, 3, 10)


def line(conn: Connection, doc: int, no: int, description: str, amount: int) -> int:
    return int(
        conn.execute(
            text(
                "INSERT INTO external_document_line (document_id, line_no, description, amount)"
                " VALUES (:d, :n, :t, :a) RETURNING id"
            ),
            {"d": doc, "n": no, "t": description, "a": amount},
        ).scalar_one()
    )


def merchant(conn: Connection, doc: int, name: str | None) -> None:
    conn.execute(text("UPDATE external_document SET merchant_name = :n WHERE id = :d"), {"n": name, "d": doc})


def inputs(conn: Connection, *, with_document: bool = True) -> dict[int, EntryInput]:
    return {u.input.entry_id: u.input for u in load_unconfirmed(conn, with_document=with_document)}


# ---- the loader ----------------------------------------------------------------------------------


def test_the_loader_gives_a_documented_entry_the_merchant_and_its_own_line_and_the_source_as_stored(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    doc = make_document(db_conn, total=-1000)
    merchant(db_conn, doc, "CloudNotes")
    own = line(db_conn, doc, 1, "Pro plan", -1000)
    src = make_source(db_conn, acct, amount=-1000, columns={"counterparty_name": "PAYPAL *X", "purpose": "P"})
    e = make_entry(db_conn, src, type=None, document_id=doc, document_line_id=own)
    got = inputs(db_conn)[e]
    assert (got.documented, got.document_merchant, got.document_line) == (True, "CloudNotes", "Pro plan")
    assert (got.counterparty_name, got.purpose) == ("PAYPAL *X", "P")  # the bank's, never rewritten


@pytest.mark.parametrize("key", ["user", "matcher_decision", "matcher_proposal"])
def test_the_loader_gives_the_pass_of_the_links_key(
    db_conn: Connection, make_account: MakeAccount, key: str
) -> None:
    acct = make_account(db_conn)
    doc = make_document(db_conn, total=-1000)
    src = make_source(db_conn, acct, amount=-1000)
    e = make_entry(
        db_conn, src, type=None, document_id=doc, derivation=json.dumps({"document": {"pass": key}})
    )
    assert inputs(db_conn)[e].document_pass == key
    assert inputs(db_conn, with_document=False)[e].document_pass is None


def test_an_undocumented_entry_has_no_document_fields(db_conn: Connection, make_account: MakeAccount) -> None:
    e = make_entry(db_conn, make_source(db_conn, make_account(db_conn)), type=None)
    got = inputs(db_conn)[e]
    assert (got.documented, got.document_merchant, got.document_line) == (False, None, None)


def test_the_loader_without_the_document_reads_none_of_it(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    doc = make_document(db_conn, total=-1000)
    merchant(db_conn, doc, "CloudNotes")
    own = line(db_conn, doc, 1, "Pro plan", -1000)
    e = make_entry(db_conn, make_source(db_conn, acct), type=None, document_id=doc, document_line_id=own)
    got = inputs(db_conn, with_document=False)[e]
    assert (got.documented, got.document_merchant, got.document_line) == (False, None, None)


def test_a_split_entry_shares_the_merchant_but_has_a_line_only_if_it_was_given_one(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    doc = make_document(db_conn, total=-1000)
    merchant(db_conn, doc, "Seeed")
    first, second = line(db_conn, doc, 1, "USB cable", -400), line(db_conn, doc, 2, "Case", -600)
    src = make_source(db_conn, acct, amount=-1000)
    original = make_entry(db_conn, src, amount=-400, type=None, document_id=doc, document_line_id=first)
    made_from_a_line = make_entry(db_conn, src, amount=-300, type=None, document_line_id=second)
    by_hand = make_entry(db_conn, src, amount=-300, type=None)
    got = inputs(db_conn)
    assert got[original].document_line == "USB cable"
    assert got[made_from_a_line].document_line == "Case"
    assert got[by_hand].document_line is None
    assert {got[e].document_merchant for e in (original, made_from_a_line, by_hand)} == {"Seeed"}


def test_an_unsplit_transaction_of_several_lines_has_no_line(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    doc = make_document(db_conn, total=-1000)
    line(db_conn, doc, 1, "USB cable", -400)
    line(db_conn, doc, 2, "Case", -600)
    e = make_entry(db_conn, make_source(db_conn, acct), type=None, document_id=doc)
    got = inputs(db_conn)[e]
    assert got.documented and got.document_line is None


def test_a_line_of_another_document_is_ignored(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    doc = make_document(db_conn, total=-1000, external_id="mine")
    other = make_document(db_conn, total=-77, external_id="other")
    stray = line(db_conn, other, 1, "Not mine", -77)
    e = make_entry(db_conn, make_source(db_conn, acct), type=None, document_id=doc, document_line_id=stray)
    assert inputs(db_conn)[e].document_line is None
    # and an entry whose transaction carries no document ignores a stale reference altogether
    e2 = make_entry(
        db_conn, make_source(db_conn, acct), type=None, document_line_id=line(db_conn, doc, 1, "X", -1)
    )
    assert inputs(db_conn)[e2].document_line is None


def test_every_movement_is_loaded_with_its_document_fields(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    doc = make_document(db_conn, total=-1000)
    merchant(db_conn, doc, "CloudNotes")
    cat = make_category(db_conn, "Software")
    e = make_entry(
        db_conn,
        make_source(db_conn, acct),
        category_id=cat,
        document_id=doc,
        derivation=json.dumps({**STANDING, "document": {"pass": "user"}}),
    )
    (loaded,) = [m for m in load_movements(db_conn) if m.input.entry_id == e]
    assert loaded.confirmed and loaded.input.document_merchant == "CloudNotes"


# ---- the votes and the snapshot -----------------------------------------------------------------


def confirmed(
    conn: Connection, acct: int, cat: int, *, doc: int | None = None, on: date = DAY, name: str = "PAYPAL *X"
) -> int:
    key = {**STANDING, "document": {"pass": "user"}} if doc is not None else STANDING
    src = make_source(conn, acct, booked_on=on, columns={"counterparty_name": name})
    cols: dict[str, Any] = {"category_id": cat, "derivation": json.dumps(key)}
    if doc is not None:
        cols["document_id"] = doc
    return make_entry(conn, src, **cols)


def test_a_documented_vote_carries_its_merchant_and_an_undocumented_one_does_not(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    cat = make_category(db_conn, "Software")
    doc = make_document(db_conn, total=-1000)
    merchant(db_conn, doc, "CloudNotes")
    with_doc, without = confirmed(db_conn, acct, cat, doc=doc), confirmed(db_conn, acct, cat)
    votes = {v.entry_id: v for v in load_votes(db_conn)}
    assert (votes[with_doc].documented, votes[with_doc].document_merchant) == (True, "CloudNotes")
    assert (votes[without].documented, votes[without].document_merchant) == (False, None)


def test_the_snapshot_answers_key6_from_documented_votes_only_and_keys_1_to_5_from_the_others(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    cat = make_category(db_conn, "Software")
    doc, other_doc = make_document(db_conn, total=-1000), make_document(db_conn, total=-500, external_id="o")
    merchant(db_conn, doc, "CloudNotes GmbH")
    merchant(db_conn, other_doc, "Somebody Else")
    documented_vote = confirmed(db_conn, acct, cat, doc=doc)
    other_vote = confirmed(db_conn, acct, cat, doc=other_doc)
    plain = confirmed(db_conn, acct, cat)  # the same bank text, no document
    snap = load_snapshot(db_conn)
    asking = EntryInput(
        1, acct, "EUR", DAY, -1, counterparty_name="PAYPAL *X", document_merchant="cloudnotes, gmbh"
    )
    assert [v.entry_id for v in snap.candidates("document_merchant", asking)] == [documented_vote]
    # an undocumented entry has no merchant: key 6 finds nothing
    assert snap.candidates("document_merchant", EntryInput(1, acct, "EUR", DAY, -1)) == []
    # the raw keys see the undocumented voter only, whatever the bank text of the documented ones
    assert [v.entry_id for v in snap.candidates("counterparty_name", asking)] == [plain]
    assert other_vote not in [v.entry_id for v in snap.candidates("tokens", asking)]


def test_key6_respects_the_lookback_and_the_exclusion() -> None:
    from tests.plugins.classifiers.fakes import vote

    inside = vote(documented=True, document_merchant="CloudNotes", booked_on=DAY - timedelta(days=365))
    outside = vote(documented=True, document_merchant="CloudNotes", booked_on=DAY - timedelta(days=366))
    snap = HistorySnapshot([inside, outside])
    e = EntryInput(1, 1, "EUR", DAY, -1, documented=True, document_merchant="cloudnotes")
    assert [v.entry_id for v in snap.candidates("document_merchant", e)] == [inside.entry_id]
    assert snap.candidates("document_merchant", e, exclude_entry_ids=frozenset({inside.entry_id})) == []


def test_a_documented_vote_without_a_merchant_votes_for_nothing() -> None:
    from tests.plugins.classifiers.fakes import vote

    snap = HistorySnapshot([vote(documented=True, document_merchant=None, counterparty_name="X")])
    assert snap.candidates("document_merchant", EntryInput(1, 1, "EUR", DAY, -1, document_merchant="x")) == []
    assert snap.candidates("counterparty_name", EntryInput(1, 1, "EUR", DAY, -1, counterparty_name="X")) == []


@pytest.mark.parametrize("documented", [True, False])
def test_touches_reads_the_merchant_for_a_documented_entry_only(documented: bool) -> None:
    from tests.plugins.classifiers.fakes import vote

    grown = HistorySnapshot().add(
        [vote(documented=True, document_merchant="CloudNotes", counterparty_name="PAYPAL *CN", payee_id=5)]
    )
    e = EntryInput(
        1,
        1,
        "EUR",
        DAY,
        -1,
        counterparty_name="PAYPAL *CN",
        documented=documented,
        document_merchant="cloudnotes",
    )
    assert (
        touches(grown, e, None) is documented
    )  # an undocumented entry never sees key 6, nor the voter's raw keys
    assert not touches(grown, EntryInput(1, 1, "EUR", DAY, -1, documented=True, document_merchant="Other"), 5)
