"""Document matching and the resolution after a link stay inside the settle budget (architecture §5.2,
spec §5.8, documents.md).

The fixture is the ~90% confirmed ledger (7,200 voters) plus 3,000 documents and 1,500 unconfirmed
provider-payee charges (`tests/fixtures/backfill.py`, `_add_documents`): about as many unconfirmed entries
(2,300) as the 70% ledger of the other budgets. Of the charges 600 have exactly one document (100 of several
lines), 300 are in ambiguous pairs, 300 have only a near miss, and 300 are of a provider whose instance's
coverage is behind them (waiting). One instance is covered through the end of the year, the other 100 days in.
Numbers are printed (run with -s).

The first settle does everything: resolves the card text to the provider payee (step 1), links the 600
(step 2), derives them again on the enriched input (step 3), flags the rest, and goes on for the rounds the
newly confirmed units cause. The second settle is idle: nothing is written, I37. Steps 2 and 3 are also timed
on their own on the settled ledger: step 2 still loads the charges and documents that stay open.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, text

from app.core.importers.providers import configure_document_providers, reset_document_providers
from app.core.integrity import check_integrity
from app.core.settle.documents import match_documents_step, resolve_after_link_step
from app.core.settle.settle import settle
from tests.fixtures.backfill import DocumentSummary
from tests.perf.budget import BUDGET_SECONDS
from tests.perf.conftest import Backfill

pytestmark = pytest.mark.perf


@pytest.fixture(scope="module", autouse=True)
def _registry(backfill_documents: Backfill) -> Iterator[None]:
    docs = backfill_documents.summary.documents
    assert docs is not None
    configure_document_providers(docs.providers)
    yield
    reset_document_providers()


def _summary(backfill: Backfill) -> DocumentSummary:
    assert backfill.summary.documents is not None
    return backfill.summary.documents


@pytest.fixture(scope="module")
def measured(backfill_documents: Backfill) -> dict[str, Any]:
    engine = backfill_documents.engine
    out: dict[str, Any] = {}
    started = time.perf_counter()
    out["first"] = settle(engine)
    out["first_seconds"] = time.perf_counter() - started
    started = time.perf_counter()
    out["second"] = settle(engine)
    out["second_seconds"] = time.perf_counter() - started
    return out


def _rolled_back(engine: Engine, work: Callable[[Connection], Any]) -> float:
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text("SELECT set_config('ledger.settling', 'on', true)"))
            started = time.perf_counter()
            work(conn)
            return time.perf_counter() - started
        finally:
            trans.rollback()


def test_fixture_has_the_document_mix(backfill_documents: Backfill) -> None:
    docs = _summary(backfill_documents)
    assert docs.document_count == 3000 and docs.charge_count == 1500
    with backfill_documents.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM external_document")).scalar_one() == 3000
        assert conn.execute(text("SELECT count(*) FROM external_document_line")).scalar_one() == 300


def test_settle_with_documents_within_budget(backfill_documents: Backfill, measured: dict[str, Any]) -> None:
    docs = _summary(backfill_documents)
    first, second = measured["first"], measured["second"]
    print(
        f"\n[perf] settle over the documents ledger ({docs.document_count} documents,"
        f" {docs.charge_count} charges): first {measured['first_seconds'] * 1000:.0f} ms,"
        f" second (idle) {measured['second_seconds'] * 1000:.0f} ms, budget {BUDGET_SECONDS} s"
    )
    assert first.error is None and second.error is None
    assert measured["first_seconds"] <= BUDGET_SECONDS, f"first settle {measured['first_seconds']:.2f} s"
    assert measured["second_seconds"] <= BUDGET_SECONDS
    assert second.touched_entry_ids == ()  # I37


def test_the_links_flags_and_waiting_are_what_the_fixture_says(
    backfill_documents: Backfill, measured: dict[str, Any]
) -> None:
    docs = _summary(backfill_documents)
    assert measured["first"].error is None
    with backfill_documents.engine.connect() as conn:
        by_key = dict(
            conn.execute(
                text(
                    "SELECT derivation -> 'document' ->> 'pass', count(*) FROM ledger_entry"
                    " WHERE document_id IS NOT NULL GROUP BY 1"
                )
            ).all()
        )
        flags = dict(
            conn.execute(
                text(
                    "SELECT f, count(*) FROM ledger_entry, unnest(review_flags) AS f"
                    " WHERE f IN ('waiting', 'document_suggested') GROUP BY f"
                )
            ).all()
        )
        report = check_integrity(conn)
    print(f"[perf]   links by key {by_key}, flags {flags}")
    assert by_key == {"matcher_decision": docs.unique - docs.multi_line, "matcher_proposal": docs.multi_line}
    assert flags["document_suggested"] == docs.ambiguous_charges
    assert flags["waiting"] == docs.waiting
    assert report.ok


def test_the_steps_on_a_settled_ledger_within_budget(
    backfill_documents: Backfill, measured: dict[str, Any]
) -> None:
    assert measured["first"].error is None
    engine = backfill_documents.engine
    step2 = max(_rolled_back(engine, match_documents_step) for _ in range(5))
    step3 = max(_rolled_back(engine, resolve_after_link_step) for _ in range(5))
    print(
        f"[perf] step 2 on the settled ledger: max {step2 * 1000:.0f} ms;"
        f" step 3 with nothing linked: {step3 * 1000:.1f} ms"
    )
    assert step2 <= BUDGET_SECONDS and step3 <= BUDGET_SECONDS
