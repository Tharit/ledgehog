"""Reports (architecture §4.1, spec §8): the Overview's figures and the three reports.

Reads only: no lock, no write, no settle. The answers carry the sums, so the client adds nothing: every
figure is a `Line` (its total in the base currency, how many entries it covers, the unvalued remainder
per currency), and savings is one shape (`SavingsOut`) for the Overview and the over-time report alike.
The filters are the ledger list's, one predicate, so the entries behind a figure are exactly the entries
its drill-down lists. Money travels as `{"amount": <minor units>, "currency": <code>}` (architecture §4.5).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from app.api.errors import map_error
from app.api.routers.accounts import (
    AccountOut,
    GroupWorthOut,
    Money,
    NetWorthUnvaluedOut,
    PointNetWorthOut,
    facts,
    worth_out,
)
from app.api.routers.accounts import Kind as AccountKind
from app.api.routers.entries import Ids
from app.api.session import CurrentUser, EngineDep
from app.core import reporting as rp
from app.core.ledger import InvalidFilter
from app.core.reporting import Line, Savings
from app.utils import clock

router = APIRouter(prefix="/api/reports", tags=["reports"])

# a 422 located at the query parameter that names the way out, like the ledger filter's
map_error(
    rp.TooManyPeriods,
    422,
    "validation_error",
    details=lambda e: [{"location": ["query", e.parameter], "message": str(e), "type": "too_many_periods"}],
)


class UnvaluedOut(BaseModel):
    amount: Money  # in the entries' own currency
    count: int


class LineOut(BaseModel):
    total: Money | None  # the base currency; null when entries exist and none could be valued
    count: int  # every entry covered, valued or not
    unvalued: list[UnvaluedOut]  # per currency; empty when every entry was valued

    @staticmethod
    def of(line: Line, base: str) -> LineOut:
        return LineOut(
            total=None if line.total is None else Money(amount=line.total, currency=base),
            count=line.count,
            unvalued=[
                UnvaluedOut(amount=Money(amount=u.amount, currency=u.currency), count=u.count)
                for u in line.unvalued
            ],
        )


class SavingsOut(BaseModel):
    income: LineOut
    expense: LineOut
    unclassified: LineOut  # both signs, net
    reconciliations: LineOut
    savings: LineOut  # the four summed
    rate_bp: int | None  # savings over income in basis points; null when income is not positive
    incomplete: bool  # unclassified entries, reconciliations or unvalued amounts in the four

    @staticmethod
    def of(s: Savings, base: str) -> SavingsOut:
        return SavingsOut(
            income=LineOut.of(s.income, base),
            expense=LineOut.of(s.expense, base),
            unclassified=LineOut.of(s.unclassified, base),
            reconciliations=LineOut.of(s.reconciliations, base),
            savings=LineOut.of(s.savings, base),
            rate_bp=s.rate_bp,
            incomplete=s.incomplete,
        )


class Span(BaseModel):
    """A range of days, inclusive on both ends."""

    from_: date = Field(serialization_alias="from")  # an answer only: `from` is a Python keyword
    to: date


class SavingsSpanOut(Span, SavingsOut):
    @staticmethod
    def span(span: rp.SavingsSpan, base: str) -> SavingsSpanOut:
        return SavingsSpanOut(from_=span.start, to=span.end, **SavingsOut.of(span.savings, base).model_dump())


class NetWorthSinceOut(BaseModel):
    on: date  # the end of last month
    change: Money  # base currency: today's net worth minus the one at `on`


class NetWorthOut(BaseModel):
    total: Money | None  # null when balances exist and none could be valued
    unvalued: list[NetWorthUnvaluedOut]
    unpaired_transfers: LineOut  # every unpaired leg, all dates, each at its own rate
    since: NetWorthSinceOut | None  # null when nothing existed at that date
    owed_to_you: GroupWorthOut | None  # the receivable accounts, null when none holds anything
    you_owe: GroupWorthOut | None  # the debt accounts, signed


class OverviewSavingsOut(BaseModel):
    last_12: SavingsSpanOut  # the 12 complete months before this one
    last_month: SavingsSpanOut
    this_month: SavingsSpanOut  # the 1st to today


class MonthSpendOut(Span):
    spend: LineOut  # expense-kind flows, refunds netting; the *By category* total of the range


class ThisMonthSpendOut(MonthSpendOut):
    unclassified_out: LineOut
    reconciliations: LineOut


class OverviewSpendOut(BaseModel):
    this_month: ThisMonthSpendOut
    last_month: MonthSpendOut
    last_month_to_date: MonthSpendOut  # the same day of last month, clamped to its last day


class OverviewAccountOut(AccountOut):
    data_age_days: int | None  # null = never fed


class DataAgeOut(BaseModel):
    # each the stalest few, never fed first, a settled clearance account last; a closed account only
    # while it holds a balance
    synced: list[OverviewAccountOut]
    by_hand: list[OverviewAccountOut]  # the unsynced accounts, clearance accounts included


class OverviewOut(BaseModel):
    as_of: date
    base_currency: str
    net_worth: NetWorthOut
    savings: OverviewSavingsOut
    spend: OverviewSpendOut
    data_age: DataAgeOut


@router.get("/overview")
def get_overview(user: CurrentUser, engine: EngineDep, request: Request) -> OverviewOut:
    """Net worth, savings of the last 12 months, last month and this month, this month's spend against
    last month's, and the stalest accounts by data age; the day is the household's today."""
    config = request.app.state.config
    base: str = config.base_currency
    today = clock.today(config.timezone)
    with engine.connect() as conn:
        ov = rp.overview(conn, today)

        def listed(items: tuple[rp.OverviewAccount, ...]) -> list[OverviewAccountOut]:
            return [
                OverviewAccountOut(**facts(conn, a.view).model_dump(), data_age_days=a.data_age_days)
                for a in items
            ]

        data_age = DataAgeOut(
            synced=listed(ov.data_age.synced),
            by_hand=listed(ov.data_age.by_hand),
        )
    worth = ov.net_worth
    spend = ov.spend_this_month
    since = (
        None
        if worth.since is None
        else NetWorthSinceOut(on=worth.since.on, change=Money(amount=worth.since.change, currency=base))
    )
    return OverviewOut(
        as_of=ov.as_of,
        base_currency=base,
        net_worth=NetWorthOut(
            total=None if worth.total is None else Money(amount=worth.total, currency=base),
            unvalued=worth_out(rp.NetWorth(worth.total, worth.unvalued), base).unvalued,
            unpaired_transfers=LineOut.of(worth.unpaired_transfers, base),
            since=since,
            owed_to_you=None if worth.owed_to_you is None else GroupWorthOut.of(worth.owed_to_you, base),
            you_owe=None if worth.you_owe is None else GroupWorthOut.of(worth.you_owe, base),
        ),
        savings=OverviewSavingsOut(
            last_12=SavingsSpanOut.span(ov.last_12, base),
            last_month=SavingsSpanOut.span(ov.last_month, base),
            this_month=SavingsSpanOut.span(ov.this_month, base),
        ),
        spend=OverviewSpendOut(
            this_month=ThisMonthSpendOut(
                from_=spend.start,
                to=spend.end,
                spend=LineOut.of(spend.spend, base),
                unclassified_out=LineOut.of(spend.unclassified_out, base),
                reconciliations=LineOut.of(spend.reconciliations, base),
            ),
            last_month=MonthSpendOut(
                from_=ov.spend_last_month.start,
                to=ov.spend_last_month.end,
                spend=LineOut.of(ov.spend_last_month.spend, base),
            ),
            last_month_to_date=MonthSpendOut(
                from_=ov.spend_last_month_to_date.start,
                to=ov.spend_last_month_to_date.end,
                spend=LineOut.of(ov.spend_last_month_to_date.spend, base),
            ),
        ),
        data_age=data_age,
    )


# ---- By category

Kind = Literal["expense", "income"]
Required = Annotated[date, Query()]


class CategoryRowOut(BaseModel):
    category_id: int
    parent_id: int | None
    own: LineOut  # the entries booked to the category itself
    total: LineOut  # with its descendants
    share_bp: int | None  # of the kind's total in basis points; null for a net of the other sign


class SliceOut(BaseModel):
    category_id: int
    total: LineOut


class ByCategoryOut(BaseModel):
    base_currency: str
    from_: date = Field(serialization_alias="from")
    to: date
    kind: Kind
    total: LineOut  # the kind's flows over the range, refunds netting
    categories: list[CategoryRowOut]  # flat, depth-first, siblings by magnitude; only those with entries
    slices: list[SliceOut] | None  # with `top`: the largest top-level categories of the kind's sign
    other: LineOut | None  # with `top`: the remaining ones, summed; null when there are none
    unclassified_out: LineOut
    unclassified_in: LineOut
    reconciliations: LineOut
    unconfirmed_count: int  # entries of the range not confirmed yet (their proposals are in the table)


@router.get("/by-category")
def get_by_category(
    user: CurrentUser,
    engine: EngineDep,
    request: Request,
    from_: Annotated[date, Query(alias="from")],
    to: Required,
    kind: Kind = "expense",
    account_id: Ids = None,
    tag_id: Ids = None,
    top: Annotated[int | None, Query(ge=1, le=50)] = None,
) -> ByCategoryOut:
    """Spend (or income) by category over a range, as the category tree, with the unclassified and
    reconciliation lines beside it. `account_id` and `tag_id` are the ledger list's filters."""
    base: str = request.app.state.config.base_currency
    flt = rp.entry_filter(from_, to, account_id or (), tag_id or ())
    with engine.connect() as conn:
        got = rp.by_category(conn, flt, kind, top)
    return ByCategoryOut(
        base_currency=base,
        from_=from_,
        to=to,
        kind=kind,
        total=LineOut.of(got.total, base),
        categories=[
            CategoryRowOut(
                category_id=r.category_id,
                parent_id=r.parent_id,
                own=LineOut.of(r.own, base),
                total=LineOut.of(r.total, base),
                share_bp=r.share_bp,
            )
            for r in got.categories
        ],
        slices=None
        if got.slices is None
        else [SliceOut(category_id=s.category_id, total=LineOut.of(s.total, base)) for s in got.slices],
        other=None if got.other is None else LineOut.of(got.other, base),
        unclassified_out=LineOut.of(got.unclassified_out, base),
        unclassified_in=LineOut.of(got.unclassified_in, base),
        reconciliations=LineOut.of(got.reconciliations, base),
        unconfirmed_count=got.unconfirmed_count,
    )


