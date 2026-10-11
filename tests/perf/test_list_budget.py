"""The ledger list stays inside the budget on a backfill-sized ledger (architecture §4.1, plan step 5).

A request is a page of 100 plus the count over the same predicates, so each sample times both,
exactly what `list_entries` does. Filters are the dimensions the UI offers: none, a date range,
one account, a tag, text, an amount range, and all of them combined. The budget is
`tests.perf.budget.LIST_BUDGET_SECONDS`. Numbers are printed (run with -s).
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy import text

from app.core.ledger import LedgerFilter, list_entries
from tests.fixtures.backfill import END
from tests.perf.budget import LIST_BUDGET_SECONDS
from tests.perf.conftest import Backfill
from tests.perf.test_settle_budget import Stats

pytestmark = pytest.mark.perf
REPEATS = 7


@pytest.fixture(scope="module")
def tag_id(backfill: Backfill) -> Iterator[int]:
    """One tag on about one entry in eight (the backfill itself carries no tags)."""
    with backfill.engine.begin() as conn:
        tag = int(conn.execute(text("INSERT INTO tag (name) VALUES ('perf') RETURNING id")).scalar_one())
        conn.execute(
            text(
                "INSERT INTO ledger_entry_tag (ledger_entry_id, tag_id)"
                " SELECT id, :t FROM ledger_entry WHERE id % 8 = 0 AND balance_record_id IS NULL"
            ),
            {"t": tag},
        )
    yield tag
    with backfill.engine.begin() as conn:
        conn.execute(text("DELETE FROM tag WHERE id = :t"), {"t": tag})


def _time(backfill: Backfill, flt: LedgerFilter) -> tuple[Stats, int]:
    samples: list[float] = []
    total = 0
    for _ in range(REPEATS):
        started = time.perf_counter()
        with backfill.engine.connect() as conn:
            page = list_entries(conn, flt, limit=100, offset=0)
        samples.append(time.perf_counter() - started)
        total = page.total
    return Stats.of(samples), total


def _cases(backfill: Backfill, tag: int) -> dict[str, LedgerFilter]:
    first = backfill.summary.account_ids[0]
    return {
        "no filter": LedgerFilter(),
        "date range (one quarter)": LedgerFilter(
            date_from=date(END.year, 7, 1), date_to=date(END.year, 9, 30)
        ),
        "one account": LedgerFilter(account_ids=(first,)),
        "tag": LedgerFilter(tag_ids=(tag,)),
        "text": LedgerFilter(text="kartenzahlung rewe"),
        "amount range": LedgerFilter(amount_min=1000, amount_max=5000, currency="EUR"),
        "all combined": LedgerFilter(
            date_from=date(END.year, 1, 1),
            date_to=END,
            account_ids=(first,),
            tag_ids=(tag,),
            text="kartenzahlung",
            amount_min=500,
            amount_max=50_000,
            currency="EUR",
            direction="out",
        ),
    }


def test_list_within_budget_for_every_filter(backfill: Backfill, tag_id: int):
    worst = 0.0
    for name, flt in _cases(backfill, tag_id).items():
        stats, total = _time(backfill, flt)
        print(f"[perf] list page of 100 + count, {name}: {stats} (total {total})")
        assert total > 0, f"{name}: the case matches nothing, so it times nothing"
        worst = max(worst, stats.max)
        assert stats.max <= LIST_BUDGET_SECONDS, (
            f"{name}: {stats} exceeds the budget of {LIST_BUDGET_SECONDS} s"
        )
    print(f"[perf] list worst case over all filters: {worst * 1000:.0f} ms (budget {LIST_BUDGET_SECONDS} s)")


def test_a_deep_page_is_inside_the_budget_too(backfill: Backfill):
    started = time.perf_counter()
    with backfill.engine.connect() as conn:
        page = list_entries(conn, LedgerFilter(), limit=100, offset=7_000)
    elapsed = time.perf_counter() - started
    print(f"[perf] list page 71 of an unfiltered ledger: {elapsed * 1000:.0f} ms")
    assert len(page.entries) == 100
    assert elapsed <= LIST_BUDGET_SECONDS
