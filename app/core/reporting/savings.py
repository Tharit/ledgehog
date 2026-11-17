"""Savings, and the range cut into periods (spec §8, architecture §4.1).

`savings_in` is THE savings computation: the Overview's cards and the over-time report both call it,
over the buckets they want, so their figures cannot disagree. A range's savings and rate are those of
its whole span (the sum of its periods' Lines), never a mean of periods' rates.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Connection, Date, DateTime, cast, func, literal, or_, select, text
from sqlalchemy.sql.elements import ColumnElement

from app.core.ledger import LedgerFilter, compose
from app.core.ledger.sql import le
from app.core.reporting.balances import KIND_ORDER
from app.core.reporting.facts import CLASS_OF, KIND_SIGN, Facts, fetch, rcat
from app.core.reporting.line import EMPTY, Line, Savings, add, line_of_group, savings_of
from app.core.reporting.periods import Period, Step, periods
from app.core.reporting.tree import category_tree, opposes, pick_slices

TOP_SLICES = 6
ACCOUNT_KINDS = ("expense", "income", "transfer_in", "transfer_out")  # the kinds of the by-account mode


def savings_in(facts: Facts, buckets: Collection[date | None] | None = None) -> Savings:
    """Savings over `buckets` of the facts (None: all of them)."""
    return savings_of(
        income=facts.klass("income", buckets),
        expense=facts.klass("expense", buckets),
        unclassified=add([facts.klass("unclassified_out", buckets), facts.klass("unclassified_in", buckets)]),
        reconciliations=facts.klass("reconciliation", buckets),
    )


@dataclass(frozen=True)
class SavingsOverTime:
    periods: tuple[Period, ...]
    savings: tuple[Savings, ...]  # per period
    total: Savings  # the whole range


@dataclass(frozen=True)
class CategorySeries:
    category_id: int
    parent_id: int | None
    own: tuple[Line, ...]  # per period
    total: tuple[Line, ...]
    own_sum: Line  # the entries booked to the node itself, over the range
    sum: Line  # the node's total over the range


@dataclass(frozen=True)
class CategoriesOverTime:
    kind: str
    periods: tuple[Period, ...]
    categories: tuple[CategorySeries, ...]  # depth-first, siblings by the range's magnitude
    slices: tuple[int, ...]  # the largest top-level categories of the kind's sign over the range
    other: tuple[Line, ...]  # per period: the remaining top-level categories, summed
    totals: tuple[Line, ...]  # per period: the kind's total
    sum: Line  # the kind's total over the range


@dataclass(frozen=True)
class AccountOverTime:
    account_id: int
    total: tuple[Line, ...]  # per period: the account's amount of the kind
    sum: Line  # over the range


@dataclass(frozen=True)
class AccountKindOverTime:
    kind: str  # an account kind
    total: tuple[Line, ...]  # per period: its accounts' amounts, added
    sum: Line  # over the range


@dataclass(frozen=True)
class AccountsOverTime:
    kind: str  # expense, income, transfer_in or transfer_out
    periods: tuple[Period, ...]
    accounts: tuple[AccountOverTime, ...]  # only those with entries, by the range's magnitude
    account_kinds: tuple[AccountKindOverTime, ...]  # in KIND_ORDER; only kinds with a listed account
    slices: tuple[int, ...]  # the largest accounts of the kind's sign over the range
    other: tuple[Line, ...]  # per period: the remaining accounts, summed
    totals: tuple[Line, ...]  # per period: the kind's total
    sum: Line  # the kind's total over the range


def savings_over_time(conn: Connection, flt: LedgerFilter, step: Step) -> SavingsOverTime:
    assert flt.date_from is not None and flt.date_to is not None
    cut = periods(flt.date_from, flt.date_to, step)
    facts = fetch(conn, flt, step)
    return SavingsOverTime(
        periods=tuple(cut),
        savings=tuple(savings_in(facts, {p.bucket}) for p in cut),
        total=savings_in(facts),
    )


def categories_over_time(conn: Connection, flt: LedgerFilter, step: Step, kind: str) -> CategoriesOverTime:
    assert flt.date_from is not None and flt.date_to is not None
    cut = periods(flt.date_from, flt.date_to, step)
    buckets: list[date | None] = [p.bucket for p in cut]
    facts = fetch(conn, flt, step)
    nodes, total = category_tree(conn, facts, kind, buckets)
    chosen, rest = pick_slices(nodes, kind, TOP_SLICES)
    other = tuple(
        # a period in which a remaining category nets to the other sign leaves that category out of the bar
        add(n.total[i] for n in rest if not opposes(n.total[i], kind))
        for i in range(len(cut))
    )
    return CategoriesOverTime(
        kind=kind,
        periods=tuple(cut),
        categories=tuple(
            CategorySeries(n.category_id, n.parent_id, n.own, n.total, n.own_sum, n.total_sum) for n in nodes
        ),
        slices=tuple(n.category_id for n in chosen),
        other=other,
        totals=tuple(facts.klass(kind, {b}) for b in buckets),
        sum=total,
    )


def _account_lines(
    conn: Connection, flt: LedgerFilter, step: Step, kind: str
) -> dict[tuple[date, int], Line]:
    """The kind's entries by (period bucket, own account), currencies added.

    income / expense: the flows the category mode counts for the kind (`CLASS_OF`); transfer_in /
    transfer_out: the transfer legs of amount above / below zero, paired or not.
    """
    parts = compose(flt)
    base = func.base_value(le.c.amount, le.c.currency, le.c.booked_on)
    if kind in ("income", "expense"):
        kept: tuple[ColumnElement[bool], ...] = (
            or_(le.c.type.is_(None), le.c.type.in_(("flow", "reconciliation"))),
            CLASS_OF == kind,
        )
    else:
        kept = (le.c.type == "transfer", le.c.amount > 0 if kind == "transfer_in" else le.c.amount < 0)
    entries = (
        select(
            cast(func.date_trunc(literal(step), cast(le.c.booked_on, DateTime)), Date).label("bucket"),
            le.c.account_id.label("account_id"),
            le.c.currency.label("currency"),
            le.c.amount.label("amount"),
            base.label("base"),
        )
        .select_from(parts.source.outerjoin(rcat, rcat.c.id == le.c.category_id))
        .where(*parts.where, *kept)
        # valued once per entry: the planner may not inline the conversion into each aggregate below
        .cte("entries")
        .prefix_with("MATERIALIZED")
    )
    stmt = select(
        entries.c.bucket,
        entries.c.account_id,
        entries.c.currency,
        func.count().label("n"),
        func.count().filter(entries.c.base.is_(None)).label("n_unvalued"),
        func.coalesce(func.sum(entries.c.base), 0).label("base_sum"),
        func.coalesce(func.sum(entries.c.amount).filter(entries.c.base.is_(None)), 0).label("unvalued_sum"),
    ).group_by(entries.c.bucket, entries.c.account_id, entries.c.currency)
    grouped: dict[tuple[date, int], list[Line]] = {}
    for r in conn.execute(stmt):
        grouped.setdefault((r.bucket, int(r.account_id)), []).append(
            line_of_group(str(r.currency), int(r.n), int(r.n_unvalued), int(r.base_sum), int(r.unvalued_sum))
        )
    return {key: add(lines) for key, lines in grouped.items()}


def accounts_over_time(conn: Connection, flt: LedgerFilter, step: Step, kind: str) -> AccountsOverTime:
    """Each account's amount of `kind` per period, with slices and "other" as the category mode has them."""
    assert flt.date_from is not None and flt.date_to is not None
    assert kind in ACCOUNT_KINDS
    cut = periods(flt.date_from, flt.date_to, step)
    buckets = [p.bucket for p in cut]
    cells = _account_lines(conn, flt, step, kind)
    series = [
        AccountOverTime(a, (lines := tuple(cells.get((b, a), EMPTY) for b in buckets)), add(lines))
        for a in {a for _, a in cells}
    ]
    series.sort(key=lambda s: (-abs(s.sum.total or 0), -s.sum.count, s.account_id))
    sign = KIND_SIGN[kind]
    slices = [s for s in series if s.sum.total is not None and s.sum.total * sign > 0][:TOP_SLICES]
    rest = [s for s in series if s not in slices and not opposes(s.sum, kind)]
    totals = tuple(add(s.total[i] for s in series) for i in range(len(cut)))
    kind_of = {int(r.id): str(r.kind) for r in conn.execute(text("SELECT id, kind FROM account"))}
    groups = tuple(
        AccountKindOverTime(
            k, tuple(add(s.total[i] for s in mine) for i in range(len(cut))), add(s.sum for s in mine)
        )
        for k in KIND_ORDER
        if (mine := [s for s in series if kind_of[s.account_id] == k])
    )
    return AccountsOverTime(
        kind=kind,
        periods=tuple(cut),
        accounts=tuple(series),
        account_kinds=groups,
        slices=tuple(s.account_id for s in slices),
        # a period in which a remaining account nets to the other sign leaves it out of the bar
        other=tuple(add(s.total[i] for s in rest if not opposes(s.total[i], kind)) for i in range(len(cut))),
        totals=totals,
        sum=add(totals),
    )