# ---- By account


class AccountLinkOut(BaseModel):
    account_id: int
    line: LineOut  # signed as booked


class CategoryLinksOut(BaseModel):
    category_id: int  # a top-level category
    total: LineOut  # with its descendants: its *By category* figure
    accounts: list[AccountLinkOut]  # the total cut by account; the links sum to it


class KindLinksOut(BaseModel):
    total: LineOut  # the kind's *By category* total
    categories: list[CategoryLinksOut]  # top-level, by magnitude; only those with entries
    slices: list[int] | None  # with `top`: the category ids of the largest of the kind's sign
    other: list[AccountLinkOut] | None  # with `top`: the remaining ones summed per account; null if none


class AccountLinksOut(BaseModel):
    total: LineOut  # the group's figure: the sum of its links, as *By category* gives it
    accounts: list[AccountLinkOut]


class TransferToOut(BaseModel):
    account_id: int | None  # the receiving account: the leg's counter-account; null: "Unpaired"
    line: LineOut  # as booked: negative for an outgoing leg


class TransferGroupOut(BaseModel):
    from_account_id: int | None  # null: the unpaired incoming legs, `to` being their own accounts
    total: LineOut  # the sum of `to`
    to: list[TransferToOut]


class StayedOut(BaseModel):
    """Derived, with no entries behind it: what the account received on the income side, less its transfers
    out, never below zero."""

    account_id: int
    amount: Money  # base currency, positive


