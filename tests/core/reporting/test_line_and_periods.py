"""`Line`, `Savings` and the calendar periods: the pure parts of core/reporting (no database)."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.reporting import (
    EMPTY,
    Line,
    TooManyPeriods,
    Unvalued,
    add,
    periods,
    points,
    rate_bp,
    savings_of,
)
from app.core.reporting.line import line_of_group
from app.core.reporting.periods import add_months, same_day_last_month

USD2 = Line(None, 2, (Unvalued("USD", 700, 2),))


def test_a_line_with_nothing_valued_has_no_total():
    assert line_of_group("USD", count=2, unvalued_count=2, base_sum=0, unvalued_amount=700) == USD2


def test_a_partly_valued_line_keeps_its_total_and_the_remainder():
    line = line_of_group("USD", count=3, unvalued_count=1, base_sum=500, unvalued_amount=-90)
    assert (line.total, line.count, line.valued) == (500, 3, 2)
    assert line.unvalued == (Unvalued("USD", -90, 1),)


def test_add_merges_unvalued_per_currency_and_keeps_none_only_while_nothing_is_valued():
    assert add([USD2, USD2]) == Line(None, 4, (Unvalued("USD", 1400, 4),))
    mixed = add([USD2, Line(300, 1), Line(None, 1, (Unvalued("GBP", 5, 1),))])
    assert mixed == Line(300, 4, (Unvalued("GBP", 5, 1), Unvalued("USD", 700, 2)))
    assert add([EMPTY, Line(5, 1)]) == Line(5, 1)
    assert add([]) == EMPTY
    assert add([EMPTY, USD2]).total is None  # entries exist and none is valued


@pytest.mark.parametrize(
    ("kept", "income", "expected"),
    [
        (1, 3, 3333),  # 33.33 %
        (1, 8, 1250),
        (-1, 8, -1250),  # a negative rate is a rate
        (1, 20_000, 0),  # 0.5 bp: half-even goes to 0
        (3, 20_000, 2),  # 1.5 bp: half-even goes to 2
        (5, 20_000, 2),  # 2.5 bp: half-even goes to 2
    ],
)
def test_the_rate_is_in_basis_points_half_even(kept: int, income: int, expected: int):
    assert rate_bp(Line(kept, 1), Line(income, 1)) == expected


@pytest.mark.parametrize("income", [Line(0, 0), Line(0, 1), Line(-500, 1), USD2])
def test_the_rate_is_none_unless_income_is_positive(income: Line):
    assert rate_bp(Line(100, 1), income) is None


def test_savings_adds_the_four_lines_and_names_every_cause_of_incompleteness():
    clean = savings_of(Line(10_000, 2), Line(-4_000, 3), EMPTY, EMPTY)
    assert clean.savings == Line(6_000, 5) and clean.rate_bp == 6000 and not clean.incomplete
    assert savings_of(Line(10_000, 2), Line(-4_000, 3), Line(-100, 1), EMPTY).incomplete
    assert savings_of(Line(10_000, 2), Line(-4_000, 3), EMPTY, Line(50, 1)).incomplete
    unvalued = savings_of(Line(10_000, 2), Line(-4_000, 3, (Unvalued("USD", -9, 1),)), EMPTY, EMPTY)
    assert unvalued.incomplete  # a third cause: an amount that could not be valued
    # savings includes the unclassified and reconciliation lines
    full = savings_of(Line(10_000, 1), Line(-4_000, 1), Line(-500, 1), Line(-250, 1))
    assert full.savings.total == 5_250 and full.rate_bp == 5250


# ---- periods


def test_months_are_clipped_to_the_range():
    cut = periods(date(2026, 1, 20), date(2026, 3, 10), "month")
    assert [(p.start, p.end, p.bucket) for p in cut] == [
        (date(2026, 1, 20), date(2026, 1, 31), date(2026, 1, 1)),
        (date(2026, 2, 1), date(2026, 2, 28), date(2026, 2, 1)),
        (date(2026, 3, 1), date(2026, 3, 10), date(2026, 3, 1)),
    ]


def test_quarters_and_years():
    q = periods(date(2025, 11, 15), date(2026, 5, 2), "quarter")
    assert [(p.start, p.end, p.bucket) for p in q] == [
        (date(2025, 11, 15), date(2025, 12, 31), date(2025, 10, 1)),
        (date(2026, 1, 1), date(2026, 3, 31), date(2026, 1, 1)),
        (date(2026, 4, 1), date(2026, 5, 2), date(2026, 4, 1)),
    ]
    y = periods(date(2024, 2, 29), date(2025, 12, 31), "year")
    assert [(p.start, p.end) for p in y] == [
        (date(2024, 2, 29), date(2024, 12, 31)),
        (date(2025, 1, 1), date(2025, 12, 31)),
    ]


def test_a_leap_february_has_29_days_and_a_single_day_is_one_period():
    (feb,) = periods(date(2028, 2, 1), date(2028, 2, 29), "month")
    assert feb.end == date(2028, 2, 29)
    (one,) = periods(date(2026, 6, 15), date(2026, 6, 15), "year")
    assert one.start == one.end == date(2026, 6, 15) and one.bucket == date(2026, 1, 1)


def test_more_than_120_periods_is_refused_naming_the_step():
    assert len(periods(date(2016, 1, 1), date(2025, 12, 31), "month")) == 120
    with pytest.raises(TooManyPeriods) as caught:
        periods(date(2015, 12, 31), date(2025, 12, 31), "month")
    assert caught.value.parameter == "step"


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 10, 20), date(2026, 9, 20)),
        (date(2026, 10, 31), date(2026, 9, 30)),  # September has 30 days
        (date(2026, 3, 30), date(2026, 2, 28)),
        (date(2028, 3, 30), date(2028, 2, 29)),
        (date(2026, 1, 31), date(2025, 12, 31)),
    ],
)
def test_the_same_day_last_month_is_clamped_to_its_last_day(today: date, expected: date):
    assert same_day_last_month(today) == expected


def test_add_months_crosses_years_both_ways():
    assert add_months(date(2026, 1, 31), -1) == date(2025, 12, 1)
    assert add_months(date(2026, 10, 5), -12) == date(2025, 10, 1)
    assert add_months(date(2026, 11, 5), 2) == date(2027, 1, 1)


def test_points_are_month_ends_the_future_replaced_by_today():
    today = date(2026, 10, 20)
    assert points(date(2026, 7, 1), date(2026, 9, 30), today) == [
        date(2026, 7, 31),
        date(2026, 8, 31),
        date(2026, 9, 30),
    ]
    # the range reaches today: the current month's point is today, not October's end
    assert points(date(2026, 7, 1), date(2026, 10, 20), today)[-1] == today
    assert points(date(2026, 7, 1), date(2026, 10, 31), today)[-2:] == [date(2026, 9, 30), today]
    # a range wholly in the future gives the one point, today
    assert points(date(2027, 1, 1), date(2027, 3, 31), today) == [today]
    # a range that starts mid-month starts at that month's end
    assert points(date(2026, 8, 15), date(2026, 9, 30), today) == [date(2026, 8, 31), date(2026, 9, 30)]
    assert points(date(2026, 8, 15), date(2026, 8, 20), today) == []
