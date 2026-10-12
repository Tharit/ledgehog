"""Settling after a single commit stays inside the budget (architecture §5.2, spec/plan.md step 2).

How the timing is taken: every write operation settles after its own commit. The tests
wrap the `settle` that `ingest_delivery` / `mark_duplicate` call (patched at their import
site) with a timer around the REAL `settle`, so the measured call is exactly the one a user
waits for after a commit, with real work in it (new entries to flag), not an idle second pass.
The timer is `time.perf_counter` (tests are outside the AST clock rule, which scans app/).

The budget is `tests.perf.budget.BUDGET_SECONDS`. Numbers are printed (run with -s).
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

import pytest
from sqlalchemy import Engine, text

from app.core.ingest import duplicates, run
from app.core.ingest.duplicates import mark_duplicate
from app.core.ingest.run import ingest_delivery, start_run
from app.core.plugins.importer import IncomingRow
from app.core.settle.settle import SettleResult, settle
from tests.fixtures.backfill import END
from tests.perf.budget import BUDGET_SECONDS
from tests.perf.conftest import Backfill

pytestmark = pytest.mark.perf
REPEATS = 5


@dataclass(frozen=True)
class Stats:
    median: float
    p95: float
    max: float

    @staticmethod
    def of(samples: list[float]) -> Stats:
        ordered = sorted(samples)
        p95 = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]
        return Stats(statistics.median(ordered), p95, ordered[-1])

    def __str__(self) -> str:
        return (
            f"median {self.median * 1000:.0f} ms, p95 {self.p95 * 1000:.0f} ms, max {self.max * 1000:.0f} ms"
        )


@pytest.fixture(scope="session")
def baseline(backfill: Backfill) -> Iterator[tuple[SettleResult, float]]:
    """The first settle after the load: the pass over ALL unconfirmed units."""
    started = time.perf_counter()
    result = settle(backfill.engine)
    elapsed = time.perf_counter() - started
    print(
        f"\n[perf] fixture: {backfill.summary.source_count} source rows/entries, "
        f"{len(backfill.summary.account_ids)} accounts, built in {backfill.build_seconds:.1f} s"
    )
    print(f"[perf] baseline settle (all units): {elapsed * 1000:.0f} ms, budget {BUDGET_SECONDS} s")
    yield result, elapsed


def test_baseline_settle_touches_every_entry_then_nothing(
    backfill: Backfill, baseline: tuple[SettleResult, float]
):
    result, elapsed = baseline
    assert result.error is None
    assert elapsed <= BUDGET_SECONDS, f"baseline pass took {elapsed:.2f} s, budget {BUDGET_SECONDS} s"
    assert len(result.touched_entry_ids) == backfill.summary.entry_count
    again = settle(backfill.engine)
    assert again.error is None and again.touched_entry_ids == ()


def _timed(monkeypatch: pytest.MonkeyPatch, module: object) -> list[float]:
    samples: list[float] = []
    real = settle

    def timed(engine: Engine) -> SettleResult:
        started = time.perf_counter()
        try:
            return real(engine)
        finally:
            samples.append(time.perf_counter() - started)

    monkeypatch.setattr(module, "settle", timed)
    return samples


def _new_rows(rep: int) -> list[IncomingRow]:
    # unique amounts: none of them can pair with an existing row as a duplicate
    return [
        IncomingRow(
            amount_minor=-(777_000 + rep * 10 + i),
            currency="EUR",
            booked_on=END,
            source_format="csv:perf",
            raw={"rep": rep, "i": i},
            counterparty_name="Perf Shop",
            purpose=f"perf delivery {rep}-{i}",
        )
        for i in range(5)
    ]


def test_settle_after_ingest_commit_within_budget(
    backfill: Backfill, baseline: tuple[SettleResult, float], monkeypatch: pytest.MonkeyPatch
):
    samples = _timed(monkeypatch, run)
    account = backfill.summary.account_ids[0]
    for rep in range(REPEATS):
        run_id = start_run(backfill.engine, account, "transactions", importer="csv")
        result = ingest_delivery(backfill.engine, run_id, _new_rows(rep), covered_through=date(2026, 1, 1))
        assert result.inserted == 5
        assert result.settle.error is None
        assert len(result.settle.touched_entry_ids) == 5  # exactly the new entries
    assert len(samples) == REPEATS
    stats = Stats.of(samples)
    print(f"[perf] settle after ingest_delivery (5 rows): {stats}")
    assert stats.max <= BUDGET_SECONDS, f"{stats} exceeds the budget of {BUDGET_SECONDS} s"


def test_settle_after_mark_duplicate_within_budget(
    backfill: Backfill, baseline: tuple[SettleResult, float], monkeypatch: pytest.MonkeyPatch
):
    account = backfill.summary.account_ids[1]
    with backfill.engine.connect() as conn:
        ids = list(
            conn.execute(
                text(
                    "SELECT id FROM source_transaction WHERE account_id = :a AND duplicate_of IS NULL"
                    " ORDER BY id LIMIT :n"
                ),
                {"a": account, "n": 2 * REPEATS},
            ).scalars()
        )
    samples = _timed(monkeypatch, duplicates)
    for rep in range(REPEATS):
        result = mark_duplicate(backfill.engine, ids[2 * rep + 1], ids[2 * rep])
        assert result.settle.error is None
    assert len(samples) == REPEATS
    stats = Stats.of(samples)
    print(f"[perf] settle after mark_duplicate: {stats}")
    assert stats.max <= BUDGET_SECONDS, f"{stats} exceeds the budget of {BUDGET_SECONDS} s"


def test_settle_with_resolution_over_a_mostly_confirmed_ledger_within_budget(
    backfill_settled: Backfill,
):
    """~70% confirmed (5,600 voters), ~2,400 unconfirmed entries to resolve by rules and history."""
    engine = backfill_settled.engine
    started = time.perf_counter()
    first = settle(engine)
    elapsed = time.perf_counter() - started
    assert first.error is None
    with engine.connect() as conn:
        flow_by = dict(
            conn.execute(
                text(
                    "SELECT derivation -> 'category' ->> 'pass', count(*) FROM ledger_entry"
                    " WHERE derivation ? 'category' GROUP BY 1"
                )
            ).all()
        )
        unresolved = conn.execute(text("SELECT count(*) FROM ledger_entry WHERE type IS NULL")).scalar_one()
    print(f"[perf] resolving settle, 70% confirmed: {elapsed * 1000:.0f} ms, budget {BUDGET_SECONDS} s")
    print(f"[perf]   categories by pass {flow_by}, untyped after: {unresolved}")
    assert flow_by.get("history", 0) > 0 and flow_by.get("rule", 0) > 0  # real work was done
    assert elapsed <= BUDGET_SECONDS, f"resolving settle took {elapsed:.2f} s, budget {BUDGET_SECONDS} s"
    started = time.perf_counter()
    again = settle(engine)
    idle = time.perf_counter() - started
    print(f"[perf] second settle (nothing to do): {idle * 1000:.0f} ms")
    assert again.error is None and again.touched_entry_ids == ()
    assert idle <= BUDGET_SECONDS
