"""The write transaction of a large first import stays inside the budget (spec/plan.md step 2).

`ingest_delivery` holds the settle lock (shared) and the account lock for its whole write
transaction, so that transaction must not cost a round trip per row. The test delivers ONE
~5,000-row delivery into a fresh account and times exactly that transaction: `settle` is
patched to a no-op for the timed call (settling is its own transaction, after the commit,
and is budgeted in test_settle_budget.py). Time is `time.perf_counter` (tests are outside
the AST clock rule, which scans app/).

The delivery mixes rows with and without `source_id`; ~5% of it repeats an earlier delivery
so the identity-skip path (same identity) and the amount-pairing path (same day and amount,
different text, no identity) run as well. The budget is `tests.perf.budget.INGEST_BUDGET_SECONDS`.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from datetime import date, timedelta

import pytest
from sqlalchemy import Engine, text

from app.core.ingest import run
from app.core.ingest.run import ingest_delivery, start_run
from app.core.plugins.importer import IncomingRow
from app.core.settle.settle import SettleResult, settle
from tests.perf.budget import INGEST_BUDGET_SECONDS

pytestmark = pytest.mark.perf
REPEATS = 3
FRESH = 4_750
EARLIER = 250  # delivered first; half repeated verbatim (identity), half paired by amount
FIRST_DAY = date(2025, 1, 1)


def _row(n: int, *, with_id: bool, purpose: str | None = None) -> IncomingRow:
    return IncomingRow(
        amount_minor=-(1_000 + n),  # distinct per n: only the intended rows can pair
        currency="EUR",
        booked_on=FIRST_DAY + timedelta(days=n % 365),
        source_format="csv:perf",
        raw={"n": n},
        source_id=f"perf-{n}" if with_id else None,
        counterparty_name="Perf Shop",
        purpose=purpose if purpose is not None else f"perf booking {n}",
    )


def _earlier() -> list[IncomingRow]:
    return [_row(n, with_id=n % 2 == 0) for n in range(EARLIER)]


def _big_delivery() -> list[IncomingRow]:
    half = EARLIER // 2
    rows = [_row(1_000 + n, with_id=n % 2 == 0) for n in range(FRESH)]
    rows += [_row(n, with_id=n % 2 == 0) for n in range(half)]  # identity skips
    rows += [_row(n, with_id=False, purpose=f"other text {n}") for n in range(half, EARLIER)]  # pairing
    return rows


def _noop_settle(engine: Engine) -> SettleResult:
    return SettleResult(touched_entry_ids=(), error=None)


def test_five_thousand_row_write_transaction_within_budget(
    isolated_engine: Engine, make_account: Callable[..., int], monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(run, "settle", _noop_settle)
    samples: list[float] = []
    for _ in range(REPEATS):
        with isolated_engine.begin() as conn:
            account = make_account(conn)
        first = start_run(isolated_engine, account, "transactions", importer="csv")
        ingest_delivery(isolated_engine, first, _earlier(), covered_through=date(2026, 1, 1))
        rows = _big_delivery()
        run_id = start_run(isolated_engine, account, "transactions", importer="csv")
        started = time.perf_counter()
        result = ingest_delivery(isolated_engine, run_id, rows, covered_through=date(2026, 1, 1))
        samples.append(time.perf_counter() - started)
        assert result.inserted == FRESH
        assert result.skipped_by_identity == EARLIER // 2
        assert len(result.duplicates) == EARLIER // 2
    median = statistics.median(samples)
    print(f"[perf] 5,000-row write transaction: median {median * 1000:.0f} ms of {samples}")
    # settling is a separate transaction: once, for the record
    started = time.perf_counter()
    settled = settle(isolated_engine)
    print(f"[perf] settle after the three imports: {(time.perf_counter() - started) * 1000:.0f} ms")
    assert settled.error is None
    assert max(samples) <= INGEST_BUDGET_SECONDS, f"{samples} exceeds the budget of {INGEST_BUDGET_SECONDS} s"
    with isolated_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM ledger_entry")).scalar_one() == REPEATS * (
            EARLIER + FRESH
        )
