"""The reports stay inside the budget on a backfill-sized ledger (architecture §4.1, plan step 11).

Each sample times what a request computes: the Overview, *By category* over the whole year, *Over time*
over 12 months in both modes (savings; by category), and *Balances* over 12 months, as the core functions
do under the routes. The ledger is the ~70% confirmed backfill (8,000 entries over 6 accounts and a year,
with categories), with the base currency set and a USD rate every 3 days, so the conversion runs for every
entry (`base_value()` reads the setting per call and looks a rate up for the foreign account). The budget is
`tests.perf.budget.REPORTS_BUDGET_SECONDS`. Numbers are printed (run with -s).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from datetime import date

import pytest
from sqlalchemy import Connection, text

from app.core.reporting import (
    balances_report,
    by_category,
    categories_over_time,
    entry_filter,
    overview,
    savings_over_time,
)
from tests.fixtures.backfill import END
from tests.perf.budget import REPORTS_BUDGET_SECONDS
from tests.perf.conftest import Backfill
from tests.perf.test_settle_budget import Stats

pytestmark = pytest.mark.perf
REPEATS = 7
YEAR_START = date(END.year, 1, 1)


@pytest.fixture(scope="module")
def priced(backfill_settled: Backfill) -> Iterator[Backfill]:
    """The backfill with its base currency written and a USD rate every 3 days (so USD is valued)."""
    with backfill_settled.engine.begin() as conn:
        conn.execute(text("INSERT INTO ledger_setting (base_currency) VALUES ('EUR')"))
        conn.execute(
            text(
                "INSERT INTO fx_rate (currency, rate_date, per_base)"
                " SELECT 'USD', d::date, 1.1 FROM generate_series("
                " CAST(:a AS date) - 30, CAST(:b AS date), interval '3 days') AS d"
            ),
            {"a": YEAR_START, "b": END},
        )
    yield backfill_settled
    with backfill_settled.engine.begin() as conn:
        conn.execute(text("DELETE FROM fx_rate WHERE currency = 'USD'"))
        conn.execute(text("DELETE FROM ledger_setting"))


def _cases() -> dict[str, Callable[[Connection], object]]:
    twelve = entry_filter(date(END.year, 1, 1), END)
    return {
        "overview": lambda c: overview(c, END),
        "by category over the year (top 5)": lambda c: by_category(c, twelve, "expense", top=5),
        "over time, 12 months, savings": lambda c: savings_over_time(c, twelve, "month"),
        "over time, 12 months, by category": lambda c: categories_over_time(c, twelve, "month", "expense"),
        "balances, 12 months": lambda c: balances_report(c, YEAR_START, END, END),
    }


def test_every_report_is_inside_the_budget(priced: Backfill):
    worst = 0.0
    for name, call in _cases().items():
        samples: list[float] = []
        for _ in range(REPEATS):
            started = time.perf_counter()
            with priced.engine.connect() as conn:
                call(conn)
            samples.append(time.perf_counter() - started)
        stats = Stats.of(samples)
        print(f"[perf] reports, {name}: {stats}")
        worst = max(worst, stats.max)
        assert stats.max <= REPORTS_BUDGET_SECONDS, f"{name}: {stats} exceeds {REPORTS_BUDGET_SECONDS} s"
    print(f"[perf] reports worst case: {worst * 1000:.0f} ms (budget {REPORTS_BUDGET_SECONDS} s)")


def test_the_timed_ledger_has_something_to_report(priced: Backfill):
    """A timing over an empty answer times nothing."""
    with priced.engine.connect() as conn:
        got = by_category(conn, entry_filter(YEAR_START, END), "expense")
        worth = overview(conn, END).net_worth
    assert got.total.count > 3_000 and got.total.total is not None
    assert len(got.categories) > 10
    assert worth.total is not None and worth.unvalued == ()  # the USD account is valued by the rates
