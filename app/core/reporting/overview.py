"""The Overview's figures (spec §3.11, §6, §8; architecture §4.1).

One moment in time: net worth, savings of the last 12 complete months, last month and this month so
far, this month's spend against last month's, and the stalest accounts by data age. Savings and spend come
from the same facts as the reports (`facts.fetch`, `savings.savings_in`), so a figure here and the
report it links to cannot disagree: this month's spend is the *By category* total of the month.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import Connection, text

from app.core.accounts import AccountView, list_accounts
from app.core.reporting.balances import GroupWorth, UnvaluedAccounts, balances_on, kind_held, net_worth_of
from app.core.reporting.facts import entry_filter, fetch
from app.core.reporting.line import Line, Savings, add, line_of_group
from app.core.reporting.periods import add_months, last_month_end, month_start, same_day_last_month
from app.core.reporting.savings import savings_in

_UNPAIRED = text(
    """
    WITH legs AS MATERIALIZED (
        SELECT e.currency, e.amount, base_value(e.amount, e.currency, e.booked_on) AS base
          FROM v_open_transfer_legs e)
    SELECT currency, count(*) AS n, count(*) FILTER (WHERE base IS NULL) AS n_unvalued,
           COALESCE(sum(base), 0) AS base_sum,
           COALESCE(sum(amount) FILTER (WHERE base IS NULL), 0) AS unvalued_sum
      FROM legs GROUP BY currency
    """
)


@dataclass(frozen=True)
class NetWorthSince:
    on: date  # the end of last month
    change: int  # base currency minor units: today's net worth minus that one


@dataclass(frozen=True)
class NetWorthFigure:
    total: int | None
    unvalued: tuple[UnvaluedAccounts, ...]
    unpaired_transfers: Line  # every unpaired leg, all dates, at each leg's own rate
    since: NetWorthSince | None
    owed_to_you: GroupWorth | None  # the receivable accounts' total; None when none holds anything
    you_owe: GroupWorth | None  # the debt accounts', signed


@dataclass(frozen=True)
class SavingsSpan:
    start: date
    end: date
    savings: Savings


@dataclass(frozen=True)
class MonthSpend:
    start: date
    end: date
    spend: Line


@dataclass(frozen=True)
class ThisMonthSpend(MonthSpend):
    unclassified_out: Line
    reconciliations: Line


@dataclass(frozen=True)
class OverviewAccount:
    view: AccountView
    data_age_days: int | None  # None = never fed


STALEST = 3  # per list on the Data age card


@dataclass(frozen=True)
class DataAge:
    synced: tuple[OverviewAccount, ...]  # the stalest few of the synced accounts
    by_hand: tuple[OverviewAccount, ...]  # of the unsynced ones, clearance accounts included
    accounts: int  # how many open accounts there are


@dataclass(frozen=True)
class Overview:
    as_of: date
    net_worth: NetWorthFigure
    last_12: SavingsSpan
    last_month: SavingsSpan
    this_month: SavingsSpan
    spend_this_month: ThisMonthSpend
    spend_last_month: MonthSpend
    spend_last_month_to_date: MonthSpend
    data_age: DataAge


def unpaired_transfers(conn: Connection) -> Line:
    return add(
        line_of_group(str(r.currency), int(r.n), int(r.n_unvalued), int(r.base_sum), int(r.unvalued_sum))
        for r in conn.execute(_UNPAIRED)
    )


def net_worth_figure(conn: Connection, today: date) -> NetWorthFigure:
    """Every account's full balance at today's rate; `since` is the change against the net worth at
    last month's end (entries cut at that date, converted at its rate), none when nothing existed then."""
    now = net_worth_of(balances_on(conn, [today], through_all=True))
    then_rows = balances_on(conn, [last_month_end(today)])
    then = net_worth_of(then_rows)
    existed = any(r.entries for r in then_rows)
    since = (
        NetWorthSince(last_month_end(today), now.total - then.total)
        if existed and now.total is not None and then.total is not None
        else None
    )
    return NetWorthFigure(
        now.total,
        now.unvalued,
        unpaired_transfers(conn),
        since,
        kind_held(conn, today, "receivable"),
        kind_held(conn, today, "debt"),
    )


def _settled(v: AccountView) -> bool:
    return v.kind == "clearance" and v.balance == 0


def _stalest(views: list[AccountView], today: date) -> tuple[OverviewAccount, ...]:
    """Stalest first, accounts never fed first of all, a settled clearance account last, ties by sort
    order then id."""
    ranked = sorted(
        views,
        key=lambda v: (
            _settled(v),
            v.last_data_on is not None,
            v.last_data_on or date.min,
            v.sort_order,
            v.id,
        ),
    )
    return tuple(
        OverviewAccount(v, None if v.last_data_on is None else max(0, (today - v.last_data_on).days))
        for v in ranked[:STALEST]
    )


def data_age(views: list[AccountView], today: date) -> DataAge:
    """The three stalest synced and the three stalest hand-kept accounts (spec §3.11). A closed account
    is listed only while it holds a balance."""
    shown = [v for v in views if v.closed_on is None or v.balance != 0]
    return DataAge(
        synced=_stalest([v for v in shown if v.synced], today),
        by_hand=_stalest([v for v in shown if not v.synced], today),
        accounts=sum(1 for v in views if v.closed_on is None),
    )


def overview(conn: Connection, today: date) -> Overview:
    this_start = month_start(today)
    last_start = add_months(this_start, -1)
    first = add_months(this_start, -12)
    facts = fetch(conn, entry_filter(first, today), "month")
    months_12: set[date | None] = {add_months(this_start, -n) for n in range(1, 13)}

    def span(start: date, end: date, buckets: set[date | None]) -> SavingsSpan:
        return SavingsSpan(start, end, savings_in(facts, buckets))

    to_date = same_day_last_month(today)
    same_day = fetch(conn, entry_filter(last_start, to_date))
    return Overview(
        as_of=today,
        net_worth=net_worth_figure(conn, today),
        last_12=span(first, last_month_end(today), months_12),
        last_month=span(last_start, last_month_end(today), {last_start}),
        this_month=span(this_start, today, {this_start}),
        spend_this_month=ThisMonthSpend(
            this_start,
            today,
            facts.klass("expense", {this_start}),
            facts.klass("unclassified_out", {this_start}),
            facts.klass("reconciliation", {this_start}),
        ),
        spend_last_month=MonthSpend(last_start, last_month_end(today), facts.klass("expense", {last_start})),
        spend_last_month_to_date=MonthSpend(last_start, to_date, same_day.klass("expense")),
        data_age=data_age(list_accounts(conn), today),
    )
