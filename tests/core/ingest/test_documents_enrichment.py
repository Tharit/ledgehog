"""A changed document resolves its unconfirmed carrier afresh WITHOUT the document, and settling then links
and derives again from the document as it now is (spec §5.5, §5.9; documents.md §4, §5)."""

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
            text("SELECT payee_id, document_id, derivation FROM ledger_entry WHERE id = :i"), {"i": entry}
        ).one()


def setup(engine: Engine, make_account: Callable[..., int]) -> dict[str, int]:
    """A charge by card text `PAYPAL *X` (rule: the provider payee) and rules on two merchants' names."""
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
        rs.rule(conn, "old", "payee", old, conditions=(rs.name_is("Old Shop"),))
        rs.rule(conn, "new", "payee", new, conditions=(rs.name_is("New Shop"),))
        src = make_source(conn, acct, amount=-1000, booked_on=ON, columns={"counterparty_name": "PAYPAL *X"})
        entry = make_entry(conn, src, type=None)
    return {"entry": entry, "provider": provider, "old": old, "new": new}


def test_a_delivered_document_is_linked_and_enriches_the_resolution(isolated_engine, make_account):
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
    assert r.payee_id == w["new"]  # from the new merchant, not the old one the stale link enriched
    assert r.derivation["document"]["pass"] == "matcher_decision"


def test_the_afresh_resolution_does_not_read_the_document_it_drops(isolated_engine, make_account):
    w = setup(isolated_engine, make_account)
    deliver(isolated_engine, document(merchant_name="Old Shop"))
    assert row(isolated_engine, w["entry"]).payee_id == w["old"]
    with isolated_engine.begin() as conn:
        assert reresolve_unconfirmed_carrier(conn, [w["entry"]]) == [w["entry"]]
    r = row(isolated_engine, w["entry"])
    # the bank's text decides: the provider payee, not the payee the old enrichment gave
    assert r.document_id is None and r.payee_id == w["provider"]
    assert "document" not in r.derivation


def test_a_changed_document_that_no_longer_matches_leaves_the_entry_without_it(isolated_engine, make_account):
    w = setup(isolated_engine, make_account)
    deliver(isolated_engine, document(merchant_name="Old Shop"))
    deliver(isolated_engine, document(merchant_name="Old Shop", total_minor=-1100))
    r = row(isolated_engine, w["entry"])
    assert r.document_id is None and r.payee_id == w["provider"]
