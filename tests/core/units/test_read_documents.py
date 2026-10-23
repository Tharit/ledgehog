"""The review queue and a unit waiting for a document (documents.md §7, spec §6, plan D5 option b)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Connection

from app.core.importers.providers import reset_document_providers
from app.core.settle.flags import recompute_review_flags
from app.core.settle.window import document_window
from app.core.units.read import WaitingForDocument, review_queue
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


def _queue(bench: Bench) -> dict[str, Any]:
    recompute_review_flags(bench.conn)
    return {s.kind: s for s in review_queue(bench.conn).sections}


def test_a_unit_waiting_for_a_document_is_in_waiting_with_the_provider(bench: Bench) -> None:
    conn = bench.conn
    make_doc_source(conn)  # never run
    entry = bench.flow(bench.source(), payee_id=make_payee(conn, "PayPal", "paypal"))
    sections = _queue(bench)
    assert [u.anchor_entry_id for u in sections["waiting"].units] == [entry]
    unit = sections["waiting"].units[0]
    assert unit.waiting is None
    assert unit.waiting_document == WaitingForDocument(provider="paypal", covered_through=None)
    assert "waiting_for_document" in unit.state.reasons
    assert sections["pending_review"].total == 0


def test_covered_through_is_the_earliest_of_the_instances_still_holding_it(bench: Bench) -> None:
    conn = bench.conn
    window = document_window(conn).ahead
    behind = D + timedelta(days=1)
    make_doc_source(conn, "a", covered_through=behind)
    make_doc_source(conn, "b", covered_through=D + timedelta(days=window - 1))
    make_doc_source(conn, "c", covered_through=D + timedelta(days=window + 3))  # reached: not holding
    bench.flow(bench.source(), payee_id=make_payee(conn, "PayPal", "paypal"))
    unit = _queue(bench)["waiting"].units[0]
    assert unit.waiting_document == WaitingForDocument(provider="paypal", covered_through=behind)


def test_one_instance_never_run_makes_it_not_synced_yet(bench: Bench) -> None:
    conn = bench.conn
    make_doc_source(conn, "a", covered_through=D + timedelta(days=1))
    make_doc_source(conn, "b")
    bench.flow(bench.source(), payee_id=make_payee(conn, "PayPal", "paypal"))
    assert _queue(bench)["waiting"].units[0].waiting_document == WaitingForDocument("paypal", None)


def test_suggestions_alone_are_pending_review(bench: Bench) -> None:
    conn = bench.conn
    make_doc_source(conn, covered_through=D + timedelta(days=30))
    make_document(conn, total=-100)
    make_document(conn, total=-100, on=D + timedelta(days=1))
    entry = bench.flow(bench.source(), payee_id=make_payee(conn, "PayPal", "paypal"))
    sections = _queue(bench)
    assert [u.anchor_entry_id for u in sections["pending_review"].units] == [entry]
    unit = sections["pending_review"].units[0]
    assert unit.waiting_document is None and unit.state.reasons == ("document_suggested",)
    assert sections["waiting"].total == 0


def test_waiting_and_suggestions_together_are_waiting(bench: Bench) -> None:
    conn = bench.conn
    make_doc_source(conn)
    make_document(conn, total=-100)
    make_document(conn, total=-100, on=D + timedelta(days=1))
    entry = bench.flow(bench.source(), payee_id=make_payee(conn, "PayPal", "paypal"))
    sections = _queue(bench)
    assert [u.anchor_entry_id for u in sections["waiting"].units] == [entry]
    assert sections["waiting"].units[0].state.reasons == ("waiting_for_document", "document_suggested")


def test_a_partner_wait_still_shows_the_account(bench: Bench) -> None:
    conn = bench.conn
    make_doc_source(conn)
    bench.flow(bench.source(), payee_id=make_payee(conn, "PayPal", "paypal"))
    sections = _queue(bench)
    assert sections["waiting"].units[0].waiting is None
