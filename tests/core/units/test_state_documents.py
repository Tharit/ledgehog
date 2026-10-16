"""A unit with a document open is not confirmed (spec §6, documents.md §1, §7): the SQL of `units_sql`
(`doc_awaited`, `doc_suggested`, `unit_ok`) pinned to its Python twin over a matrix of cases.

The matrix is generated: provider payees and others, entries with and without a decided `document`, split
transactions, instructed currencies, carried documents, shared candidates, and document sources that are
disabled, started late, covered or never run.
"""

from __future__ import annotations

import json
import random
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import Connection, text

from app.core.importers.providers import document_providers, reset_document_providers
from app.core.matching.documents import DocInput, DocTxn
from app.core.resolution.confirmed import units_binds, units_sql
from app.core.settle.window import document_window
from app.core.units.closure import UnitEntry, units_of
from app.core.units.documents import DocumentFacts, DocumentSource, awaited, document_facts
from app.core.units.state import unit_state
from tests.core.units.doc_helpers import make_doc_source, make_document, make_payee
from tests.core.units.helpers import Bench, D
from tests.invariants.helpers import make_entry, make_source

DOC_KEY = json.dumps({"document": {"pass": "user"}})


@pytest.fixture(autouse=True)
def _registry() -> Iterator[None]:
    reset_document_providers()
    yield
    reset_document_providers()


def _sql(conn: Connection) -> dict[int, Any]:
    rows = conn.execute(text(f"WITH units AS ({units_sql()}) SELECT * FROM units"), units_binds())
    return {r.id: r for r in rows}


def test_no_provider_payee_nothing_is_open(db_conn: Connection, make_account: Any) -> None:
    bench = Bench(db_conn, make_account)
    make_doc_source(db_conn)
    make_document(db_conn)
    entry = bench.flow(bench.source(), payee_id=make_payee(db_conn, "Plain", None))
    row = _sql(db_conn)[entry]
    assert (row.doc_awaited, row.doc_suggested, row.unit_ok) == (False, False, True)


def test_a_provider_payee_with_an_active_source_awaits(db_conn: Connection, make_account: Any) -> None:
    bench = Bench(db_conn, make_account)
    make_doc_source(db_conn)
    entry = bench.flow(bench.source(), payee_id=make_payee(db_conn, "PayPal", "paypal"))
    row = _sql(db_conn)[entry]
    assert (row.doc_awaited, row.doc_suggested, row.unit_ok) == (True, False, False)


def test_without_a_source_nothing_waits(db_conn: Connection, make_account: Any) -> None:
    bench = Bench(db_conn, make_account)
    entry = bench.flow(bench.source(), payee_id=make_payee(db_conn, "PayPal", "paypal"))
    assert _sql(db_conn)[entry].unit_ok is True


def test_a_document_key_closes_the_gate(db_conn: Connection, make_account: Any) -> None:
    bench = Bench(db_conn, make_account)
    make_doc_source(db_conn)
    make_document(db_conn)
    entry = bench.flow(bench.source(), payee_id=make_payee(db_conn, "PayPal", "paypal"), derivation=DOC_KEY)
    row = _sql(db_conn)[entry]
    assert (row.doc_awaited, row.doc_suggested, row.unit_ok) == (False, False, True)


def test_only_the_original_entry_of_a_split_is_judged(db_conn: Connection, make_account: Any) -> None:
    bench = Bench(db_conn, make_account)
    make_doc_source(db_conn)
    payee = make_payee(db_conn, "PayPal", "paypal")
    src = bench.source(parts=2)
    first = bench.flow(src, payee_id=payee)
    second = bench.flow(src, payee_id=payee)
    sql = _sql(db_conn)
    assert sql[first].doc_awaited is True and sql[second].doc_awaited is False
    assert sql[first].unit_ok is False and sql[second].unit_ok is False  # the unit is one


def test_covered_through_the_end_of_the_window_ends_the_wait(db_conn: Connection, make_account: Any) -> None:
    bench = Bench(db_conn, make_account)
    window = document_window(db_conn)
    make_doc_source(db_conn, covered_through=D + timedelta(days=window))
    entry = bench.flow(bench.source(), payee_id=make_payee(db_conn, "PayPal", "paypal"))
    assert _sql(db_conn)[entry].doc_awaited is False


def test_one_day_short_of_the_window_still_waits(db_conn: Connection, make_account: Any) -> None:
    bench = Bench(db_conn, make_account)
    window = document_window(db_conn)
    make_doc_source(db_conn, covered_through=D + timedelta(days=window - 1))
    entry = bench.flow(bench.source(), payee_id=make_payee(db_conn, "PayPal", "paypal"))
    assert _sql(db_conn)[entry].doc_awaited is True


def test_every_instance_must_have_reached_it(db_conn: Connection, make_account: Any) -> None:
    bench = Bench(db_conn, make_account)
    done = D + timedelta(days=document_window(db_conn))
    make_doc_source(db_conn, "a", covered_through=done)
    make_doc_source(db_conn, "b", covered_through=done - timedelta(days=1))
    entry = bench.flow(bench.source(), payee_id=make_payee(db_conn, "PayPal", "paypal"))
    assert _sql(db_conn)[entry].doc_awaited is True