class ByAccountOut(BaseModel):
    base_currency: str
    from_: date = Field(serialization_alias="from")
    to: date
    income: KindLinksOut
    expense: KindLinksOut
    unclassified_in: AccountLinksOut
    unclassified_out: AccountLinksOut
    reconciliations: AccountLinksOut  # one net link per account
    transfers: list[
        TransferGroupOut
    ]  # per sending account, then a group of no sender: the unpaired incoming legs
    stayed: list[StayedOut]  # per account: received on the income side less transferred out, if positive


def _account_links(links: tuple[rp.AccountLink, ...], base: str) -> list[AccountLinkOut]:
    return [AccountLinkOut(account_id=k.account_id, line=LineOut.of(k.line, base)) for k in links]


def _group(group: rp.AccountLinks, base: str) -> AccountLinksOut:
    return AccountLinksOut(total=LineOut.of(group.total, base), accounts=_account_links(group.accounts, base))


def _kind_links(kind: rp.KindLinks, base: str) -> KindLinksOut:
    return KindLinksOut(
        total=LineOut.of(kind.total, base),
        categories=[
            CategoryLinksOut(
                category_id=c.category_id,
                total=LineOut.of(c.total, base),
                accounts=_account_links(c.accounts, base),
            )
            for c in kind.categories
        ],
        slices=None if kind.slices is None else list(kind.slices),
        other=None if kind.other is None else _account_links(kind.other, base),
    )


