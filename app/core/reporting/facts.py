"""The filtered entries of a report, summed (architecture §4.1, §5.1; spec §8, I26, I27).

One statement. Its entries are selected by `app.core.ledger.compose`, the predicate of the ledger
list, so the entries behind a figure are exactly the entries its drill-down lists. Each entry is
valued once, at its own `booked_on` rate, by `base_value()` (nothing outside this package calls it),
and the aggregate is grouped by period, class and category. Review state never excludes an entry (I26).

The classes (spec §8) are told apart by the entry alone:
  income / expense   flows in a category of that kind
  unclassified_out / unclassified_in
                     flows without a category and entries with no type yet, by sign (the entries the
                     ledger's `uncategorised` filter selects)
  reconciliation     reconciliations
Transfers and the other derived entries are in none of them.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import Connection, Date, DateTime, case, cast, column, func, literal, or_, select, table
from sqlalchemy.sql.elements import ColumnElement

from app.core.ledger import LedgerFilter, compose
from app.core.ledger.sql import le
from app.core.reporting.line import Line, add, line_of_group
from app.core.reporting.periods import Step

CLASSES = ("income", "expense", "unclassified_out", "unclassified_in", "reconciliation")
KIND_SIGN = {"expense": -1, "income": 1}  # the sign a category of the kind normally has

_cat = table("category", column("id"), column("kind")).alias("rcat")

Key = tuple[date | None, str, int | None]  # (period bucket or None, class, category id or None)


@dataclass(frozen=True)
class Facts:
    """The grouped answer: one Line per (period bucket, class, category), currencies already added."""

    cells: dict[Key, Line] = field(default_factory=dict)

    def klass(self, cls: str, buckets: Collection[date | None] | None = None) -> Line:
        """The Line of a class, over every category, over `buckets` (None: all of them)."""
        return add(
            line for (b, c, _), line in self.cells.items() if c == cls and (buckets is None or b in buckets)
        )

    def own_lines(self) -> dict[tuple[date | None, int], Line]:
        """The entries booked directly to a category, by (bucket, category id): the `own` Lines."""
        return {
            (b, cat): line for (b, c, cat), line in self.cells.items() if cat is not None and c in KIND_SIGN
        }


def entry_filter(
    start: date | None,
    end: date | None,
    account_ids: Iterable[int] = (),
    tag_ids: Iterable[int] = (),
) -> LedgerFilter:
    """The ledger filter a report reads through: the dimensions every report takes (several values of
    one dimension are alternatives). Raises `InvalidFilter` for a reversed range or a bad id."""
    return LedgerFilter(date_from=start, date_to=end, account_ids=tuple(account_ids), tag_ids=tuple(tag_ids))


def count_matching(conn: Connection, flt: LedgerFilter) -> int:
    """How many entries the ledger list would count for `flt` (its own predicate, nothing else)."""
    parts = compose(flt)
    return int(conn.execute(select(func.count()).select_from(parts.source).where(*parts.where)).scalar_one())


def fetch(conn: Connection, flt: LedgerFilter, step: Step | None = None) -> Facts:
    """Sum the entries `flt` selects by class and category, per calendar bucket when `step` is given."""
    parts = compose(flt)
    base = func.base_value(le.c.amount, le.c.currency, le.c.booked_on)
    bucket: ColumnElement[Any] = (
        cast(func.date_trunc(literal(step), cast(le.c.booked_on, DateTime)), Date)
        if step is not None
        else cast(literal(None), Date)
    )
    klass = case(
        (le.c.type == "reconciliation", "reconciliation"),
        (
            le.c.category_id.is_(None),
            case((le.c.amount < 0, "unclassified_out"), else_="unclassified_in"),
        ),
        (_cat.c.kind == "income", "income"),
        else_="expense",
    )
    entries = (
        select(
            bucket.label("bucket"),
            klass.label("klass"),
            le.c.category_id.label("category_id"),
            le.c.currency.label("currency"),
            le.c.amount.label("amount"),
            base.label("base"),
        )
        .select_from(parts.source.outerjoin(_cat, _cat.c.id == le.c.category_id))
        .where(*parts.where, or_(le.c.type.is_(None), le.c.type.in_(("flow", "reconciliation"))))
        # valued once per entry: the planner may not inline the conversion into each aggregate below
        .cte("entries")
        .prefix_with("MATERIALIZED")
    )
    stmt = select(
        entries.c.bucket,
        entries.c.klass,
        entries.c.category_id,
        entries.c.currency,
        func.count().label("n"),
        func.count().filter(entries.c.base.is_(None)).label("n_unvalued"),
        func.coalesce(func.sum(entries.c.base), 0).label("base_sum"),
        func.coalesce(func.sum(entries.c.amount).filter(entries.c.base.is_(None)), 0).label("unvalued_sum"),
    ).group_by(entries.c.bucket, entries.c.klass, entries.c.category_id, entries.c.currency)

    grouped: dict[Key, list[Line]] = {}
    for r in conn.execute(stmt):
        key: Key = (r.bucket, str(r.klass), None if r.category_id is None else int(r.category_id))
        grouped.setdefault(key, []).append(
            line_of_group(str(r.currency), int(r.n), int(r.n_unvalued), int(r.base_sum), int(r.unvalued_sum))
        )
    return Facts({key: add(lines) for key, lines in grouped.items()})
