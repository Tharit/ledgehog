"""Category writes (spec §3.5, architecture §4.1 'Management writes'): create, update, delete, merge.

Every write is ONE transaction: settle lock shared, then the category rows locked in ascending id
(structural writes lock the whole table: it is small, and a tree-shape decision reads all of it);
it commits, and only then settles (a settling failure is the `error` of the result, never raised
into the committed write). Delete and merge are previewed: `dry_run` runs the same code and rolls
it back. A merge repoints entries under the settling flag, so no `ledger_entry.version` moves
(D200), and derives nothing again (I18).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import EllipsisType
from typing import Any

import psycopg.errors
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

from app.core.ledger.dimensions import (
    DimensionError,
    DuplicateName,
    InvalidValue,
    check_count,
    clean_name,
    clean_presentation,
    previewable,
    require_count,
)
from app.core.ledger.lookups import CategoryRow, get_category
from app.core.settle.settle import SettleResult, settle
from app.core.stale import StaleReference
from app.utils.db.errors import constraint_name
from app.utils.db.locks import lock_rows, lock_settle_shared, retry_on_deadlock

KINDS = ("income", "expense")


class CategoryMissing(DimensionError):
    def __init__(self, category_id: int) -> None:
        self.category_id = category_id
        super().__init__(f"category {category_id} does not exist")


class CategoryCycle(DimensionError):
    def __init__(self, category_id: int, parent_id: int) -> None:
        super().__init__(
            f"category {category_id} cannot move under {parent_id}: that is itself or one of its descendants"
        )


class CategoryInUse(DimensionError):
    """Delete refused: entries, rules or children still reference it; merge it instead."""

    def __init__(self, category_id: int, held: dict[str, int]) -> None:
        self.held = held
        what = ", ".join(f"{n} {name}" for name, n in held.items())
        super().__init__(f"category {category_id} holds {what} and cannot be deleted: merge it instead")


class MergeRefused(DimensionError):
    """The merge would put a category under its own descendant (the only reason, for now)."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


@dataclass(frozen=True)
class CategoryWritten:
    category: CategoryRow
    settle: SettleResult


@dataclass(frozen=True)
class CategoryDeleteResult:
    category: CategoryRow
    held: dict[str, int]  # entries / rules / children that stop a delete; only non-zero keys
    deleted: bool
    settle: SettleResult | None  # None on a dry run


@dataclass(frozen=True)
class MergedPair:
    source_id: int
    source_name: str
    target_id: int
    target_name: str
    entries: int  # repointed from source to target
    rules: int


@dataclass(frozen=True)
class MovedChild:
    id: int
    name: str
    from_id: int
    to_id: int


@dataclass(frozen=True)
class CategoryMergeResult:
    source_id: int
    target_id: int
    pairs: tuple[MergedPair, ...]  # every merge, deepest first, the requested one last
    moved_children: tuple[MovedChild, ...]
    entry_count: int  # entries repointed in all: what `expected_count` confirms
    entry_ids: tuple[int, ...]  # real run only
    rule_ids: tuple[int, ...]
    settle: SettleResult | None = None  # None on a dry run


def _lock_all(conn: Connection) -> None:
    ids = conn.execute(text("SELECT id FROM category")).scalars().all()
    lock_rows(conn, "category", [int(i) for i in ids])


def _descendants(conn: Connection, category_id: int) -> set[int]:
    rows = conn.execute(
        text(
            "WITH RECURSIVE sub(id) AS (SELECT id FROM category WHERE parent_id = :i"
            " UNION SELECT c.id FROM category c JOIN sub ON c.parent_id = sub.id)"
            " SELECT id FROM sub"
        ),
        {"i": category_id},
    )
    return {int(i) for i in rows.scalars()}


def _duplicate(exc: DBAPIError) -> bool:
    return constraint_name(exc) == "ux_category_name"


