"""The line allocation of a document over transactions (spec/features/documents.md §3, §4), pure.

A line allocation assigns each line of a document to at most one of the given transactions (the
parties) so that the lines assigned to a party sum exactly to its amount, in the document's currency.
ALL lines take part in the sums, those of the opposite sign (a coupon, a discount) too: they fold into the
original entry's remainder only when a split is built, not here. Lines assigned to none are not yet charged.

Two ways to allocate:

* a WHOLE-DOCUMENT match: a single party whose amount equals the document's total takes every line, however
  they sum (possible for any document, the remainder goes to the original entry later);
* a PARTIAL match, a party taking some lines: only for a document whose lines sum exactly to its total and
  that has at most `MAX_PARTIAL_LINES` lines (a fixed limit that bounds the search, not a setting).

Committed line references (a party's entries referencing lines of this document) are a PREFERENCE: an
allocation KEEPS them when every referenced line is assigned to the referencing party. The proposal is built
line by line, in line order, each line going to the earliest party (by `booked_on`, then key) that still
leaves a complete allocation, and to none when no party can take it; it keeps the references where any
allocation does, else it is the first of all. That is a depth-first search in exactly that preference order,
so the first complete allocation it reaches is the proposal. Orders are small; the search prunes a branch the
moment a party's remaining need cannot be met by the lines still to come, and remembers failures.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import NamedTuple

MAX_PARTIAL_LINES = 20


class Line(NamedTuple):
    """A line of the document: its number (the key within the document, ascending = line order) and its
    signed amount in the document's currency."""

    number: int
    amount: int


class Party(NamedTuple):
    """A transaction as the allocation reads it: `key` identifies it (its original entry), `amount` is in the
    document's currency, `refs` are the numbers of the document's lines its entries reference."""

    key: int
    booked_on: date
    amount: int
    refs: frozenset[int] = frozenset()


class Allocation(NamedTuple):
    """`assigned` maps a line number to the key of the party that takes it (a line in no key is not yet
    charged); `keeps` says every committed reference is assigned to its own party."""

    assigned: Mapping[int, int]
    keeps: bool

    def of(self, key: int) -> list[int]:
        """The numbers of the lines the party `key` takes, ascending."""
        return sorted(n for n, k in self.assigned.items() if k == key)


def allocate(lines: Sequence[Line], total: int, parties: Sequence[Party]) -> Allocation | None:
    """The proposed line allocation of a document (its `lines`, summing to `total` or not) over `parties`,
    or None where there is none. No party: the empty allocation."""
    if not parties:
        return Allocation({}, True)
    order = sorted(parties, key=lambda p: (p.booked_on, p.key))
    if len(order) == 1 and order[0].amount == total:
        whole = {ln.number: order[0].key for ln in lines}
        return Allocation(whole, _keeps(whole, lines, order))
    if len(lines) > MAX_PARTIAL_LINES or sum(ln.amount for ln in lines) != total:
        return None
    for keep in (True, False):
        found = _search(lines, order, keep)
        if found is not None:
            return Allocation(found, _keeps(found, lines, order))
    return None


def _keeps(found: Mapping[int, int], lines: Sequence[Line], order: Sequence[Party]) -> bool:
    """Every referenced line (of this document) is assigned to the party that references it."""
    numbers = {ln.number for ln in lines}
    return all(found.get(r) == p.key for p in order for r in p.refs if r in numbers)


def _search(lines: Sequence[Line], order: Sequence[Party], keep: bool) -> dict[int, int] | None:
    n = len(lines)
    owner = {r: i for i, p in enumerate(order) for r in p.refs} if keep else {}
    # what the lines from i on can still give a party at most / at least
    most = [0] * (n + 1)
    least = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        amount = lines[i].amount
        most[i] = most[i + 1] + max(amount, 0)
        least[i] = least[i + 1] + min(amount, 0)
    choice = [-1] * n
    dead: set[tuple[int, tuple[int, ...]]] = set()

    def reachable(i: int, need: tuple[int, ...]) -> bool:
        return all(least[i] <= x <= most[i] for x in need)

    def go(i: int, need: tuple[int, ...]) -> bool:
        if i == n:
            return not any(need)
        state = (i, need)
        if state in dead:
            return False
        line = lines[i]
        owed = owner.get(line.number)
        for j in range(len(need)) if owed is None else (owed,):
            after = need[:j] + (need[j] - line.amount,) + need[j + 1 :]
            if reachable(i + 1, after):
                choice[i] = j
                if go(i + 1, after):
                    return True
        if owed is None and reachable(i + 1, need):
            choice[i] = -1
            if go(i + 1, need):
                return True
        dead.add(state)
        return False

    start = tuple(p.amount for p in order)
    if not reachable(0, start) or not go(0, start):
        return None
    return {ln.number: order[c].key for ln, c in zip(lines, choice, strict=True) if c >= 0}
