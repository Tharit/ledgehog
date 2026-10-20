"""Savings, and the range cut into periods (spec §8, architecture §4.1).

`savings_in` is THE savings computation: the Overview's cards and the over-time report both call it,
over the buckets they want, so their figures cannot disagree. A range's savings and rate are those of
its whole span (the sum of its periods' Lines), never a mean of periods' rates.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Connection

from app.core.ledger import LedgerFilter
from app.core.reporting.facts import Facts, fetch
from app.core.reporting.line import Line, Savings, add, savings_of
from app.core.reporting.periods import Period, Step, periods
from app.core.reporting.tree import category_tree, opposes, pick_slices

TOP_SLICES = 6


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
            CategorySeries(n.category_id, n.parent_id, n.own, n.total, n.total_sum) for n in nodes
        ),
        slices=tuple(n.category_id for n in chosen),
        other=other,
        totals=tuple(facts.klass(kind, {b}) for b in buckets),
        sum=total,
    )
