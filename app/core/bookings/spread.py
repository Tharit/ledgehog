"""The entries of a document's booking (features/documents.md §2): the spread of its total over its lines.

Pure arithmetic in minor units, no database. `spread(total, amounts)` answers, for a document of total
`T` and lines of the given amounts in line order, which lines get an entry and how much it is.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Share:
    """One entry of a booking: the index of its line in the document's lines (None for the one entry
    that carries the whole total because no line has the total's sign) and its amount."""

    line: int | None
    amount: int


def _sign(n: int) -> int:
    return (n > 0) - (n < 0)


def _half_even(numerator: int, denominator: int) -> int:
    """round_half_even(numerator / denominator) for a non-negative numerator and a positive denominator."""
    q, r = divmod(numerator, denominator)
    twice = 2 * r
    if twice > denominator or (twice == denominator and q % 2 == 1):
        q += 1
    return q


def spread(total: int, amounts: Sequence[int]) -> list[Share]:
    """The entries of a booking of `total` (not 0) over lines of `amounts`, in line order.

    The lines of amount 0 are dropped. A line of the opposite sign to the total stays as listed. What
    the lines leave of the total is spread over the lines of its sign in proportion to their amounts,
    rounded half-even, the rounding remainder going to the largest line (the earlier on a tie); an
    entry of 0 or of the opposite sign then merges into the largest other one, and its line gets no
    entry. No line of the total's sign: one entry for the total. The amounts always sum to the total.
    """
    if total == 0:
        raise ValueError("a total of 0 has no booking")
    sign = _sign(total)
    same = [i for i, a in enumerate(amounts) if _sign(a) == sign]
    if not same:
        return [Share(None, total)]
    opposite = {i: a for i, a in enumerate(amounts) if a != 0 and _sign(a) == -sign}
    share_total = total - sum(opposite.values())  # T_S: T's sign, at least as large as T
    sum_same = sum(amounts[i] for i in same)
    entries: dict[int, int] = {
        i: sign * _half_even(abs(amounts[i]) * abs(share_total), abs(sum_same)) for i in same
    }

    def largest(candidates: Sequence[int]) -> int:
        # by the line's magnitude; the earlier line on a tie
        return max(candidates, key=lambda i: (abs(amounts[i]), -i))

    entries[largest(same)] += share_total - sum(entries.values())
    while True:
        bad = next((i for i in sorted(entries) if entries[i] == 0 or _sign(entries[i]) == -sign), None)
        if bad is None:
            break
        amount = entries.pop(bad)
        entries[largest(sorted(entries))] += amount
    merged = {**opposite, **entries}
    return [Share(i, merged[i]) for i in sorted(merged)]
