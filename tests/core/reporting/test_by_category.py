"""Spend or income by category (core/reporting/spend.py) on a real database."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import Connection

from app.core.ledger import InvalidFilter
from app.core.reporting import EMPTY, Line, Unvalued, by_category, entry_filter
from tests.core.reporting.helpers import household, rate
from tests.fixtures import ledger_seed as seed

D = date


def test_each_entry_is_valued_at_its_own_rate_and_rounded_half_even(ledger: Connection):
    usd = seed.account(ledger, "Card", currency="USD", kind="card")
    food = seed.category(ledger, "Food")
    rate(ledger, "USD", D(2026, 9, 1), "2.0")
    seed.entry(ledger, usd, amount=-2001, on=D(2026, 9, 3), category_id=food)  # -1000.5 -> -1000 (even)
    seed.entry(ledger, usd, amount=-2003, on=D(2026, 9, 4), category_id=food)  # -1001.5 -> -1002 (even)
    got = by_category(ledger, entry_filter(D(2026, 9, 1), D(2026, 9, 30)), "expense")
    assert got.total == Line(-2002, 2)  # the sum of the rounded entries, not the rounding of the sum


def test_an_entry_with_no_rate_in_the_window_is_unvalued_never_zero(ledger: Connection):
    usd = seed.account(ledger, "Card", currency="USD", kind="card")
    giro = seed.account(ledger)
    food = seed.category(ledger, "Food")
    rate(ledger, "USD", D(2026, 9, 1), "2.0")
    seed.entry(ledger, usd, amount=-2000, on=D(2026, 9, 3), category_id=food)  # valued: -1000
    seed.entry(ledger, usd, amount=-500, on=D(2026, 9, 20), category_id=food)  # 19 days: too old
    seed.entry(ledger, giro, amount=-300, on=D(2026, 9, 20), category_id=food)  # base currency
    got = by_category(ledger, entry_filter(D(2026, 9, 1), D(2026, 9, 30)), "expense")
    assert got.total == Line(-1300, 3, (Unvalued("USD", -500, 1),))
    only_old = by_category(ledger, entry_filter(D(2026, 9, 15), D(2026, 9, 30)), "expense")
    assert only_old.total == Line(-300, 2, (Unvalued("USD", -500, 1),))
    nothing = by_category(ledger, entry_filter(D(2026, 9, 19), D(2026, 9, 21)), "expense")
    assert nothing.total.count == 2 and nothing.total.total == -300
    (row_food,) = nothing.categories
    assert row_food.total.unvalued == (Unvalued("USD", -500, 1),)


def test_a_category_of_only_unvalued_entries_has_no_total(ledger: Connection):
    usd = seed.account(ledger, "Card", currency="USD", kind="card")
    food = seed.category(ledger, "Food")
    seed.entry(ledger, usd, amount=-500, on=D(2026, 9, 20), category_id=food)
    got = by_category(ledger, entry_filter(D(2026, 9, 1), D(2026, 9, 30)), "expense", top=3)
    assert got.total == Line(None, 1, (Unvalued("USD", -500, 1),))
    assert got.categories[0].share_bp is None
    # it is neither a slice nor hidden: it is in "Other", so its unvalued remainder stays visible
    assert got.slices == () and got.other == got.total


def test_refunds_net_and_a_parent_has_its_own_entries(ledger: Connection):
    h = household(ledger)
    got = by_category(ledger, entry_filter(D(2026, 9, 1), D(2026, 9, 30)), "expense")
    rows = {r.category_id: r for r in got.categories}
    assert rows[h.groceries].own == Line(-7_500, 2)  # -8000 purchase, +500 refund
    assert rows[h.food].own == Line(-2_000, 1)  # booked to the parent itself
    assert rows[h.food].total == Line(-9_500, 3)  # with its child
    assert rows[h.travel].total == Line(-40_000, 1)
    assert got.total == Line(-49_500, 4)
    # depth-first, siblings by magnitude: travel before food, food's child right after it
    assert [r.category_id for r in got.categories] == [h.travel, h.food, h.groceries]
    assert rows[h.travel].share_bp == 8081  # 40000 / 49500
    assert rows[h.food].share_bp == 1919


def test_a_root_whose_net_has_the_other_sign_is_no_slice_but_a_row(ledger: Connection):
    h = household(ledger)
    got = by_category(ledger, entry_filter(D(2026, 10, 1), D(2026, 10, 31)), "expense", top=5)
    rows = {r.category_id: r for r in got.categories}
    assert rows[h.travel].total == Line(700, 2, (Unvalued("USD", -2_000, 1),))
    assert rows[h.travel].share_bp is None  # refunds beyond purchases: shown as it is, no share
    assert rows[h.food].total == Line(-10_200, 2) and rows[h.food].own == EMPTY
    assert rows[h.food].share_bp == 10737  # a share over 100 % is the arithmetic of the net total
    assert got.total == Line(-9_500, 4, (Unvalued("USD", -2_000, 1),))
    assert got.slices is not None and [s.category_id for s in got.slices] == [h.food]
    assert got.other is None  # nothing remains (the other-signed root belongs to neither)


def test_top_splits_the_roots_into_slices_and_other(ledger: Connection):
    acct = seed.account(ledger)
    roots = [seed.category(ledger, f"C{i}") for i in range(4)]
    for amount, cat in zip((-400, -300, -200, -100), roots, strict=True):
        seed.entry(ledger, acct, amount=amount, on=D(2026, 9, 3), category_id=cat)
    got = by_category(ledger, entry_filter(D(2026, 9, 1), D(2026, 9, 30)), "expense", top=2)
    assert got.slices is not None
    assert [(s.category_id, s.total.total) for s in got.slices] == [(roots[0], -400), (roots[1], -300)]
    assert got.other == Line(-300, 2)
    assert by_category(ledger, entry_filter(D(2026, 9, 1), D(2026, 9, 30)), "expense").slices is None


def test_income_is_the_other_kind_and_the_lines_beside_it(ledger: Connection):
    h = household(ledger)
    got = by_category(ledger, entry_filter(D(2026, 10, 1), D(2026, 10, 31)), "income")
    assert got.total == Line(301_000, 2)
    assert [r.share_bp for r in got.categories] == [9967, 33]
    assert got.unclassified_out == Line(-300, 1)  # an entry not yet interpreted is unclassified too
    assert got.unclassified_in == Line(2_500, 1)
    assert got.reconciliations == Line(-700, 1)
    assert got.unconfirmed_count == 1
    assert h.salary in {r.category_id for r in got.categories}


def test_the_ledger_filters_narrow_every_line_alike(ledger: Connection):
    h = household(ledger)
    september = (D(2026, 9, 1), D(2026, 9, 30))
    trip = by_category(ledger, entry_filter(*september, tag_ids=[h.trip]), "expense")
    assert [r.category_id for r in trip.categories] == [h.travel]
    assert trip.unclassified_out == EMPTY  # the untagged unclassified entry is out
    cash = by_category(ledger, entry_filter(D(2026, 10, 1), D(2026, 10, 31), account_ids=[h.cash]), "expense")
    assert cash.total == Line(-1_200, 1)
    both = by_category(
        ledger, entry_filter(D(2026, 10, 1), D(2026, 10, 31), account_ids=[h.cash, h.giro]), "expense"
    )
    assert both.total.count == 3  # several values of one dimension are alternatives


def test_a_reversed_range_is_an_invalid_filter_naming_to(ledger: Connection):
    with pytest.raises(InvalidFilter) as caught:
        entry_filter(D(2026, 10, 2), D(2026, 10, 1))
    assert caught.value.parameter == "to"
