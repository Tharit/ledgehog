"""The category tree of a report (spec §3.5, §8): each category's own and total Lines per bucket.

A category's `own` Line is the entries booked to it; its `total` adds its descendants'. A category
with no entries in the range, itself or below, is not listed. The order is depth-first, siblings by
the magnitude of their total (spec §8: refunds net, so a total can be of either sign).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import Connection, text

from app.core.reporting.facts import KIND_SIGN, Facts
from app.core.reporting.line import EMPTY, Line, add


@dataclass(frozen=True)
class Node:
    category_id: int
    parent_id: int | None
    own: tuple[Line, ...]  # per bucket
    total: tuple[Line, ...]  # per bucket
    own_sum: Line  # over the buckets
    total_sum: Line


def _order(node: Node) -> tuple[int, int, int]:
    """Largest magnitude first (an unvalued total counts as 0), then the busier, then the older."""
    return (-abs(node.total_sum.total or 0), -node.total_sum.count, node.category_id)


def opposes(line: Line, kind: str) -> bool:
    """A net of the other sign than the kind's (refunds beyond purchases): never a slice or a bar."""
    return line.total is not None and line.total * KIND_SIGN[kind] < 0


def pick_slices(nodes: list[Node], kind: str, top: int) -> tuple[list[Node], list[Node]]:
    """The first `top` top-level categories with a net of the kind's sign, by magnitude, and the other
    top-level categories that belong to "Other" (those of the opposite sign belong to neither)."""
    roots = [n for n in nodes if n.parent_id is None]
    slices = [n for n in roots if n.total_sum.total is not None and n.total_sum.total * KIND_SIGN[kind] > 0]
    slices = slices[:top]
    rest = [n for n in roots if n not in slices and not opposes(n.total_sum, kind)]
    return slices, rest


def category_tree(
    conn: Connection, facts: Facts, kind: str, buckets: list[date | None]
) -> tuple[list[Node], Line]:
    """The nodes of `kind` in display order, and the kind's own total Line (every bucket, every node)."""
    rows = conn.execute(
        text("SELECT id, parent_id FROM category WHERE kind = :k ORDER BY id"), {"k": kind}
    ).all()
    children: dict[int | None, list[int]] = {}
    for r in rows:
        children.setdefault(None if r.parent_id is None else int(r.parent_id), []).append(int(r.id))
    parent = {int(r.id): (None if r.parent_id is None else int(r.parent_id)) for r in rows}
    own_lines = facts.own_lines()

    built: dict[int, Node] = {}

    def build(cid: int) -> Node | None:
        kids = [n for n in (build(k) for k in children.get(cid, [])) if n is not None]
        own = tuple(own_lines.get((b, cid), EMPTY) for b in buckets)
        total = tuple(add([own[i], *(k.total[i] for k in kids)]) for i in range(len(buckets)))
        total_sum = add(total)
        if total_sum.count == 0:
            return None
        node = Node(cid, parent[cid], own, total, add(own), total_sum)
        built[cid] = node
        return node

    roots = [n for n in (build(r) for r in children.get(None, [])) if n is not None]
    ordered: list[Node] = []

    def walk(nodes: list[Node]) -> None:
        for n in sorted(nodes, key=_order):
            ordered.append(n)
            walk([built[k] for k in children.get(n.category_id, []) if k in built])

    walk(roots)
    return ordered, add(n.total_sum for n in roots)
