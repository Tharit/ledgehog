"""Balances and net worth at dates (spec §3.8, §8; schema `net_worth_on`).

An account's balance at a date is every entry booked on or before it (openings, valuations and
reconciliations included), converted at that date's rate with `base_value()`; a zero balance is worth
zero without a rate; an account with no entry yet has no balance (None), not zero. The net worth is the
sum of those that can be valued; the others are reported per currency, never as zero.

`through_all` takes every entry whatever its date: the account list's balance, and so the Overview's
net worth today (an entry dated after today counts until its date comes).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Connection, text

from app.core.reporting.periods import TooManyPeriods, add_months, month_end

MAX_POINTS = 120

# the account kinds in the order of the schema's check constraint (spec §3.3), which the API's `Kind` follows
KIND_ORDER = (
    "checking",
    "savings",
    "card",
    "cash",
    "digital_wallet",
    "depot",
    "debt",
    "receivable",
    "asset",
    "clearance",
)

_BALANCES = text(
    """
    WITH pts AS (SELECT unnest(CAST(:dates AS date[])) AS p),
    bal AS (
        SELECT a.id AS account_id, a.currency, pts.p,
               COALESCE(sum(e.amount), 0)::bigint AS balance, count(e.id) AS n
          FROM account a CROSS JOIN pts
          LEFT JOIN ledger_entry e
                 ON e.account_id = a.id AND (CAST(:through_all AS boolean) OR e.booked_on <= pts.p)
         GROUP BY a.id, a.currency, pts.p
    )
    SELECT account_id, currency, p, balance, n,
           CASE WHEN n = 0 THEN NULL
                WHEN balance = 0 THEN 0
                ELSE base_value(balance, currency, p) END AS base
      FROM bal
     ORDER BY account_id, p
    """
)


@dataclass(frozen=True)
class AccountBalance:
    account_id: int
    currency: str
    on: date
    balance: int  # minor units of `currency`
    entries: int  # how many entries it sums; 0 = no balance yet
    base: int | None  # in the base currency at `on`'s rate; None = no entry yet, or unvalued


@dataclass(frozen=True)
class UnvaluedAccounts:
    currency: str
    amount: int  # the native balance of those accounts, summed
    accounts: int


@dataclass(frozen=True)
class NetWorth:
    total: int | None  # the sum of the valued balances; None when balances exist and none could be valued
    unvalued: tuple[UnvaluedAccounts, ...]


def balances_on(
    conn: Connection, dates: Sequence[date], *, through_all: bool = False
) -> list[AccountBalance]:
    """Every account's balance at each date, ordered by account then date."""
    if not dates:
        return []
    return [
        AccountBalance(
            int(r.account_id),
            str(r.currency),
            r.p,
            int(r.balance),
            int(r.n),
            None if r.base is None else int(r.base),
        )
        for r in conn.execute(_BALANCES, {"dates": list(dates), "through_all": through_all})
    ]


def net_worth_of(rows: Sequence[AccountBalance]) -> NetWorth:
    """The net worth of one date's balances; accounts holding nothing are left out."""
    held = [r for r in rows if r.balance != 0]
    valued = [r for r in held if r.base is not None]
    unvalued: dict[str, tuple[int, int]] = {}
    for r in held:
        if r.base is None:
            amount, n = unvalued.get(r.currency, (0, 0))
            unvalued[r.currency] = (amount + r.balance, n + 1)
    total = None if held and not valued else sum(r.base or 0 for r in valued)
    return NetWorth(total, tuple(UnvaluedAccounts(c, a, n) for c, (a, n) in sorted(unvalued.items())))


def net_worth_at(conn: Connection, on: date, *, through_all: bool = False) -> tuple[NetWorth, bool]:
    """The net worth at `on`, and whether any entry exists to say it."""
    rows = balances_on(conn, [on], through_all=through_all)
    return net_worth_of(rows), any(r.entries for r in rows)


def points(start: date, end: date, today: date) -> list[date]:
    """The balance dates of a range: its month-ends, a future one replaced by today, and today when
    the range holds it (the current month's point is today). Ascending, once each."""
    out: set[date] = set()
    month = start.replace(day=1)
    while month_end(month) <= end:
        last = month_end(month)
        if last >= start:
            out.add(min(last, today))
        month = add_months(month, 1)
    if start <= today <= end:
        out.add(today)
    return sorted(out)