def _kind_of(conn: Connection, category_id: int) -> str | None:
    row = conn.execute(text("SELECT kind FROM category WHERE id = :i"), {"i": category_id}).first()
    return None if row is None else str(row.kind)


def _view(conn: Connection, category_id: int) -> CategoryRow:
    found = get_category(conn, category_id)
    if found is None:
        raise CategoryMissing(category_id)
    return found


def create_category(
    engine: Engine,
    *,
    name: str,
    kind: str | None = None,
    parent_id: int | None = None,
    sort_order: int = 0,
    icon: str | None = None,
    color: str | None = None,
) -> CategoryWritten:
    """A top-level category takes `kind`; a child takes its parent's, and a disagreeing `kind` is refused."""
    cleaned = clean_name(name)
    icon, color = clean_presentation("icon", icon), clean_presentation("color", color)
    if parent_id is None and kind is None:
        raise InvalidValue("kind", "a top-level category needs a `kind`")
    if kind is not None and kind not in KINDS:
        raise InvalidValue("kind", "kind must be 'income' or 'expense'")

    def run() -> CategoryRow:
        with engine.begin() as conn:
            lock_settle_shared(conn)
            resolved = kind
            if parent_id is not None:
                lock_rows(conn, "category", [parent_id])
                parent_kind = _kind_of(conn, parent_id)
                if parent_kind is None:
                    raise StaleReference("parent_id", "category", parent_id)
                if kind is not None and kind != parent_kind:
                    raise InvalidValue("kind", f"a child takes its parent's kind ({parent_kind})")
                resolved = parent_kind
            try:
                new_id = conn.execute(
                    text(
                        "INSERT INTO category (name, kind, parent_id, sort_order, icon, color)"
                        " VALUES (:n, :k, :p, :s, :i, :c) RETURNING id"
                    ),
                    {"n": cleaned, "k": resolved, "p": parent_id, "s": sort_order, "i": icon, "c": color},
                ).scalar_one()
            except DBAPIError as exc:
                if _duplicate(exc):
                    raise DuplicateName("category") from exc
                raise
            return _view(conn, int(new_id))

    return CategoryWritten(retry_on_deadlock(run), settle(engine))


def update_category(
    engine: Engine,
    category_id: int,
    *,
    name: str | EllipsisType = ...,
    parent_id: int | None | EllipsisType = ...,
    sort_order: int | EllipsisType = ...,
    icon: str | None | EllipsisType = ...,
    color: str | None | EllipsisType = ...,
) -> CategoryWritten:
    """Change what is given (`...` leaves a field alone; `None` clears `icon`/`color`, or makes it top-level).

    The kind never changes; a new parent must be of the category's kind and never itself or one of
    its descendants.
    """
    sets: dict[str, Any] = {}
    if not isinstance(name, EllipsisType):
        sets["name"] = clean_name(name)
    if not isinstance(sort_order, EllipsisType):
        sets["sort_order"] = sort_order
    if not isinstance(icon, EllipsisType):
        sets["icon"] = clean_presentation("icon", icon)
    if not isinstance(color, EllipsisType):
        sets["color"] = clean_presentation("color", color)
    reparent = not isinstance(parent_id, EllipsisType)
    if not isinstance(parent_id, EllipsisType):
        sets["parent_id"] = parent_id

    def run() -> CategoryRow:
        with engine.begin() as conn:
            lock_settle_shared(conn)
            if reparent:
                _lock_all(conn)
            else:
                lock_rows(conn, "category", [category_id])
            kind = _kind_of(conn, category_id)
            if kind is None:
                raise CategoryMissing(category_id)
            new_parent = sets.get("parent_id")
            if new_parent is not None:
                parent_kind = _kind_of(conn, new_parent)
                if parent_kind is None:
                    raise StaleReference("parent_id", "category", new_parent)
                if new_parent == category_id or new_parent in _descendants(conn, category_id):
                    raise CategoryCycle(category_id, new_parent)
                if parent_kind != kind:
                    raise InvalidValue("parent_id", f"the parent must be of the category's kind ({kind})")
            if sets:
                assignments = ", ".join(f"{col} = :{col}" for col in sets)  # columns are fixed above
                try:
                    conn.execute(
                        text(f"UPDATE category SET {assignments} WHERE id = :id"),  # noqa: S608
                        {**sets, "id": category_id},
                    )
                except DBAPIError as exc:
                    if _duplicate(exc):
                        raise DuplicateName("category") from exc
                    if isinstance(exc.orig, psycopg.errors.RaiseException) and "cycle" in str(exc.orig):
                        raise CategoryCycle(category_id, int(new_parent or 0)) from exc
                    raise
            return _view(conn, category_id)

    return CategoryWritten(retry_on_deadlock(run), settle(engine))