@router.get("/by-account")
def get_by_account(
    user: CurrentUser,
    engine: EngineDep,
    request: Request,
    from_: Annotated[date, Query(alias="from")],
    to: Required,
    tag_id: Ids = None,
    top: Annotated[int | None, Query(ge=1, le=50)] = None,
) -> ByAccountOut:
    """The money each account received, passed on and paid over a range, as a list of links: the
    *By category* figures cut by account, the transfers by account and counter-account
    (an unpaired leg against no account), and what stayed.
    There is no `account_id`: a transfer into a chosen account would drop out of its own account's view."""
    base: str = request.app.state.config.base_currency
    flt = rp.entry_filter(from_, to, (), tag_id or ())
    with engine.connect() as conn:
        got = rp.by_account(conn, flt, top)
    return ByAccountOut(
        base_currency=base,
        from_=from_,
        to=to,
        income=_kind_links(got.income, base),
        expense=_kind_links(got.expense, base),
        unclassified_in=_group(got.unclassified_in, base),
        unclassified_out=_group(got.unclassified_out, base),
        reconciliations=_group(got.reconciliations, base),
        transfers=[
            TransferGroupOut(
                from_account_id=g.from_account_id,
                total=LineOut.of(g.total, base),
                to=[TransferToOut(account_id=t.account_id, line=LineOut.of(t.line, base)) for t in g.to],
            )
            for g in got.transfers
        ],
        stayed=[
            StayedOut(
                account_id=s.account_id,
                amount=Money(amount=s.amount, currency=base),
            )
            for s in got.stayed
        ],
    )


# ---- Over time


OverTimeKind = Literal["expense", "income", "transfer_in", "transfer_out"]


class PeriodOut(Span):
    """A calendar month, quarter or year, clipped to the range."""


class CategorySeriesOut(BaseModel):
    category_id: int
    parent_id: int | None
    own: list[LineOut]  # per period
    total: list[LineOut]  # per period, with the descendants
    own_sum: LineOut  # the entries booked to the category itself, over the range
    sum: LineOut  # the category's total over the range


class SliceIdOut(BaseModel):
    category_id: int


class SliceAccountOut(BaseModel):
    account_id: int


class AccountSeriesOut(BaseModel):
    account_id: int
    total: list[LineOut]  # per period: the account's amount of the kind
    sum: LineOut  # over the range


class AccountKindSeriesOut(BaseModel):
    kind: AccountKind
    total: list[LineOut]  # per period: its accounts' amounts, added
    sum: LineOut  # over the range


class OverTimeOut(BaseModel):
    """Only the fields of the chosen mode are present."""

    base_currency: str
    kind: OverTimeKind
    step: rp.Step
    periods: list[PeriodOut]
    # mode = savings
    savings: list[SavingsOut] | None = None  # per period
    total: SavingsOut | None = None  # the whole range: its savings over its income, not a mean of rates
    # mode = category
    categories: list[CategorySeriesOut] | None = None  # flat, depth-first, siblings by the range's magnitude
    slices: list[SliceIdOut] | None = None  # the largest top-level categories of the kind's sign
    other: list[LineOut] | None = None  # per period: the remaining top-level categories, summed
    totals: list[LineOut] | None = None  # per period: the kind's total
    sum: LineOut | None = None  # the kind's total over the range
    # mode = account (also `other`, `totals` and `sum`, as above)
    accounts: list[AccountSeriesOut] | None = None  # only accounts with entries, by the range's magnitude
    account_kinds: list[AccountKindSeriesOut] | None = None  # in the usual kind order; kinds with an account
    account_slices: list[SliceAccountOut] | None = None  # the largest accounts of the kind's sign


