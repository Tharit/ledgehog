"""A changed document resolves its unconfirmed carrier afresh WITHOUT the document (link, key and line dropped
together), and settling then links and derives again from the document as it now is (spec §5.5, §5.9;
documents.md §4, §5). A document is an input rules read, never a rewrite of the source."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from sqlalchemy import Engine, text

from app.core.ingest.documents import ingest_documents, reresolve_unconfirmed_carrier
from app.core.ingest.run import start_run
from app.core.plugins.importer import IncomingDocument
from tests.core.units.doc_helpers import make_payee
from tests.fixtures import rule_seed as rs
from tests.invariants.helpers import make_entry, make_source
from tests.plugins.importers.fakes import document, line

ON = date(2026, 6, 1)


def deliver(engine: Engine, *docs: IncomingDocument) -> Any:
    run_id = start_run(engine, None, "documents", importer="fake")
    return ingest_documents(engine, run_id, docs, covered_through=date(2026, 6, 30))


def row(engine: Engine, entry: int) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT payee_id, document_id, document_line_id, derivation FROM ledger_entry WHERE id = :i"
            ),
            {"i": entry},
        ).one()


def setup(engine: Engine, make_account: Callable[..., int]) -> dict[str, int]:
    """A charge by card text `PAYPAL *X` (rule: the provider payee) and rules on two merchants' names, ordered
    before the card rule (a rule on the document's merchant is the explicit act of curating it)."""
    with engine.begin() as conn:
        acct = make_account(conn)
        provider = make_payee(conn, "PayPal", "paypal")
        old, new = make_payee(conn, "Old Shop", None), make_payee(conn, "New Shop", None)
        rs.rule(
            conn,
            "card",
            "payee",
            provider,
            conditions=(rs.cond("counterparty_name", "starts_with", "PAYPAL"),),
        )
        merchant = "document_merchant"
        rs.rule(conn, "old", "payee", old, conditions=(rs.cond(merchant, "equals", "Old Shop"),), priority=50)
        rs.rule(conn, "new", "payee", new, conditions=(rs.cond(merchant, "equals", "New Shop"),), priority=50)
        src = make_source(conn, acct, amount=-1000, booked_on=ON, columns={"counterparty_name": "PAYPAL *X"})
        entry = make_entry(conn, src, type=None)
    return {"entry": entry, "provider": provider, "old": old, "new": new}


def test_a_delivered_document_is_linked_and_a_rule_on_its_merchant_decides(isolated_engine, make_account):
    w = setup(isolated_engine, make_account)
    result = deliver(isolated_engine, document(merchant_name="Old Shop", lines=(line("Cable", -1000),)))
    assert result.settle.error is None
    r = row(isolated_engine, w["entry"])
    assert r.document_id is not None and r.payee_id == w["old"]


def test_a_changed_document_derives_the_values_again_from_the_new_content(isolated_engine, make_account):
    w = setup(isolated_engine, make_account)
    deliver(isolated_engine, document(merchant_name="Old Shop"))
    result = deliver(isolated_engine, document(merchant_name="New Shop"))
    assert result.reresolved_entry_ids == (w["entry"],)
    r = row(isolated_engine, w["entry"])
    assert r.document_id is not None  # settling linked it again
    assert r.payee_id == w["new"]  # from the new merchant, not the old one the stale link had
    assert r.derivation["document"]["pass"] == "matcher_decision"


def test_the_afresh_resolution_does_not_read_the_document_it_drops(isolated_engine, make_account):
    w = setup(isolated_engine, make_account)
    deliver(isolated_engine, document(merchant_name="Old Shop"))
    assert row(isolated_engine, w["entry"]).payee_id == w["old"]
    with isolated_engine.begin() as conn:
        assert reresolve_unconfirmed_carrier(conn, [w["entry"]]) == [w["entry"]]
    r = row(isolated_engine, w["entry"])
    # the bank's text decides: the provider payee, not the payee the old merchant gave
    assert r.document_id is None and r.payee_id == w["provider"]
    assert "document" not in r.derivation


def test_a_changed_document_that_no_longer_matches_leaves_the_entry_without_it(isolated_engine, make_account):
    w = setup(isolated_engine, make_account)
    deliver(isolated_engine, document(merchant_name="Old Shop"))
    deliver(isolated_engine, document(merchant_name="Old Shop", total_minor=-1100))
    r = row(isolated_engine, w["entry"])
    assert r.document_id is None and r.payee_id == w["provider"]


def lines_of(engine: Engine, entry: int) -> tuple[int | None, list[int]]:
    with engine.connect() as conn:
        carried = conn.execute(
            text("SELECT document_line_id FROM ledger_entry WHERE id = :i"), {"i": entry}
        ).scalar_one()
        ids = conn.execute(text("SELECT id FROM external_document_line ORDER BY line_no")).scalars().all()
    return carried, [int(i) for i in ids]


def test_a_document_of_one_line_gives_the_entry_its_line_and_a_changed_one_gives_it_again(
    isolated_engine, make_account
):
    w = setup(isolated_engine, make_account)
    deliver(isolated_engine, document(merchant_name="Old Shop", lines=(line("Cable", -1000),)))
    carried, ids = lines_of(isolated_engine, w["entry"])
    assert carried is not None and ids == [carried]
    # the lines are replaced (delete and insert): the reference is cleared and settling gives the new line
    result = deliver(isolated_engine, document(merchant_name="New Shop", lines=(line("Cable 2", -1000),)))
    assert result.reresolved_entry_ids == (w["entry"],)
    carried2, ids2 = lines_of(isolated_engine, w["entry"])
    assert carried2 is not None and ids2 == [carried2] and carried2 != carried
    assert row(isolated_engine, w["entry"]).payee_id == w["new"]


def test_the_afresh_resolution_drops_the_link_the_key_and_the_line_in_one_write(
    isolated_engine, make_account
):
    w = setup(isolated_engine, make_account)
    deliver(isolated_engine, document(merchant_name="Old Shop", lines=(line("Cable", -1000),)))
    assert row(isolated_engine, w["entry"]).document_line_id is not None
    with isolated_engine.begin() as conn:
        reresolve_unconfirmed_carrier(conn, [w["entry"]])
    r = row(isolated_engine, w["entry"])
    assert (r.document_id, r.document_line_id) == (None, None)


def test_a_changed_document_of_a_confirmed_carrier_keeps_the_link_and_loses_the_line(
    isolated_engine, make_account
):
    w = setup(isolated_engine, make_account)
    deliver(isolated_engine, document(merchant_name="Old Shop", lines=(line("Cable", -1000),)))
    with isolated_engine.begin() as conn:  # the user confirmed it: standing keys on a complete unit
        cat = conn.execute(
            text("INSERT INTO category (name, kind) VALUES ('c', 'expense') RETURNING id")
        ).scalar_one()
        conn.execute(
            text(
                "UPDATE ledger_entry SET category_id = :c, derivation = derivation || CAST(:k AS jsonb)"
                " WHERE id = :i"
            ),
            {
                "c": cat,
                "i": w["entry"],
                "k": '{"type": {"pass": "user"}, "payee": {"pass": "user"}, "category": {"pass": "user"},'
                ' "document": {"pass": "user"}}',
            },
        )
    version = lines_version(isolated_engine, w["entry"])
    result = deliver(
        isolated_engine, document(merchant_name="Old Shop", lines=(line("Cable, new text", -1000),))
    )
    assert result.reresolved_entry_ids == ()  # I20: a confirmed unit is left alone
    r = row(isolated_engine, w["entry"])
    assert r.document_id is not None and r.document_line_id is None  # the line reference is gone (SET NULL)
    assert lines_version(isolated_engine, w["entry"]) > version  # and the entry's version moved with it


def lines_version(engine: Engine, entry: int) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(text("SELECT version FROM ledger_entry WHERE id = :i"), {"i": entry}).scalar_one()
        )
