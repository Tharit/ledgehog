"""An investment account's net deposits, gain and money-weighted return (spec §8, D249).

Computed the way the statement's gaps are, from source transactions and counting records alone;
the derived entries are never read, so the figures hold whatever state they are in. With the
anchor `(D1, B1)`, the latest counting record `(Dn, Bn)` and the account's movements:

    net deposits = B1 + sum(movements dated after D1)      (all of them, also those after Dn)
    gain         = balance - net deposits                  (which is the sum of the valuations)
    return       = the annual rate (actual/365) at which -B1 on D1, -m on the date of each
                   movement in (D1, Dn] and +Bn on Dn discount to zero (XIRR)

The return is `None` without a record after the anchor, below a year between anchor and latest
record, and where no rate solves it.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Connection, text

from app.core.domain.kinds import INVESTMENT_KINDS

MIN_SPAN_DAYS = 365  # a rate annualised from a shorter span misleads (spec §8)
_LOW, _HIGH = -0.9999, 10.0  # the rates searched: -99.99 % to +1000 % a year
_GRID = 400  # the search's resolution, before a bracket is refined
_TOLERANCE = 1e-12


@dataclass(frozen=True)
class Performance:
    net_deposits: int
    gain: int
    return_rate_bp: int | None  # the annual return in basis points, half-even; None: not shown
    return_as_of: date


def xirr(flows: Sequence[tuple[date, int]]) -> float | None:
    """The annual rate `r` with sum(amount * (1 + r) ** (-(day - first day) / 365)) = 0.

    `None` unless the flows change sign and a root lies in (-0.9999, 10). Where several roots
    exist, the one nearest zero wins.
    """
    if not any(a > 0 for _, a in flows) or not any(a < 0 for _, a in flows):
        return None
    start = min(d for d, _ in flows)
    points = [((d - start).days / 365, float(a)) for d, a in flows]

    def value(r: float) -> float | None:
        try:
            return sum(a * math.exp(-t * math.log1p(r)) for t, a in points)
        except OverflowError:
            return None

    def slope(r: float) -> float | None:
        try:
            return sum(-t * a * math.exp(-(t + 1) * math.log1p(r)) for t, a in points)
        except OverflowError:
            return None

    # a grid evenly spaced in log(1 + r), so low and high rates are both resolved
    lo_u, hi_u = math.log1p(_LOW), math.log1p(_HIGH)
    grid = [math.expm1(lo_u + (hi_u - lo_u) * i / _GRID) for i in range(_GRID + 1)]
    brackets: list[tuple[float, float]] = []
    prev: tuple[float, float] | None = None
    for r in grid:
        v = value(r)
        if v is None:
            prev = None
            continue
        if v == 0:
            return r
        if prev is not None and (prev[1] < 0) != (v < 0):
            brackets.append((prev[0], r))
        prev = (r, v)
    if not brackets:
        return None
    lo, hi = min(brackets, key=lambda b: min(abs(b[0]), abs(b[1])))
    return _solve(value, slope, lo, hi)


def _solve(
    value: Callable[[float], float | None],
    slope: Callable[[float], float | None],
    lo: float,
    hi: float,
) -> float | None:
    """Newton from the bracket's middle, bisecting wherever a step leaves the bracket."""
    f_lo = value(lo)
    if f_lo is None:
        return None
    x = (lo + hi) / 2
    for _ in range(200):
        fx = value(x)
        if fx is None:
            return None
        if fx == 0:
            return x
        if (fx < 0) == (f_lo < 0):
            lo, f_lo = x, fx
        else:
            hi = x
        if hi - lo < _TOLERANCE:
            return (lo + hi) / 2
        dx = slope(x)
        step = None if not dx else x - fx / dx
        x = step if step is not None and lo < step < hi else (lo + hi) / 2
    return None


def performance(conn: Connection, account_id: int, kind: str, balance: int) -> Performance | None:
    """The account's figures, `None` for another kind of account and for one without a record."""
    if kind not in INVESTMENT_KINDS:
        return None
    records = conn.execute(
        text(
            "SELECT balance_on, balance FROM v_balance_record WHERE account_id = :a "
            "ORDER BY balance_on, id"
        ),
        {"a": account_id},
    ).all()
    if not records:
        return None
    d1, b1 = records[0].balance_on, int(records[0].balance)
    dn, bn = records[-1].balance_on, int(records[-1].balance)
    movements = [
        (r.booked_on, int(r.total))
        for r in conn.execute(
            text(
                "SELECT booked_on, sum(amount)::bigint AS total FROM source_transaction "
                "WHERE account_id = :a AND duplicate_of IS NULL AND booked_on > :d1 "
                "GROUP BY booked_on ORDER BY booked_on"
            ),
            {"a": account_id, "d1": d1},
        )
    ]
    net_deposits = b1 + sum(a for _, a in movements)
    rate = None
    if len(records) > 1 and (dn - d1).days >= MIN_SPAN_DAYS:
        flows = [(d1, -b1), *((d, -a) for d, a in movements if d <= dn), (dn, bn)]
        r = xirr(flows)
        rate = None if r is None else round(r * 10_000)
    return Performance(net_deposits, balance - net_deposits, rate, dn)