def test_a_unique_candidate_is_an_automatic_link_not_a_suggestion(
    db_conn: Connection, make_account: Any
) -> None:
    bench = Bench(db_conn, make_account)
    make_doc_source(db_conn, covered_through=D + timedelta(days=30))
    make_document(db_conn, total=-100)
    entry = bench.flow(bench.source(), payee_id=make_payee(db_conn, "PayPal", "paypal"))
    row = _sql(db_conn)[entry]
    assert (row.doc_suggested, row.unit_ok) == (False, True)  # step 2 of settling links it first


def test_two_candidates_are_suggested(db_conn: Connection, make_account: Any) -> None:
    bench = Bench(db_conn, make_account)
    make_doc_source(db_conn, covered_through=D + timedelta(days=30))
    make_document(db_conn, total=-100)
    make_document(db_conn, total=-100, on=D + timedelta(days=1))
    entry = bench.flow(bench.source(), payee_id=make_payee(db_conn, "PayPal", "paypal"))
    row = _sql(db_conn)[entry]
    assert (row.doc_suggested, row.doc_awaited, row.unit_ok) == (True, False, False)


def test_a_document_shared_by_two_charges_is_suggested_to_both(
    db_conn: Connection, make_account: Any
) -> None:
    bench = Bench(db_conn, make_account)
    make_document(db_conn, total=-100)
    payee = make_payee(db_conn, "PayPal", "paypal")
    a = bench.flow(bench.source(), payee_id=payee)
    b = bench.flow(bench.source(on=D + timedelta(days=1)), payee_id=payee)
    sql = _sql(db_conn)
    assert sql[a].doc_suggested is True and sql[b].doc_suggested is True


def test_a_carried_document_is_no_candidate(db_conn: Connection, make_account: Any) -> None:
    bench = Bench(db_conn, make_account)
    doc = make_document(db_conn, total=-100)
    payee = make_payee(db_conn, "PayPal", "paypal")
    carrier = bench.flow(bench.source(), payee_id=payee, derivation=DOC_KEY)
    db_conn.execute(text("UPDATE ledger_entry SET document_id = :d WHERE id = :e"), {"d": doc, "e": carrier})
    other = bench.flow(bench.source(on=D + timedelta(days=1)), payee_id=payee)
    sql = _sql(db_conn)
    assert sql[other].doc_suggested is False and sql[carrier].unit_ok is True


# ---- the matrix ----------------------------------------------------------------------------------


def _build(conn: Connection, make_account: Any, rng: random.Random) -> None:
    bench = Bench(conn, make_account)
    window = document_window(conn)
    horizon = D + timedelta(days=window + 6)
    for i in range(rng.randint(0, 4)):
        make_doc_source(
            conn,
            f"imp{i}",
            start=rng.choice([None, D - timedelta(days=30), D + timedelta(days=2), D + timedelta(days=9)]),
            disabled=rng.random() < 0.2,
            covered_through=rng.choice([None, None, D, D + timedelta(days=window - 1), horizon]),
            providers=frozenset(rng.choice([{"paypal"}, {"amazon"}, {"paypal", "amazon"}, set()])),
        )
    payees = [
        make_payee(conn, "PayPal", "paypal"),
        make_payee(conn, "Amazon", "amazon"),
        make_payee(conn, "Plain", None),
    ]
    amounts = [-100, -250, -100, 400]
    for i in range(rng.randint(0, 8)):
        make_document(
            conn,
            rng.choice(["paypal", "amazon", "paypal"]),
            total=rng.choice(amounts) if rng.random() < 0.85 else -777,
            on=D + timedelta(days=rng.randint(-10, 10)),
            currency=rng.choice(["EUR", "EUR", "EUR", "USD"]),
            external_id=f"m{i}",
        )
    carried: list[int] = []
    for _ in range(rng.randint(2, 10)):
        parts = rng.choice([1, 1, 1, 2])
        amount = rng.choice(amounts)
        src = make_source(
            conn,
            bench.a,
            amount=amount * parts,
            booked_on=D + timedelta(days=rng.randint(-3, 3)),
            columns=(
                {"instructed_currency": "USD", "instructed_amount": amount * parts}
                if rng.random() < 0.15
                else {}
            ),
        )
        decided = rng.random() < 0.2
        payee = rng.choice(payees)
        for n in range(parts):
            eid = make_entry(
                conn,
                src,
                amount=amount,
                category_id=bench.cat,
                payee_id=payee if n == 0 or rng.random() < 0.5 else payees[2],
                derivation=DOC_KEY if decided and n == 0 else "{}",
            )
            if decided and n == 0 and rng.random() < 0.5:
                carried.append(eid)
    free = conn.execute(text("SELECT id FROM external_document ORDER BY id")).scalars().all()
    for eid, doc in zip(carried, rng.sample(list(free), min(len(free), len(carried))), strict=False):
        conn.execute(text("UPDATE ledger_entry SET document_id = :d WHERE id = :e"), {"d": doc, "e": eid})


