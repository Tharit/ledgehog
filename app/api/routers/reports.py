"""Reports (architecture §4.1, spec §8): the Overview's figures and the three reports.

Reads only: no lock, no write, no settle. The answers carry the sums, so the client adds nothing: every
figure is a `Line` (its total in the base currency, how many entries it covers, the unvalued remainder
per currency), and savings is one shape (`SavingsOut`) for the Overview and the over-time report alike.
The filters are the ledger list's, one predicate, so the entries behind a figure are exactly the entries
its drill-down lists. Money travels as `{"amount": <minor units>, "currency": <code>}` (architecture §4.5).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api.errors import map_error
from app.api.routers.accounts import AccountOut, Money, facts
from app.api.session import CurrentUser, EngineDep
from app.core import reporting as rp
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


class NetWorthUnvaluedOut(BaseModel):
    amount: Money  # the accounts' native balances, summed
    accounts: int


class NetWorthSinceOut(BaseModel):
    on: date  # the end of last month
    change: Money  # base currency: today's net worth minus the one at `on`


class NetWorthOut(BaseModel):
    total: Money | None  # null when balances exist and none could be valued
    unvalued: list[NetWorthUnvaluedOut]
    unpaired_transfers: LineOut  # every unpaired leg, all dates, each at its own rate
    since: NetWorthSinceOut | None  # null when nothing existed at that date


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


class OverviewOut(BaseModel):
    as_of: date
    base_currency: str
    net_worth: NetWorthOut
    savings: OverviewSavingsOut
    spend: OverviewSpendOut
    accounts: list[OverviewAccountOut]  # stalest first, never first; closed ones only with a balance


def _worth_unvalued(items: tuple[rp.UnvaluedAccounts, ...]) -> list[NetWorthUnvaluedOut]:
    return [
        NetWorthUnvaluedOut(amount=Money(amount=u.amount, currency=u.currency), accounts=u.accounts)
        for u in items
    ]


@router.get("/overview")
def get_overview(user: CurrentUser, engine: EngineDep, request: Request) -> OverviewOut:
    """Net worth, savings of the last 12 months, last month and this month, this month's spend against
    last month's, and the accounts by data age; the day is the household's today."""
    config = request.app.state.config
    base: str = config.base_currency
    today = clock.today(config.timezone)
    with engine.connect() as conn:
        ov = rp.overview(conn, today)
        accounts = [
            OverviewAccountOut(**facts(conn, a.view).model_dump(), data_age_days=a.data_age_days)
            for a in ov.accounts
        ]
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
            unvalued=_worth_unvalued(worth.unvalued),
            unpaired_transfers=LineOut.of(worth.unpaired_transfers, base),
            since=since,
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
        accounts=accounts,
    )
