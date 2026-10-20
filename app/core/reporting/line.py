"""The figure every report is made of (architecture §4.1, spec §8): a `Line`.

A `Line` is the base-currency total of some entries, each valued at its own `booked_on` rate and
rounded per entry (`base_value()`, spec §3.8), the number of entries it covers, and what could not be
valued, per currency. Unvalued is never zero: the total is `None` when entries exist and none could
be valued.

`Savings` is the one computation of savings and its rate, used by the Overview and by the over-time
report alike.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class Unvalued:
    """The entries of one currency that had no usable rate: their native sum and how many."""

    currency: str
    amount: int  # minor units of `currency`
    count: int


@dataclass(frozen=True)
class Line:
    total: int | None  # minor units of the base currency; None = entries exist, none could be valued
    count: int  # every entry covered, valued or not
    unvalued: tuple[Unvalued, ...] = ()  # by currency; empty when every entry was valued

    @property
    def valued(self) -> int:
        return self.count - sum(u.count for u in self.unvalued)


EMPTY = Line(total=0, count=0)


def line_of_group(
    currency: str, count: int, unvalued_count: int, base_sum: int, unvalued_amount: int
) -> Line:
    """The Line of one currency's entries, from the aggregate the statement groups."""
    unvalued = (Unvalued(currency, unvalued_amount, unvalued_count),) if unvalued_count else ()
    return Line(total=None if unvalued_count == count else base_sum, count=count, unvalued=unvalued)


def add(lines: Iterable[Line]) -> Line:
    """The sum of Lines: totals, counts and the unvalued remainders (merged per currency).

    The total stays `None` only while every entry counted is unvalued.
    """
    total = 0
    count = 0
    unvalued: dict[str, tuple[int, int]] = {}
    for line in lines:
        total += line.total or 0
        count += line.count
        for u in line.unvalued:
            amount, n = unvalued.get(u.currency, (0, 0))
            unvalued[u.currency] = (amount + u.amount, n + u.count)
    merged = tuple(Unvalued(c, a, n) for c, (a, n) in sorted(unvalued.items()))
    all_unvalued = count > 0 and sum(u.count for u in merged) == count
    return Line(total=None if all_unvalued else total, count=count, unvalued=merged)


@dataclass(frozen=True)
class Savings:
    income: Line
    expense: Line
    unclassified: Line  # both signs, net (spec §8: savings includes it)
    reconciliations: Line
    savings: Line  # the four summed
    rate_bp: int | None  # savings over income in basis points, half-even; None when income is not positive
    incomplete: bool  # unclassified entries, reconciliations or unvalued amounts in the four


def rate_bp(savings: Line, income: Line) -> int | None:
    """Savings over income, in basis points rounded half-even; None unless income is positive.

    Over a range it is the range's savings over its income, never the mean of its periods' rates.
    """
    if income.total is None or income.total <= 0 or savings.total is None:
        return None
    return round(Fraction(savings.total * 10_000, income.total))


def savings_of(income: Line, expense: Line, unclassified: Line, reconciliations: Line) -> Savings:
    parts = (income, expense, unclassified, reconciliations)
    total = add(parts)
    return Savings(
        income=income,
        expense=expense,
        unclassified=unclassified,
        reconciliations=reconciliations,
        savings=total,
        rate_bp=rate_bp(total, income),
        incomplete=unclassified.count > 0 or reconciliations.count > 0 or any(p.unvalued for p in parts),
    )