def _python_facts(conn: Connection) -> tuple[dict[int, DocumentFacts], list[UnitEntry]]:
    window = document_window(conn)
    providers = document_providers()
    entries = [
        UnitEntry(r.id, r.source_transaction_id, r.type, r.category_id, r.counterpart_entry_id, r.derivation)
        for r in conn.execute(
            text(
                "SELECT id, source_transaction_id, type, category_id, counterpart_entry_id, derivation"
                " FROM ledger_entry WHERE source_transaction_id IS NOT NULL"
            )
        )
    ]
    originals = conn.execute(
        text(
            "SELECT e.id, e.booked_on, st.amount, st.currency, st.instructed_amount, st.instructed_currency,"
            "       p.document_provider, jsonb_exists(e.derivation, 'document') AS decided"
            "  FROM ledger_entry AS e JOIN source_transaction AS st ON st.id = e.source_transaction_id"
            "  LEFT JOIN payee AS p ON p.id = e.payee_id"
            " WHERE e.id = (SELECT min(x.id) FROM ledger_entry AS x"
            "                WHERE x.source_transaction_id = e.source_transaction_id)"
        )
    ).all()
    txns = [
        DocTxn(
            r.id,
            0,
            r.booked_on,
            r.amount,
            r.currency,
            r.instructed_amount,
            r.instructed_currency,
            r.document_provider,
            document_decided=r.decided,
        )
        for r in originals
    ]
    others = [t for t in txns if t.payee_provider is not None and not t.document_decided]
    documents = [
        DocInput(r.id, r.provider, r.occurred_on, r.total, r.currency, carried=r.carried)
        for r in conn.execute(
            text(
                "SELECT d.id, d.provider, d.occurred_on, d.total, d.currency,"
                "       EXISTS (SELECT 1 FROM ledger_entry AS c WHERE c.document_id = d.id) AS carried"
                "  FROM external_document AS d"
            )
        )
    ]
    sources = [
        DocumentSource(
            r.importer,
            r.disabled,
            date.fromisoformat(r.settings["start_date"]) if "start_date" in r.settings else None,
            r.covered_through,
        )
        for r in conn.execute(
            text(
                "SELECT i.importer, i.disabled, i.settings, c.covered_through FROM importer_instance AS i"
                "  LEFT JOIN v_document_coverage AS c ON c.importer_instance_id = i.id"
            )
        )
    ]
    facts = {
        t.entry_id: document_facts(
            t, others=others, documents=documents, sources=sources, providers=providers, window=window
        )
        for t in txns
    }
    return facts, entries


@pytest.mark.parametrize("seed", range(12))
def test_sql_equals_the_python_twin_over_a_matrix(db_conn: Connection, make_account: Any, seed: int) -> None:
    rng = random.Random(seed)
    _build(db_conn, make_account, rng)
    sql = _sql(db_conn)
    facts, entries = _python_facts(db_conn)
    seen: set[tuple[bool, bool]] = set()
    for members in units_of(entries).values():
        state = unit_state(members, documents={e.id: facts[e.id] for e in members if e.id in facts})
        for e in members:
            row = sql[e.id]
            expected = (
                facts[e.id]
                if e.id == min(m.id for m in members if m.source_transaction_id == e.source_transaction_id)
                else DocumentFacts()
            )
            assert (row.doc_awaited, row.doc_suggested) == (expected.awaited, expected.suggested), (seed, e)
            seen.add((row.doc_awaited, row.doc_suggested))
            assert row.unit_ok == state.confirmed, (seed, e, state)
    assert len(seen) >= 1


def test_the_matrix_covers_every_outcome(db_conn: Connection, make_account: Any) -> None:
    outcomes: set[tuple[bool, bool]] = set()
    for seed in range(12):
        savepoint = db_conn.begin_nested()
        reset_document_providers()
        _build(db_conn, make_account, random.Random(seed))
        outcomes |= {(r.doc_awaited, r.doc_suggested) for r in _sql(db_conn).values()}
        savepoint.rollback()
    assert outcomes == {(False, False), (True, False), (False, True), (True, True)}


def test_awaited_is_pure_on_its_own() -> None:
    day = date(2026, 3, 10)
    providers = {"a": frozenset({"paypal"})}
    src = DocumentSource("a", covered_through=day)
    assert awaited("paypal", day, 7, [src], providers) is True
    assert (
        awaited("paypal", day, 7, [DocumentSource("a", covered_through=day + timedelta(days=7))], providers)
        is False
    )
    assert awaited("amazon", day, 7, [src], providers) is False
    assert awaited("paypal", day, 7, [DocumentSource("a", disabled=True)], providers) is False
    assert (
        awaited("paypal", day, 7, [DocumentSource("a", start_date=day + timedelta(days=1))], providers)
        is False
    )
    assert awaited("paypal", day, 7, [DocumentSource("a")], providers) is True
    assert awaited("paypal", day, 7, [], providers) is False