def _held(conn: Connection, category_id: int) -> dict[str, int]:
    counts = {
        label: int(conn.execute(text(sql), {"i": category_id}).scalar_one())
        for label, sql in (
            ("entries", "SELECT count(*) FROM ledger_entry WHERE category_id = :i"),
            ("rules", "SELECT count(*) FROM rule WHERE category_id = :i"),
            ("children", "SELECT count(*) FROM category WHERE parent_id = :i"),
        )
    }
    return {k: n for k, n in counts.items() if n}


class _Backstop(Exception):
    """The RESTRICT foreign keys refused a delete the pre-check let through (a concurrent write)."""


def delete_category(engine: Engine, category_id: int, *, dry_run: bool = False) -> CategoryDeleteResult:
    """Delete a category nothing references and that has no children; otherwise it is merged.

    `dry_run` answers what would stand in the way (`held`) and writes nothing. A real delete that
    finds something is `CategoryInUse`.
    """

    def work(conn: Connection) -> CategoryDeleteResult:
        lock_rows(conn, "category", [category_id])
        row = _view(conn, category_id)
        held = _held(conn, category_id)
        if dry_run:
            return CategoryDeleteResult(row, held, False, None)
        if held:
            raise CategoryInUse(category_id, held)
        try:
            with conn.begin_nested():
                conn.execute(text("DELETE FROM category WHERE id = :i"), {"i": category_id})
        except DBAPIError as exc:
            if isinstance(exc.orig, psycopg.errors.ForeignKeyViolation | psycopg.errors.RestrictViolation):
                raise _Backstop from exc
            raise
        return CategoryDeleteResult(row, {}, True, None)

    try:
        result = retry_on_deadlock(lambda: previewable(engine, dry_run, work))
    except _Backstop:
        with engine.connect() as conn:
            raise CategoryInUse(category_id, _held(conn, category_id)) from None
    return result if dry_run else replace(result, settle=settle(engine))


