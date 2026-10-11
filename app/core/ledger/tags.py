"""Tags (spec §3.7, architecture §4.1): CRUD, tagging one entry, and tagging a filter's result.

Every write is ONE transaction that takes the settle lock shared (inside `retry_on_deadlock`),
commits, and only then settles; a settling failure is the `error` of the returned `SettleResult`,
never raised into the committed write. Tags are not part of review and bump no `ledger_entry.version`
(schema comment above `ledger_entry_tag`), which is why tagging takes no account lock and no version
check. A derived entry (one with a `balance_record_id`) takes no tags (I13).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from types import EllipsisType
from typing import Any

from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

from app.core.ledger.entries import tag_ids_of
from app.core.settle.settle import SettleResult, settle
from app.utils.db.errors import constraint_name
from app.utils.db.locks import lock_settle_shared, retry_on_deadlock

MAX_NAME = 200


class TagError(Exception):
    """A tag operation was refused; the message states the rule. Nothing was written."""


class TagMissing(TagError):
    def __init__(self, tag_id: int) -> None:
        self.tag_id = tag_id
        super().__init__(f"tag {tag_id} does not exist")


class EntryMissing(TagError):
    def __init__(self, entry_id: int) -> None:
        self.entry_id = entry_id
        super().__init__(f"entry {entry_id} does not exist")


class DuplicateTagName(TagError):
    def __init__(self) -> None:
        super().__init__("another tag already has this name (names are compared case-insensitively)")


class InvalidTagValue(TagError):
    """`parameter` names the body field at fault."""

    def __init__(self, parameter: str, message: str) -> None:
        self.parameter = parameter
        super().__init__(message)


class DerivedEntryRefused(TagError):
    def __init__(self, entry_id: int) -> None:
        self.entry_id = entry_id
        super().__init__(f"entry {entry_id} is derived from a balance record and takes no tags")


class EmptyFilter(TagError):
    def __init__(self) -> None:
        super().__init__("the filter selects the whole ledger; set `all` to tag every entry on purpose")


class FilterResultChanged(TagError):
    def __init__(self, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"the filter now tags {actual} entries, not the {expected} that were previewed")


@dataclass(frozen=True)
class TagView:
    id: int
    name: str
    color: str | None
    starts_on: date | None  # min booked_on over the tagged entries
    ends_on: date | None
    entry_count: int


@dataclass(frozen=True)
class TagWritten:
    tag: TagView
    settle: SettleResult


@dataclass(frozen=True)
class TagDeleted:
    removed_memberships: int
    settle: SettleResult


@dataclass(frozen=True)
class EntryTagged:
    entry_id: int
    tag_ids: tuple[int, ...]  # sorted, as the entry now stands
    changed: bool
    settle: SettleResult


@dataclass(frozen=True)
class Span:
    starts_on: date | None
    ends_on: date | None
    entry_count: int


@dataclass(frozen=True)
class ApplyResult:
    selected: int  # entries the filter matches
    newly_tagged: int
    already_tagged: int
    skipped_derived: int
    per_account: dict[int, int] = field(default_factory=dict)  # account id -> newly tagged
    span_before: Span = Span(None, None, 0)
    span_after: Span = Span(None, None, 0)
    entries: tuple[tuple[int, tuple[int, ...]], ...] = ()  # (id, tag_ids) of the newly tagged; real run only
    settle: SettleResult | None = None  # None on a dry run


_VIEW = (
    "SELECT t.id, t.name, t.color, s.starts_on, s.ends_on, COALESCE(s.entry_count, 0) AS entry_count"
    " FROM tag t LEFT JOIN v_tag_span s ON s.tag_id = t.id"
)


def _view(row: Any) -> TagView:
    return TagView(row.id, row.name, row.color, row.starts_on, row.ends_on, int(row.entry_count))


def list_tags(conn: Connection) -> list[TagView]:
    """Every tag by name, with its derived span; an unused tag has no span and a count of 0."""
    return [_view(r) for r in conn.execute(text(_VIEW + " ORDER BY lower(t.name), t.name, t.id"))]


def _tag_view(conn: Connection, tag_id: int) -> TagView:
    row = conn.execute(text(_VIEW + " WHERE t.id = :i"), {"i": tag_id}).one_or_none()
    if row is None:
        raise TagMissing(tag_id)
    return _view(row)


def _clean_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise InvalidTagValue("name", "name must not be blank")
    if len(cleaned) > MAX_NAME:
        raise InvalidTagValue("name", f"name must be at most {MAX_NAME} characters")
    return cleaned


def _clean_color(color: str | None) -> str | None:
    if color is not None and not color.strip():
        raise InvalidTagValue("color", "color must not be blank (use null for none)")
    return color


def _duplicate(exc: DBAPIError) -> bool:
    return constraint_name(exc) == "ux_tag_name"


def create_tag(engine: Engine, *, name: str, color: str | None = None) -> TagWritten:
    cleaned, color = _clean_name(name), _clean_color(color)

    def run() -> TagView:
        with engine.begin() as conn:
            lock_settle_shared(conn)
            try:
                tag_id = conn.execute(
                    text("INSERT INTO tag (name, color) VALUES (:n, :c) RETURNING id"),
                    {"n": cleaned, "c": color},
                ).scalar_one()
            except DBAPIError as exc:
                if _duplicate(exc):
                    raise DuplicateTagName() from exc
                raise
            return _tag_view(conn, int(tag_id))

    return TagWritten(retry_on_deadlock(run), settle(engine))


def update_tag(
    engine: Engine,
    tag_id: int,
    *,
    name: str | EllipsisType = ...,
    color: str | None | EllipsisType = ...,
) -> TagWritten:
    """Rename and/or recolour; `...` leaves a field alone, `color=None` clears it."""
    sets: dict[str, Any] = {}
    if not isinstance(name, EllipsisType):
        sets["name"] = _clean_name(name)
    if not isinstance(color, EllipsisType):
        sets["color"] = _clean_color(color)

    def run() -> TagView:
        with engine.begin() as conn:
            lock_settle_shared(conn)
            if sets:
                assignments = ", ".join(f"{col} = :{col}" for col in sets)  # columns are fixed above
                try:
                    found = conn.execute(
                        text(f"UPDATE tag SET {assignments} WHERE id = :id RETURNING id"),  # noqa: S608
                        {**sets, "id": tag_id},
                    ).one_or_none()
                except DBAPIError as exc:
                    if _duplicate(exc):
                        raise DuplicateTagName() from exc
                    raise
                if found is None:
                    raise TagMissing(tag_id)
            return _tag_view(conn, tag_id)

    return TagWritten(retry_on_deadlock(run), settle(engine))


def delete_tag(engine: Engine, tag_id: int) -> TagDeleted:
    """Delete the tag; its memberships go with it (cascade) and are counted."""

    def run() -> int:
        with engine.begin() as conn:
            lock_settle_shared(conn)
            if (
                conn.execute(text("SELECT 1 FROM tag WHERE id = :i FOR UPDATE"), {"i": tag_id}).first()
                is None
            ):
                raise TagMissing(tag_id)
            removed = conn.execute(
                text("SELECT count(*) FROM ledger_entry_tag WHERE tag_id = :i"), {"i": tag_id}
            ).scalar_one()
            conn.execute(text("DELETE FROM tag WHERE id = :i"), {"i": tag_id})
            return int(removed)

    return TagDeleted(retry_on_deadlock(run), settle(engine))


def _check_taggable(conn: Connection, entry_id: int, tag_id: int) -> None:
    entry = conn.execute(
        text("SELECT balance_record_id FROM ledger_entry WHERE id = :i FOR KEY SHARE"), {"i": entry_id}
    ).one_or_none()
    if entry is None:
        raise EntryMissing(entry_id)
    if conn.execute(text("SELECT 1 FROM tag WHERE id = :i FOR KEY SHARE"), {"i": tag_id}).first() is None:
        raise TagMissing(tag_id)
    if entry.balance_record_id is not None:
        raise DerivedEntryRefused(entry_id)


def tag_entry(engine: Engine, entry_id: int, tag_id: int) -> EntryTagged:
    """Put `tag_id` on the entry. Idempotent: `changed` is False when it was already there."""

    def run() -> tuple[bool, tuple[int, ...]]:
        with engine.begin() as conn:
            lock_settle_shared(conn)
            _check_taggable(conn, entry_id, tag_id)
            inserted = conn.execute(
                text(
                    "INSERT INTO ledger_entry_tag (ledger_entry_id, tag_id) VALUES (:e, :t)"
                    " ON CONFLICT DO NOTHING"
                ),
                {"e": entry_id, "t": tag_id},
            ).rowcount
            return inserted > 0, tag_ids_of(conn, [entry_id]).get(entry_id, ())

    changed, tag_ids = retry_on_deadlock(run)
    return EntryTagged(entry_id, tag_ids, changed, settle(engine))


def untag_entry(engine: Engine, entry_id: int, tag_id: int) -> EntryTagged:
    """Take `tag_id` off the entry. Idempotent: `changed` is False when it was not there."""

    def run() -> tuple[bool, tuple[int, ...]]:
        with engine.begin() as conn:
            lock_settle_shared(conn)
            _check_taggable(conn, entry_id, tag_id)
            removed = conn.execute(
                text("DELETE FROM ledger_entry_tag WHERE ledger_entry_id = :e AND tag_id = :t"),
                {"e": entry_id, "t": tag_id},
            ).rowcount
            return removed > 0, tag_ids_of(conn, [entry_id]).get(entry_id, ())

    changed, tag_ids = retry_on_deadlock(run)
    return EntryTagged(entry_id, tag_ids, changed, settle(engine))
