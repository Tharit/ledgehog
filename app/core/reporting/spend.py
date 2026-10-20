"""Spend or income by category over a date range (spec §8, architecture §4.1).

The kind's flows grouped by category with refunds netting, as a flat tree (each node's own entries
and its total with its descendants), with the lines that stand beside it: unclassified money out and
in, reconciliations, and how many entries are not confirmed yet (I26: they count, with their
proposed categories). One request is one range; the Overview's top categories are this answer with
`top`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction

from sqlalchemy import Connection

from app.core.ledger import LedgerFilter
from app.core.reporting.facts import KIND_SIGN, count_matching, fetch
from app.core.reporting.line import Line, add
from app.core.reporting.tree import category_tree, pick_slices


@dataclass(frozen=True)
class CategoryRow:
    category_id: int
    parent_id: int | None
    own: Line
    total: Line
    share_bp: int | None  # total over the kind's total, in basis points; None for a net of the other sign


@dataclass(frozen=True)
class Slice:
    category_id: int
    total: Line


@dataclass(frozen=True)
class ByCategory:
    kind: str
    total: Line
    categories: tuple[CategoryRow, ...]  # depth-first, siblings by magnitude; only those with entries
    slices: tuple[Slice, ...] | None  # with `top`: the largest top-level categories of the kind's sign
    other: Line | None  # with `top`: the remaining ones, summed; None when there are none
    unclassified_out: Line
    unclassified_in: Line
    reconciliations: Line
    unconfirmed_count: int


def share_bp(node: Line, kind_total: Line, kind: str) -> int | None:
    sign = KIND_SIGN[kind]
    if node.total is None or kind_total.total is None or kind_total.total * sign <= 0:
        return None
    if node.total * sign < 0:
        return None
    return round(Fraction(node.total * 10_000, kind_total.total))


def by_category(conn: Connection, flt: LedgerFilter, kind: str, top: int | None = None) -> ByCategory:
    facts = fetch(conn, flt)
    nodes, total = category_tree(conn, facts, kind, [None])
    rows = tuple(
        CategoryRow(n.category_id, n.parent_id, n.own[0], n.total[0], share_bp(n.total[0], total, kind))
        for n in nodes
    )
    slices: tuple[Slice, ...] | None = None
    other: Line | None = None
    if top is not None:
        chosen, rest = pick_slices(nodes, kind, top)
        slices = tuple(Slice(n.category_id, n.total[0]) for n in chosen)
        other = add(n.total[0] for n in rest) if rest else None
    return ByCategory(
        kind=kind,
        total=total,
        categories=rows,
        slices=slices,
        other=other,
        unclassified_out=facts.klass("unclassified_out"),
        unclassified_in=facts.klass("unclassified_in"),
        reconciliations=facts.klass("reconciliation"),
        unconfirmed_count=count_matching(conn, replace(flt, flags=("unconfirmed",))),
    )
