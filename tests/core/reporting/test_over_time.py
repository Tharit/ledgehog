"""Savings and categories per period (core/reporting/savings.py): the periods sum to the range."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import Connection

from app.core.reporting import (
    EMPTY,
    Line,
    Unvalued,
    accounts_over_time,
    add,
    by_category,
    categories_over_time,
    entry_filter,
    savings_over_time,
)
from tests.core.reporting.helpers import household
from tests.fixtures import ledger_seed as seed

D = date


def test_each_period_holds_its_own_dates_and_the_periods_sum_to_the_range(ledger: Connection):
    household(ledger)
    flt = entry_filter(D(2026, 9, 1), D(2026, 10, 31))
    got = savings_over_time(ledger, flt, "month")
    assert [(p.start, p.end) for p in got.periods] == [
        (D(2026, 9, 1), D(2026, 9, 30)),
        (D(2026, 10, 1), D(2026, 10, 31)),
    ]
    sep, octo = got.savings
    assert sep.income == Line(300_000, 1) and sep.expense == Line(-49_500, 4)  # 30 Sep is September's
    assert sep.unclassified == Line(-1_500, 1) and sep.reconciliations == EMPTY
    assert sep.savings == Line(249_000, 6) and sep.rate_bp == 8300 and sep.incomplete
    assert octo.income == Line(301_000, 2)
    assert octo.expense == Line(-9_500, 4, (Unvalued("USD", -2_000, 1),))
    assert octo.unclassified == Line(2_200, 2) and octo.reconciliations == Line(-700, 1)
    for field in ("income", "expense", "unclassified", "reconciliations", "savings"):
        assert getattr(got.total, field) == add(getattr(s, field) for s in got.savings)
    assert got.total.savings.total == 542_000


def test_a_ranges_rate_is_its_savings_over_its_income_not_the_mean_of_its_rates(ledger: Connection):
    acct = seed.account(ledger)
    salary = seed.category(ledger, "Salary", kind="income")
    food = seed.category(ledger, "Food")
    seed.entry(ledger, acct, amount=100, on=D(2026, 1, 5), category_id=salary)  # a month that kept all
    seed.entry(ledger, acct, amount=1_000, on=D(2026, 2, 5), category_id=salary)
    seed.entry(ledger, acct, amount=-1_000, on=D(2026, 2, 6), category_id=food)  # a month that kept none
    got = savings_over_time(ledger, entry_filter(D(2026, 1, 1), D(2026, 2, 28)), "month")
    assert [s.rate_bp for s in got.savings] == [10_000, 0]
    assert got.total.rate_bp == 909  # 100 / 1100, not the mean of 10000 and 0
    # a range cut into quarters and into a year gives the same total
    assert savings_over_time(ledger, entry_filter(D(2026, 1, 1), D(2026, 2, 28)), "year").total == got.total


def test_the_rate_is_null_when_income_is_zero_or_less(ledger: Connection):
    acct = seed.account(ledger)
    food = seed.category(ledger, "Food")
    salary = seed.category(ledger, "Salary", kind="income")
    seed.entry(ledger, acct, amount=-500, on=D(2026, 3, 5), category_id=food)
    seed.entry(ledger, acct, amount=300, on=D(2026, 4, 5), category_id=salary)
    seed.entry(ledger, acct, amount=-400, on=D(2026, 4, 6), category_id=salary)  # a negative income month
    got = savings_over_time(ledger, entry_filter(D(2026, 3, 1), D(2026, 5, 31)), "month")
    march, april, may = got.savings
    assert march.income == EMPTY and march.rate_bp is None
    assert april.income == Line(-100, 2) and april.rate_bp is None
    assert may.savings == EMPTY and may.rate_bp is None and not may.incomplete


@pytest.mark.parametrize("cause", ["unclassified", "reconciliation", "unvalued", "none"])
def test_incomplete_names_each_cause(ledger: Connection, cause: str):
    acct = seed.account(ledger)
    usd = seed.account(ledger, "Card", currency="USD", kind="card")
    salary = seed.category(ledger, "Salary", kind="income")
    seed.entry(ledger, acct, amount=1_000, on=D(2026, 3, 5), category_id=salary)
    if cause == "unclassified":
        seed.entry(ledger, acct, amount=-1, on=D(2026, 3, 6))
    elif cause == "reconciliation":
        seed.derived(ledger, acct, type="reconciliation", on=D(2026, 3, 6), amount=-1)
    elif cause == "unvalued":
        seed.entry(ledger, usd, amount=-1, on=D(2026, 3, 6), category_id=seed.category(ledger, "Food"))
    (march,) = savings_over_time(ledger, entry_filter(D(2026, 3, 1), D(2026, 3, 31)), "month").savings
    assert march.incomplete is (cause != "none")


def test_quarters_and_a_period_cut_by_the_range(ledger: Connection):
    household(ledger)
    flt = entry_filter(D(2026, 8, 15), D(2026, 10, 20))
    got = savings_over_time(ledger, flt, "quarter")
    assert [(p.start, p.end) for p in got.periods] == [
        (D(2026, 8, 15), D(2026, 9, 30)),
        (D(2026, 10, 1), D(2026, 10, 20)),
    ]
    assert got.savings[0].income == Line(300_000, 1)


def test_categories_per_period_with_slices_and_other(ledger: Connection):
    h = household(ledger)
    flt = entry_filter(D(2026, 9, 1), D(2026, 10, 31))
    got = categories_over_time(ledger, flt, "month", "expense")
    series = {c.category_id: c for c in got.categories}
    assert series[h.groceries].own == (Line(-7_500, 2), Line(-10_200, 2))
    assert series[h.food].own == (Line(-2_000, 1), EMPTY)
    assert series[h.food].total == (Line(-9_500, 3), Line(-10_200, 2))
    assert series[h.travel].total[1] == Line(700, 2, (Unvalued("USD", -2_000, 1),))
    # the range's magnitude orders the siblings; a node's sum is its periods' totals
    assert [c.category_id for c in got.categories if c.parent_id is None] == [h.travel, h.food]
    assert series[h.food].sum == add(series[h.food].total)
    for c in got.categories:  # a node's own total is its own entries over the range
        assert c.own_sum == add(c.own)
    assert series[h.food].own_sum == Line(-2_000, 1)
    assert series[h.travel].own_sum == add(series[h.travel].own)  # includes October's unvalued USD
    # the same figures the range's own report gives
    whole = by_category(ledger, flt, "expense")
    assert got.sum == whole.total
    sums = {c.category_id: c.sum for c in got.categories}
    assert sums == {r.category_id: r.total for r in whole.categories}
    assert add(got.totals) == whole.total
    assert got.slices == (h.travel, h.food)
    # October's travel nets to the other sign: it leaves that period's bar and the "Other" of that period
    assert got.other == (EMPTY, EMPTY)


def test_other_collects_the_remaining_top_level_categories_per_period(ledger: Connection):
    acct = seed.account(ledger)
    cats = [seed.category(ledger, f"C{i}") for i in range(8)]
    for i, cat in enumerate(cats):
        seed.entry(ledger, acct, amount=-(1000 - i * 100), on=D(2026, 3, 5), category_id=cat)
    seed.entry(ledger, acct, amount=-50, on=D(2026, 4, 5), category_id=cats[7])
    got = categories_over_time(ledger, entry_filter(D(2026, 3, 1), D(2026, 4, 30)), "month", "expense")
    assert got.slices == tuple(cats[:6])
    assert got.other == (Line(-700, 2), Line(-50, 1))  # March: C6 and C7; April: C7 alone


# ---- By account

SEP_OCT = (D(2026, 9, 1), D(2026, 10, 31))


def test_accounts_of_a_kind_sum_per_period_to_the_kinds_total(ledger: Connection):
    h = household(ledger)
    flt = entry_filter(*SEP_OCT)
    for kind in ("expense", "income"):
        got = accounts_over_time(ledger, flt, "month", kind)
        category_mode = categories_over_time(ledger, flt, "month", kind)
        assert got.totals == category_mode.totals and got.sum == category_mode.sum
        for i in range(2):
            assert add(a.total[i] for a in got.accounts) == got.totals[i]
        assert all(a.sum == add(a.total) for a in got.accounts)
    expense = accounts_over_time(ledger, flt, "month", "expense")
    series = {a.account_id: a for a in expense.accounts}
    assert series[h.giro].total == (Line(-49_500, 4), Line(-8_300, 2))
    assert series[h.cash].total == (EMPTY, Line(-1_200, 1))
    assert series[h.usd].total == (EMPTY, Line(None, 1, (Unvalued("USD", -2_000, 1),)))
    assert [a.account_id for a in expense.accounts] == [h.giro, h.cash, h.usd]  # by magnitude, unvalued last
    income = accounts_over_time(ledger, flt, "month", "income")
    assert [(a.account_id, a.total) for a in income.accounts] == [
        (h.giro, (Line(300_000, 1), Line(301_000, 2)))
    ]


def test_every_transfer_leg_is_in_its_own_accounts_figure_of_its_direction(ledger: Connection):
    h = household(ledger)  # a paired Giro -> Cash transfer and two unpaired outgoing legs, all in October
    flt = entry_filter(*SEP_OCT)
    out = accounts_over_time(ledger, flt, "month", "transfer_out")
    assert [(a.account_id, a.total) for a in out.accounts] == [(h.giro, (EMPTY, Line(-12_000, 3)))]
    assert out.totals == (EMPTY, Line(-12_000, 3)) and out.sum == Line(-12_000, 3)
    into = accounts_over_time(ledger, flt, "month", "transfer_in")
    assert [(a.account_id, a.total) for a in into.accounts] == [(h.cash, (EMPTY, Line(5_000, 1)))]
    # an unpaired incoming leg is counted too
    seed.entry(ledger, h.giro, amount=700, on=D(2026, 9, 12), type="transfer", flags=("waiting",))
    into = accounts_over_time(ledger, flt, "month", "transfer_in")
    series = {a.account_id: a for a in into.accounts}
    assert series[h.giro].total == (Line(700, 1), EMPTY)
    assert add(a.total[0] for a in into.accounts) == into.totals[0] == Line(700, 1)


def test_the_account_and_tag_filters_apply_to_the_accounts_figures(ledger: Connection):
    h = household(ledger)
    only_cash = entry_filter(*SEP_OCT, account_ids=[h.cash])
    got = accounts_over_time(ledger, only_cash, "month", "expense")
    assert [a.account_id for a in got.accounts] == [h.cash]
    assert accounts_over_time(ledger, only_cash, "month", "transfer_out").accounts == ()
    tagged = accounts_over_time(ledger, entry_filter(*SEP_OCT, tag_ids=[h.trip]), "month", "expense")
    assert {a.account_id: a.sum for a in tagged.accounts} == {
        h.giro: Line(-40_000, 1),
        h.usd: Line(None, 1, (Unvalued("USD", -2_000, 1),)),
    }


def test_account_slices_and_other(ledger: Connection):
    accounts = [seed.account(ledger, f"A{i}") for i in range(8)]
    for i, acct in enumerate(accounts):
        seed.entry(ledger, acct, amount=-(1000 - i * 100), on=D(2026, 3, 5), type="transfer")
    seed.entry(ledger, accounts[7], amount=-50, on=D(2026, 4, 5), type="transfer")
    got = accounts_over_time(ledger, entry_filter(D(2026, 3, 1), D(2026, 4, 30)), "month", "transfer_out")
    assert got.slices == tuple(accounts[:6])
    assert got.other == (Line(-700, 2), Line(-50, 1))  # March: A6 and A7; April: A7 alone


def test_an_account_of_the_other_sign_is_no_slice_and_leaves_the_bar_of_its_period(ledger: Connection):
    big, refunded, swing = (seed.account(ledger, n) for n in ("Big", "Refunded", "Swing"))
    shop = seed.category(ledger, "Shop")
    seed.entry(ledger, big, amount=-9_000, on=D(2026, 3, 5), category_id=shop)
    seed.entry(ledger, refunded, amount=-100, on=D(2026, 3, 6), category_id=shop)
    seed.entry(ledger, refunded, amount=500, on=D(2026, 4, 6), category_id=shop)  # nets to + in April
    seed.entry(ledger, swing, amount=-300, on=D(2026, 3, 7), category_id=shop)
    seed.entry(ledger, swing, amount=-200, on=D(2026, 4, 7), category_id=shop)
    flt = entry_filter(D(2026, 3, 1), D(2026, 4, 30))
    got = accounts_over_time(ledger, flt, "month", "expense")
    # "refunded" nets -100 + 500 = +400 over the range: no slice, and "other" leaves it out of both periods
    assert got.slices == (big, swing)
    assert got.other == (EMPTY, EMPTY)
    assert {a.account_id: a.sum for a in got.accounts}[refunded] == Line(400, 2)
