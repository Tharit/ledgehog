"""Reporting (architecture §4.1, §5.1; spec §8): aggregate queries, the only caller of `base_value()` (I27).

Every figure is a `Line`; savings is one computation (`savings_in`); every report reads its entries
through the ledger list's own predicate (`app.core.ledger.compose`), so a drill-down equals its number.
"""

from app.core.reporting.balances import (
    KIND_ORDER,
    MAX_POINTS,
    AccountBalance,
    AccountSeries,
    BalancesReport,
    KindSeries,
    NetWorth,
    UnvaluedAccounts,
    balances_on,
    balances_report,
    net_worth_at,
    net_worth_of,
    points,
)
from app.core.reporting.facts import KIND_SIGN, Facts, count_matching, entry_filter, fetch
from app.core.reporting.line import EMPTY, Line, Savings, Unvalued, add, rate_bp, savings_of
from app.core.reporting.overview import (
    MonthSpend,
    NetWorthFigure,
    NetWorthSince,
    Overview,
    OverviewAccount,
    SavingsSpan,
    ThisMonthSpend,
    accounts_by_data_age,
    overview,
)
from app.core.reporting.periods import (
    MAX_PERIODS,
    STEPS,
    Period,
    Step,
    TooManyPeriods,
    periods,
)
from app.core.reporting.savings import (
    CategoriesOverTime,
    CategorySeries,
    SavingsOverTime,
    categories_over_time,
    savings_in,
    savings_over_time,
)
from app.core.reporting.spend import ByCategory, CategoryRow, Slice, by_category

__all__ = [
    "EMPTY",
    "KIND_ORDER",
    "KIND_SIGN",
    "MAX_PERIODS",
    "MAX_POINTS",
    "STEPS",
    "AccountBalance",
    "AccountSeries",
    "BalancesReport",
    "ByCategory",
    "CategoriesOverTime",
    "CategoryRow",
    "CategorySeries",
    "Facts",
    "KindSeries",
    "Line",
    "MonthSpend",
    "NetWorth",
    "NetWorthFigure",
    "NetWorthSince",
    "Overview",
    "OverviewAccount",
    "Period",
    "Savings",
    "SavingsOverTime",
    "SavingsSpan",
    "Slice",
    "Step",
    "ThisMonthSpend",
    "TooManyPeriods",
    "Unvalued",
    "UnvaluedAccounts",
    "accounts_by_data_age",
    "add",
    "balances_on",
    "balances_report",
    "by_category",
    "categories_over_time",
    "count_matching",
    "entry_filter",
    "fetch",
    "net_worth_at",
    "net_worth_of",
    "overview",
    "periods",
    "points",
    "rate_bp",
    "savings_in",
    "savings_of",
    "savings_over_time",
]