def _merge_into(
    conn: Connection,
    source: int,
    target: int,
    pairs: list[MergedPair],
    moved: list[MovedChild],
    entry_ids: list[int],
    rule_ids: list[int],
) -> None:
    """Merge `source` into `target` (same kind; `target` not below `source`), post-order.

    The children of `source` whose name `target`'s children already use (the source itself is not
    among them) are merged into those first, deepest first; the others move under `target`; then
    entries and rules are repointed and `source` is deleted last. `ux_category_name` is checked row
    by row, which this order satisfies.
    """
    names = {
        int(r.id): str(r.name)
        for r in conn.execute(
            text("SELECT id, name FROM category WHERE id IN (:s, :t)"), {"s": source, "t": target}
        )
    }
    collisions = conn.execute(
        text(
            "SELECT c.id AS child, d.id AS dest FROM category c JOIN category d"
            "  ON d.parent_id = :t AND d.id <> :s AND lower(d.name) = lower(c.name)"
            " WHERE c.parent_id = :s ORDER BY c.id"
        ),
        {"s": source, "t": target},
    ).all()
    for row in collisions:
        _merge_into(conn, int(row.child), int(row.dest), pairs, moved, entry_ids, rule_ids)
    remaining = conn.execute(
        text("SELECT id, name FROM category WHERE parent_id = :s ORDER BY id"), {"s": source}
    ).all()
    if remaining:
        if conn.execute(
            text("SELECT 1 FROM category WHERE id = :s AND parent_id = :t"), {"s": source, "t": target}
        ).first():
            # the source still sits among the target's children: a moving child named like it would
            # collide with it for the moment; it is deleted below, so only its name steps aside
            conn.execute(
                text("UPDATE category SET name = '~merging ' || id::text WHERE id = :s"), {"s": source}
            )
        conn.execute(
            text("UPDATE category SET parent_id = :t WHERE parent_id = :s"), {"s": source, "t": target}
        )
        moved.extend(MovedChild(int(r.id), str(r.name), source, target) for r in remaining)
    moved_entries = [
        int(i)
        for i in conn.execute(
            text("UPDATE ledger_entry SET category_id = :t WHERE category_id = :s RETURNING id"),
            {"s": source, "t": target},
        ).scalars()
    ]
    moved_rules = [
        int(i)
        for i in conn.execute(
            text("UPDATE rule SET category_id = :t WHERE category_id = :s RETURNING id"),
            {"s": source, "t": target},
        ).scalars()
    ]
    conn.execute(text("DELETE FROM category WHERE id = :s"), {"s": source})
    entry_ids.extend(moved_entries)
    rule_ids.extend(moved_rules)
    pairs.append(
        MergedPair(source, names[source], target, names[target], len(moved_entries), len(moved_rules))
    )


def merge_category(
    engine: Engine, source_id: int, target_id: int, *, dry_run: bool, expected_count: int | None
) -> CategoryMergeResult:
    """Merge `source_id` into `target_id` (spec §3.5); `dry_run` reports and writes nothing.

    Refused: the same category, another kind, or a target below the source; a target above it is
    fine. Entries and rules are repointed under the settling flag (no version moves, nothing is
    derived again, keys stay). The real run carries the dry run's `entry_count`; another number
    writes nothing (`MergeCountChanged`).
    """
    require_count(dry_run, expected_count)

    def work(conn: Connection) -> CategoryMergeResult:
        _lock_all(conn)
        source_kind = _kind_of(conn, source_id)
        if source_kind is None:
            raise CategoryMissing(source_id)
        target_kind = _kind_of(conn, target_id)
        if target_kind is None:
            raise StaleReference("into", "category", target_id)
        if source_id == target_id:
            raise InvalidValue("into", "a category cannot be merged into itself")
        if source_kind != target_kind:
            raise InvalidValue("into", f"a {source_kind} category cannot be merged into a {target_kind} one")
        if target_id in _descendants(conn, source_id):
            raise MergeRefused(
                "into_descendant",
                "a category cannot be merged into one of its own descendants: merge the descendants "
                "upwards instead",
            )
        conn.execute(text("SELECT set_config('ledger.settling', 'on', true)"))  # no version bumps (D200)
        pairs: list[MergedPair] = []
        moved: list[MovedChild] = []
        entry_ids: list[int] = []
        rule_ids: list[int] = []
        _merge_into(conn, source_id, target_id, pairs, moved, entry_ids, rule_ids)
        check_count(dry_run, expected_count, len(entry_ids))
        return CategoryMergeResult(
            source_id=source_id,
            target_id=target_id,
            pairs=tuple(pairs),
            moved_children=tuple(moved),
            entry_count=len(entry_ids),
            entry_ids=() if dry_run else tuple(sorted(entry_ids)),
            rule_ids=tuple(sorted(rule_ids)),
        )

    result = retry_on_deadlock(lambda: previewable(engine, dry_run, work))
    return result if dry_run else replace(result, settle=settle(engine))