@router.get("/over-time", response_model_exclude_unset=True)
def get_over_time(
    user: CurrentUser,
    engine: EngineDep,
    request: Request,
    from_: Annotated[date, Query(alias="from")],
    to: Required,
    step: rp.Step = "month",
    mode: Literal["savings", "category", "account"] = "savings",
    kind: OverTimeKind = "expense",
    account_id: Ids = None,
    tag_id: Ids = None,
) -> OverTimeOut:
    """A range cut into calendar months, quarters or years (at most 120): the savings and rate of each,
    or each category's amount of a kind (`expense`, `income`), or each account's amount of a kind (those
    two, or `transfer_in` / `transfer_out`: its transfer legs by direction, paired or not). The transfer
    kinds only exist in mode `account`: with another mode, `kind` is a 422. The ledger list's account and
    tag filters apply to every figure."""
    base: str = request.app.state.config.base_currency
    flt = rp.entry_filter(from_, to, account_id or (), tag_id or ())
    if kind.startswith("transfer") and mode != "account":
        raise InvalidFilter("kind", f"kind {kind} is only available in mode account")
    with engine.connect() as conn:
        if mode == "account":
            by_acc = rp.accounts_over_time(conn, flt, step, kind)
            return OverTimeOut(
                base_currency=base,
                kind=kind,
                step=step,
                periods=[PeriodOut(from_=p.start, to=p.end) for p in by_acc.periods],
                accounts=[
                    AccountSeriesOut(
                        account_id=a.account_id,
                        total=[LineOut.of(x, base) for x in a.total],
                        sum=LineOut.of(a.sum, base),
                    )
                    for a in by_acc.accounts
                ],
                account_kinds=[
                    AccountKindSeriesOut(
                        kind=k.kind,  # type: ignore[arg-type]
                        total=[LineOut.of(x, base) for x in k.total],
                        sum=LineOut.of(k.sum, base),
                    )
                    for k in by_acc.account_kinds
                ],
                account_slices=[SliceAccountOut(account_id=a) for a in by_acc.slices],
                other=[LineOut.of(x, base) for x in by_acc.other],
                totals=[LineOut.of(x, base) for x in by_acc.totals],
                sum=LineOut.of(by_acc.sum, base),
            )
        if mode == "savings":
            got = rp.savings_over_time(conn, flt, step)
            return OverTimeOut(
                base_currency=base,
                kind=kind,
                step=step,
                periods=[PeriodOut(from_=p.start, to=p.end) for p in got.periods],
                savings=[SavingsOut.of(s, base) for s in got.savings],
                total=SavingsOut.of(got.total, base),
            )
        by_cat = rp.categories_over_time(conn, flt, step, kind)
    return OverTimeOut(
        base_currency=base,
        kind=kind,
        step=step,
        periods=[PeriodOut(from_=p.start, to=p.end) for p in by_cat.periods],
        categories=[
            CategorySeriesOut(
                category_id=c.category_id,
                parent_id=c.parent_id,
                own=[LineOut.of(x, base) for x in c.own],
                total=[LineOut.of(x, base) for x in c.total],
                own_sum=LineOut.of(c.own_sum, base),
                sum=LineOut.of(c.sum, base),
            )
            for c in by_cat.categories
        ],
        slices=[SliceIdOut(category_id=c) for c in by_cat.slices],
        other=[LineOut.of(x, base) for x in by_cat.other],
        totals=[LineOut.of(x, base) for x in by_cat.totals],
        sum=LineOut.of(by_cat.sum, base),
    )


# ---- Balances


class AccountBalancesOut(BaseModel):
    account_id: int
    # the base-currency value at each point; null where the account has no balance yet or it is unvalued
    balances: list[Money | None]
    native: list[Money]  # the balance in the account's own currency at each point


class KindNetWorthOut(BaseModel):
    kind: AccountKind
    net_worth: list[PointNetWorthOut]  # per point: the net worth of the listed accounts of this kind


class BalancesOut(BaseModel):
    base_currency: str
    points: list[date]  # the range's month-ends, a future one replaced by today, today when in the range
    net_worth: list[PointNetWorthOut]  # per point
    kinds: list[KindNetWorthOut]  # only kinds with a listed account, in the account kinds' usual order
    accounts: list[AccountBalancesOut]  # open accounts, and closed ones that held a balance in the range


@router.get("/balances")
def get_balances(
    user: CurrentUser,
    engine: EngineDep,
    request: Request,
    from_: Annotated[date, Query(alias="from")],
    to: Required,
) -> BalancesOut:
    """Net worth and every account's balance at the month-ends of a range. A balance is every entry
    booked on or before the point (openings, valuations and reconciliations included), converted at that
    date's rate; an amount that cannot be valued is listed, never counted as zero."""
    config = request.app.state.config
    base: str = config.base_currency
    if from_ > to:
        raise InvalidFilter("to", "to must not be before from")
    with engine.connect() as conn:
        got = rp.balances_report(conn, from_, to, clock.today(config.timezone))
    return BalancesOut(
        base_currency=base,
        points=list(got.points),
        net_worth=[worth_out(n, base) for n in got.net_worth],
        kinds=[
            KindNetWorthOut(
                kind=k.kind,  # type: ignore[arg-type]
                net_worth=[worth_out(n, base) for n in k.net_worth],
            )
            for k in got.kinds
        ],
        accounts=[
            AccountBalancesOut(
                account_id=a.account_id,
                balances=[None if b is None else Money(amount=b, currency=base) for b in a.base],
                native=[Money(amount=b, currency=a.currency) for b in a.native],
            )
            for a in got.accounts
        ],
    )