@dataclass(frozen=True)
class AccountSeries:
    account_id: int
    currency: str
    base: tuple[int | None, ...]  # per point; None = no balance yet, or unvalued
    native: tuple[int, ...]  # per point, in the account's currency


@dataclass(frozen=True)
class KindSeries:
    kind: str
    net_worth: tuple[NetWorth, ...]  # per point: the net worth of the listed accounts of this kind


@dataclass(frozen=True)
class BalancesReport:
    points: tuple[date, ...]
    net_worth: tuple[NetWorth, ...]  # per point
    kinds: tuple[KindSeries, ...]  # in KIND_ORDER; only kinds with a listed account
    accounts: tuple[AccountSeries, ...]


def balances_report(conn: Connection, start: date, end: date, today: date) -> BalancesReport:
    """Net worth, each account kind's net worth and every account's balance at the range's month-ends.

    All open accounts are listed; a closed one only when it held a balance at some point. A kind's net
    worth is `net_worth_of` its listed accounts, so unvalued amounts are handled exactly as in the total.
    """
    dates = points(start, end, today)
    if len(dates) > MAX_POINTS:
        raise TooManyPeriods("from", f"the range has more than {MAX_POINTS} month-ends: shorten it")
    rows = balances_on(conn, dates)
    by_account: dict[int, list[AccountBalance]] = {}
    for r in rows:
        by_account.setdefault(r.account_id, []).append(r)
    account_rows = conn.execute(text("SELECT id, kind, closed_on IS NOT NULL AS closed FROM account")).all()
    closed = {int(r.id) for r in account_rows if r.closed}
    kind_of = {int(r.id): str(r.kind) for r in account_rows}
    listed = {
        account_id: series_rows
        for account_id, series_rows in by_account.items()
        if account_id not in closed or any(r.balance != 0 for r in series_rows)
    }
    series = tuple(
        AccountSeries(
            account_id=account_id,
            currency=series_rows[0].currency,
            base=tuple(r.base for r in series_rows),
            native=tuple(r.balance for r in series_rows),
        )
        for account_id, series_rows in listed.items()
    )
    net_worth = tuple(net_worth_of([r for r in rows if r.on == d]) for d in dates)
    kinds = tuple(
        KindSeries(
            kind,
            tuple(
                net_worth_of([r for a, rs in listed.items() if kind_of[a] == kind for r in rs if r.on == d])
                for d in dates
            ),
        )
        for kind in KIND_ORDER
        if any(kind_of[a] == kind for a in listed)
    )
    return BalancesReport(tuple(dates), net_worth, kinds, series)


@dataclass(frozen=True)
class GroupWorth:
    """What a group of accounts is worth at today's rate: the account list's group row."""

    kind: str | None  # None = the closed accounts
    accounts: int
    net_worth: NetWorth


def _account_kinds(conn: Connection) -> dict[int, tuple[str, bool]]:
    return {
        int(r.id): (str(r.kind), r.closed)
        for r in conn.execute(text("SELECT id, kind, closed_on IS NOT NULL AS closed FROM account"))
    }


def group_worths(conn: Connection, today: date) -> tuple[GroupWorth, ...]:
    """The account list's groups: a kind per kind with open accounts, in KIND_ORDER, each the net worth
    of its open accounts; then the closed accounts, if any. Every entry counts, whatever its date, as in
    the list's balances; unvalued amounts are handled as in the net worth."""
    rows = balances_on(conn, [today], through_all=True)
    meta = _account_kinds(conn)
    groups = [
        GroupWorth(
            kind,
            len(mine),
            net_worth_of(mine),
        )
        for kind in KIND_ORDER
        if (mine := [r for r in rows if meta[r.account_id] == (kind, False)])
    ]
    closed = [r for r in rows if meta[r.account_id][1]]
    if closed:
        groups.append(GroupWorth(None, len(closed), net_worth_of(closed)))
    return tuple(groups)


def kind_held(conn: Connection, today: date, kind: str) -> GroupWorth | None:
    """What the accounts of one kind, open or closed, hold at today's rate, and how many hold anything;
    None when none does."""
    meta = _account_kinds(conn)
    held = [
        r
        for r in balances_on(conn, [today], through_all=True)
        if meta[r.account_id][0] == kind and r.balance != 0
    ]
    return GroupWorth(kind, len(held), net_worth_of(held)) if held else None
