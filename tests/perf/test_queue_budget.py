"""The review queue stays inside the budget on a backfill-sized ledger (spec §6, plan step 7).

Each sample times what a request does: the first page of the queue (all sections), a deep page reached by
its cursor, the cheap new-count, and one unit read. Two ledgers: all 8,000 entries unconfirmed (the worst
case: a queue of 8,000 units) and the ~70% confirmed variant (about 2,400 unconfirmed). The budget is
`tests.perf.budget.QUEUE_BUDGET_SECONDS`. Numbers are printed (run with -s).
"""

from __future__ import annotations

import time
from collections.abc import Callable

import pytest

from app.core.units.read import get_unit, new_unit_count, review_queue
from tests.perf.budget import QUEUE_BUDGET_SECONDS
from tests.perf.conftest import Backfill
from tests.perf.test_settle_budget import Stats

pytestmark = pytest.mark.perf
REPEATS = 7


def _time(backfill: Backfill, call: Callable[..., object]) -> Stats:
    samples: list[float] = []
    for _ in range(REPEATS):
        started = time.perf_counter()
        with backfill.engine.connect() as conn:
            call(conn)
        samples.append(time.perf_counter() - started)
    return Stats.of(samples)


def _within_budget(backfill: Backfill, label: str) -> None:
    with backfill.engine.connect() as conn:
        first = review_queue(conn, limit=100)
    pending = first.sections[0]
    assert pending.total > 500 and len(pending.units) == 100 and pending.next_cursor
    with backfill.engine.connect() as conn:
        deep = review_queue(conn, limit=500, section="pending_review", cursor=pending.next_cursor)
    cases: dict[str, Callable[..., object]] = {
        "first page (100 units, all sections)": lambda c: review_queue(c, limit=100),
        "a page of 500 units": lambda c: review_queue(c, limit=500),
        "a page by cursor": lambda c: review_queue(
            c, limit=100, section="pending_review", cursor=deep.sections[0].next_cursor
        ),
        "new-count": lambda c: new_unit_count(c, first.snapshot),
        "one unit": lambda c: get_unit(c, pending.units[0].anchor_entry_id),
    }
    worst = 0.0
    for name, call in cases.items():
        stats = _time(backfill, call)
        print(f"[perf] queue {label}, {name} (queue of {pending.total}): {stats}")
        worst = max(worst, stats.max)
        assert stats.max <= QUEUE_BUDGET_SECONDS, f"{label}, {name}: {stats} exceeds {QUEUE_BUDGET_SECONDS} s"
    print(f"[perf] queue {label}: worst case {worst * 1000:.0f} ms (budget {QUEUE_BUDGET_SECONDS} s)")


def test_queue_within_budget_all_unconfirmed(backfill: Backfill) -> None:
    _within_budget(backfill, "all unconfirmed")


def test_queue_within_budget_with_most_entries_confirmed(backfill_settled: Backfill) -> None:
    _within_budget(backfill_settled, "70% confirmed")
