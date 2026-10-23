"""`waiting` and `document_suggested` for a document (spec §5.8, §6; documents.md §1, §7; D5 option b)."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Connection, text

from app.core.importers.providers import reset_document_providers
from app.core.settle.flags import recompute_review_flags
from app.core.settle.window import document_window
from tests.core.units.doc_helpers import make_doc_source, make_document, make_payee
from tests.core.units.helpers import Bench, D


@pytest.fixture(autouse=True)
def _registry() -> Any:
    reset_document_providers()
    yield
    reset_document_providers()


@pytest.fixture
def bench(db_conn: Connection, make_account: Any) -> Bench:
    return Bench(db_conn, make_account)


def _flags(conn: Connection, entry: int) -> list[str]:
    recompute_review_flags(conn)
    return list(
        conn.execute(text("SELECT review_flags FROM ledger_entry WHERE id = :i"), {"i": entry}).scalar_one()
    )


def _provider(conn: Connection) -> int:
    return make_payee(conn, "PayPal", "paypal")


def test_a_transaction_awaiting_its_document_waits(bench: Bench) -> None:
    make_doc_source(bench.conn)
    assert _flags(bench.conn, bench.flow(bench.source(), payee_id=_provider(bench.conn))) == ["waiting"]


def test_suggestions_alone_flag_document_suggested(bench: Bench) -> None:
    conn = bench.conn
    make_doc_source(conn, covered_through=D + timedelta(days=30))
    make_document(conn, total=-100)
    make_document(conn, total=-100, on=D + timedelta(days=1))
    assert _flags(conn, bench.flow(bench.source(), payee_id=_provider(conn))) == ["document_suggested"]


def test_a_unit_waiting_for_a_document_waits_even_with_suggestions(bench: Bench) -> None:
    conn = bench.conn
    make_doc_source(conn)  # never run: awaiting
    make_document(conn, total=-100)
    make_document(conn, total=-100, on=D + timedelta(days=1))
    entry = bench.flow(bench.source(), payee_id=_provider(conn))
    assert _flags(conn, entry) == ["document_suggested", "waiting"]


def test_no_source_no_waiting_no_flags(bench: Bench) -> None:
    assert _flags(bench.conn, bench.flow(bench.source(), payee_id=_provider(bench.conn))) == []


def test_the_wait_ends_when_the_coverage_reaches_the_window(bench: Bench) -> None:
    conn = bench.conn
    make_doc_source(conn, covered_through=D + timedelta(days=document_window(conn).ahead))
    assert _flags(conn, bench.flow(bench.source(), payee_id=_provider(conn))) == []


def test_a_decided_document_flags_nothing(bench: Bench) -> None:
    conn = bench.conn
    make_doc_source(conn)
    entry = bench.flow(
        bench.source(), payee_id=_provider(conn), derivation=json.dumps({"document": {"pass": "user"}})
    )
    assert _flags(conn, entry) == []


def test_the_flags_are_on_the_original_entry_of_a_split_only(bench: Bench) -> None:
    conn = bench.conn
    make_doc_source(conn)
    payee = _provider(conn)
    src = bench.source(parts=2)
    first, second = bench.flow(src, payee_id=payee), bench.flow(src, payee_id=payee)
    assert _flags(conn, first) == ["waiting"]
    assert _flags(conn, second) == []


def test_waiting_for_a_document_next_to_unconfirmed_values(bench: Bench) -> None:
    conn = bench.conn
    make_doc_source(conn)
    entry = bench.flow(
        bench.source(),
        payee_id=_provider(conn),
        derivation=json.dumps({"category": {"pass": "history"}}),
    )
    assert _flags(conn, entry) == ["unconfirmed", "waiting"]


def test_a_second_recompute_changes_nothing(bench: Bench) -> None:
    conn = bench.conn
    make_doc_source(conn)
    bench.flow(bench.source(), payee_id=_provider(conn))
    assert recompute_review_flags(conn) != []
    assert recompute_review_flags(conn) == []


def _order(conn: Connection, *amounts: int) -> int:
    doc = make_document(conn, total=sum(amounts))
    for n, amount in enumerate(amounts, start=1):
        conn.execute(
            text(
                "INSERT INTO external_document_line (document_id, line_no, description, amount)"
                " VALUES (:d, :n, 'item', :a)"
            ),
            {"d": doc, "n": n, "a": amount},
        )
    return doc


def test_the_charges_an_order_divides_among_are_no_suggestions(bench: Bench) -> None:
    conn = bench.conn
    _order(conn, -30, -20)
    payee = _provider(conn)
    thirty = bench.flow(bench.source(amount=-30), payee_id=payee)
    twenty = bench.flow(bench.source(amount=-20, on=D + timedelta(days=1)), payee_id=payee)
    assert _flags(conn, thirty) == [] and _flags(conn, twenty) == []  # settling is about to link both


def test_a_charge_the_order_cannot_divide_with_the_others_is_suggested(bench: Bench) -> None:
    conn = bench.conn
    _order(conn, -30, -20)
    payee = _provider(conn)
    first = bench.flow(bench.source(amount=-30), payee_id=payee)
    bench.flow(bench.source(amount=-30, on=D + timedelta(days=1)), payee_id=payee)
    assert _flags(conn, first) == ["document_suggested"]
