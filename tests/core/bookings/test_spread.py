"""The spread of a document's total over its lines (features/documents.md §2): pure arithmetic."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.bookings.spread import Share, spread


def pairs(shares: list[Share]) -> list[tuple[int | None, int]]:
    return [(s.line, s.amount) for s in shares]


def test_spec_worked_example_spreads_the_unitemised_amount_in_proportion() -> None:
    # spec §4: -1299 and -3499 over a total of -4997 (the lines leave -199: shipping)
    assert pairs(spread(-4997, [-1299, -3499])) == [(0, -1353), (1, -3644)]


def test_lines_that_sum_to_the_total_stay_as_listed() -> None:
    assert pairs(spread(-4798, [-1299, -3499])) == [(0, -1299), (1, -3499)]


def test_a_coupon_line_stays_as_listed_and_the_rest_is_spread_without_it() -> None:
    # T_S = -2400 - 500 = -2900 over -1000 and -2000
    assert pairs(spread(-2400, [-1000, -2000, 500])) == [(0, -967), (1, -1933), (2, 500)]


def test_zero_lines_are_dropped() -> None:
    assert pairs(spread(-2000, [-1000, 0, -1000])) == [(0, -1000), (2, -1000)]


def test_the_remainder_goes_to_the_largest_line_the_earlier_on_a_tie() -> None:
    # 3 x -100 over -1000: thirds of 1000 round to 333 each; the remainder 1 goes to the first
    assert pairs(spread(-1000, [-100, -100, -100])) == [(0, -334), (1, -333), (2, -333)]
    # the largest line takes it
    assert pairs(spread(-1000, [-100, -200, -100])) == [(0, -250), (1, -500), (2, -250)]
    assert pairs(spread(-1001, [-100, -200, -100])) == [(0, -250), (1, -501), (2, -250)]


def test_half_even_rounding() -> None:
    # equal lines over 5 and 7: 2.5 rounds to 2 and 3.5 to 4; the remainder restores the sum
    assert [s.amount for s in spread(-5, [-1, -1])] == [-3, -2]  # -2 each, remainder -1 to the first
    assert [s.amount for s in spread(-7, [-1, -1])] == [-3, -4]  # -4 each, remainder +1 to the first


def test_an_entry_rounding_to_zero_merges_into_the_largest_other() -> None:
    assert pairs(spread(-1, [-500, -500])) == [(0, -1)]
    assert pairs(spread(-100, [-1, -1000])) == [(1, -100)]


def test_no_line_of_the_totals_sign_gives_one_entry_without_a_line() -> None:
    assert pairs(spread(-500, [])) == [(None, -500)]
    assert pairs(spread(-500, [200])) == [(None, -500)]
    assert pairs(spread(300, [-1000])) == [(None, 300)]
    assert pairs(spread(-500, [0, 0])) == [(None, -500)]


def test_a_refund_spreads_like_an_order() -> None:
    assert pairs(spread(4997, [1299, 3499])) == [(0, 1353), (1, 3644)]


def test_a_total_of_zero_has_no_booking() -> None:
    with pytest.raises(ValueError):
        spread(0, [-100])


@given(
    total=st.integers(-10_000, 10_000).filter(bool),
    amounts=st.lists(st.integers(-5_000, 5_000), max_size=8),
)
def test_entries_sum_to_the_total_and_none_is_zero_or_against_it(total: int, amounts: list[int]) -> None:
    shares = spread(total, amounts)
    assert sum(s.amount for s in shares) == total
    assert shares, "a booking has at least its original entry"
    lines = [s.line for s in shares if s.line is not None]
    assert lines == sorted(set(lines))
    assert all(s.amount != 0 for s in shares)
    same = [s for s in shares if s.line is not None and amounts[s.line] * total > 0]
    assert all(s.amount * total > 0 for s in same)
    for s in shares:  # opposite-sign lines are listed as they are
        if s.line is not None and amounts[s.line] * total < 0:
            assert s.amount == amounts[s.line]
