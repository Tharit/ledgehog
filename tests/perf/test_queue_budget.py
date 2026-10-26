"""The review queue stays inside the budget on a backfill-sized ledger (spec §6, plan step 7).

Each sample times what a request does: the first page of the queue (all sections), a deep page reached by
its cursor, the Review item's count, and one unit read. Two ledgers: all 8,000 entries unconfirmed (the worst
case: a queue of 8,000 units) and the ~70% confirmed variant (about 2,400 unconfirmed). The budget is
`tests.perf.budget.QUEUE_BUDGET_SECONDS`. Numbers are printed (run with -s).
"""

from __future__ import annotations

import time
from collections.abc import Callable

import pytest

from app.core.units.read import actionable_count, get_unit, review_queue
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
        "count": actionable_count,
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


def test_queue_within_budget_with_transfers(backfill_transfers: Backfill) -> None:
    """Every section populated, from cases built here: the session ledger is shared and other perf tests pair
    and re-flag its legs, so nothing is assumed of its transfers. Inside one transaction, rolled back:
    300 legs with no counter-account and an instructed currency no account has, 150 legs towards the synced
    account (its partner not yet delivered), and the flags rewritten."""
    from sqlalchemy import text

    from app.core.settle.flags import recompute_review_flags

    samples: dict[str, list[float]] = {"first page": [], "page of 500": [], "needs_account page": []}
    summary = backfill_transfers.summary
    with backfill_transfers.engine.connect() as conn:
        synced = int(conn.execute(text("SELECT min(account_id) FROM account_source")).scalar_one())
        i = next(
            k
            for k, (acc, cur) in enumerate(zip(summary.account_ids, summary.account_currencies, strict=True))
            if cur == "EUR" and acc != synced
        )
        account, run = summary.account_ids[i], summary.run_ids[i]
        day = summary.last_booked
        for kind, count, counter, instructed in (("need", 300, None, "JPY"), ("wait", 150, synced, None)):
            conn.execute(
                text(
                    "WITH s AS (INSERT INTO source_transaction (origin, importer, import_run_id, account_id,"
                    " source_id,"
                    " source_format, amount, currency, booked_on, purpose, raw, instructed_amount,"
                    " instructed_currency)"
                    " SELECT 'import', 'perf', :run, :account, :kind || n, 'csv', -(100000 + n), 'EUR', :day,"
                    " 'perf', '{}',"
                    " CASE WHEN CAST(:instructed AS text) IS NULL THEN NULL ELSE -(100000 + n) * 150 END,"
                    " CAST(:instructed AS text)"
                    " FROM generate_series(1, :count) AS n RETURNING id, amount)"
                    " INSERT INTO ledger_entry (source_transaction_id, account_id, currency, booked_on,"
                    " amount,"
                    " type, counter_account_id, derivation)"
                    " SELECT s.id, :account, 'EUR', :day, s.amount, 'transfer', :counter,"
                    ' \'{"type": {"pass": "user"}}\' FROM s'
                ),
                {
                    "run": run,
                    "account": account,
                    "kind": kind,
                    "day": day,
                    "instructed": instructed,
                    "count": count,
                    "counter": counter,
                },
            )
        recompute_review_flags(conn)
        first = review_queue(conn, limit=100)
        kinds = {s.kind: s.total for s in first.sections}
        print(f"[perf] queue sections on the transfer ledger: {kinds}")
        assert kinds["needs_account"] >= 300 and kinds["waiting"] >= 150 and kinds["pending_review"] > 0
        for _ in range(REPEATS):
            for label, call in {
                "first page": lambda: review_queue(conn, limit=100),
                "page of 500": lambda: review_queue(conn, limit=500),
                "needs_account page": lambda: review_queue(conn, limit=100, section="needs_account"),
            }.items():
                started = time.perf_counter()
                call()
                samples[label].append(time.perf_counter() - started)
        conn.rollback()
    for label, taken in samples.items():
        stats = Stats.of(taken)
        print(f"[perf] queue with every section populated, {label}: {stats}")
        assert stats.max <= QUEUE_BUDGET_SECONDS, f"{label}: {stats} exceeds {QUEUE_BUDGET_SECONDS} s"


def test_queue_within_budget_with_most_entries_confirmed(backfill_settled: Backfill) -> None:
    _within_budget(backfill_settled, "70% confirmed")
