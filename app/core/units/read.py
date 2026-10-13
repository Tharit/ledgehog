"""Reading units as stored (spec §6, §8): one unit, and the review queue.

The membership of the queue is the unit CTE of `core/resolution/confirmed.py` (set-based: no query per
unit); the per-unit reasons come from the pure `unit_state`, over the rows of the page only. The two agree
by `tests/core/units/test_equivalence.py`. Reads only: no lock, no write, no settle.

The queue has three sections: `pending_review` (every unit that is not confirmed, until the matcher and
pairing steps split the others off), `needs_account` and `waiting` (empty until step 8). Each is ordered by
the date of the unit's anchor entry (its lowest id), then the anchor id: a total order, so a keyset
cursor `(booked_on, anchor)` stays valid when units come and go while the client pages.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy import Connection, text

from app.core.ledger.entries import EntryRow, entries_by_ids
from app.core.resolution.confirmed import STANDING, units_sql
from app.core.units.closure import UnitEntry
from app.core.units.lookup import unit_ids_of
from app.core.units.state import UnitState, unit_state

SectionKind = Literal["pending_review", "needs_account", "waiting"]
SECTIONS: tuple[SectionKind, ...] = ("pending_review", "needs_account", "waiting")
DEFAULT_LIMIT = 100
MAX_LIMIT = 500


class InvalidCursor(ValueError):
    """A cursor or snapshot token that this server did not issue."""

    def __init__(self, parameter: str) -> None:
        self.parameter = parameter
        super().__init__(f"{parameter} is not a token this server issued")


@dataclass(frozen=True)
class UnitView:
    anchor_entry_id: int  # the lowest entry id of the unit: what opens it
    unit_key: int
    state: UnitState
    entries: tuple[EntryRow, ...]  # ascending by id


@dataclass(frozen=True)
class QueueSection:
    kind: SectionKind
    total: int  # units in the section, whatever the page
    units: tuple[UnitView, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class ReviewQueue:
    sections: tuple[QueueSection, ...]
    total: int  # units in all sections
    snapshot: str  # opaque; hand it to `new_unit_count` later


def unit_entry_of(row: EntryRow) -> UnitEntry:
    return UnitEntry(
        id=row.id,
        source_transaction_id=row.source_transaction_id,
        type=row.type,
        category_id=row.category_id,
        counterpart_entry_id=row.counterpart_entry_id,
        derivation=row.derivation,
    )


def _view(unit_key: int, rows: Sequence[EntryRow]) -> UnitView:
    ordered = tuple(sorted(rows, key=lambda r: r.id))
    return UnitView(
        anchor_entry_id=ordered[0].id,
        unit_key=unit_key,
        state=unit_state([unit_entry_of(r) for r in ordered]),
        entries=ordered,
    )


def get_unit(conn: Connection, entry_id: int) -> UnitView | None:
    """The unit holding `entry_id`, as stored; None when there is no such entry or it is derived."""
    ids = unit_ids_of(conn, entry_id)
    if ids is None:
        return None
    return _view(ids.unit_key, entries_by_ids(conn, ids.entry_ids))


# ---- the queue ----------------------------------------------------------------------------------

_QUEUE_PAGE = text(
    f"""
    WITH units AS ({units_sql()}),
         q AS (SELECT u.unit_key, min(u.id) AS anchor FROM units AS u WHERE NOT u.unit_ok GROUP BY u.unit_key)
    SELECT t.unit_key, t.anchor, t.booked_on, t.total
      FROM (SELECT q.unit_key, q.anchor, e.booked_on, count(*) OVER () AS total
              FROM q JOIN ledger_entry AS e ON e.id = q.anchor) AS t
     WHERE (CAST(:after_on AS date) IS NULL
            OR (t.booked_on, t.anchor) > (CAST(:after_on AS date), CAST(:after_anchor AS bigint)))
     ORDER BY t.booked_on, t.anchor
     LIMIT :limit
    """
)

_QUEUE_TOTAL = text(
    f"""
    WITH units AS ({units_sql()})
    SELECT count(DISTINCT u.unit_key) FROM units AS u WHERE NOT u.unit_ok
    """
)

_NEW_UNITS = text(
    f"""
    WITH units AS ({units_sql()})
    SELECT count(*) FROM (SELECT u.unit_key FROM units AS u WHERE NOT u.unit_ok
                           GROUP BY u.unit_key HAVING min(u.id) > :since) AS n
    """
)

_ENTRIES_OF_UNITS = text(
    """
    SELECT e.id FROM ledger_entry AS e
     WHERE e.source_transaction_id = ANY(:keys)
        OR e.source_transaction_id IN (
              SELECT q.source_transaction_id
                FROM ledger_entry AS t
                JOIN ledger_entry AS q ON q.id = t.counterpart_entry_id
               WHERE t.source_transaction_id = ANY(:keys))
    """
)

_MAX_ENTRY_ID = text("SELECT COALESCE(max(id), 0) FROM ledger_entry")


def encode_cursor(booked_on: date, anchor: int) -> str:
    return base64.urlsafe_b64encode(f"c1:{booked_on.isoformat()}:{anchor}".encode()).decode().rstrip("=")


def decode_cursor(token: str) -> tuple[date, int]:
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
        tag, day, anchor = raw.split(":")
        if tag != "c1":
            raise ValueError(raw)
        return date.fromisoformat(day), int(anchor)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise InvalidCursor("cursor") from exc


def encode_snapshot(max_entry_id: int) -> str:
    return base64.urlsafe_b64encode(f"s1:{max_entry_id}".encode()).decode().rstrip("=")


def decode_snapshot(token: str) -> int:
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
        tag, value = raw.split(":")
        if tag != "s1":
            raise ValueError(raw)
        return int(value)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise InvalidCursor("since") from exc


def _pending_review(conn: Connection, *, limit: int, cursor: str | None) -> QueueSection:
    after_on, after_anchor = decode_cursor(cursor) if cursor else (None, 0)
    rows = conn.execute(
        _QUEUE_PAGE,
        {"standing": STANDING, "after_on": after_on, "after_anchor": after_anchor, "limit": limit + 1},
    ).all()
    if rows:
        total = int(rows[0].total)
    elif cursor:  # a cursor past the end: the page is empty, the section is not
        total = int(conn.execute(_QUEUE_TOTAL, {"standing": STANDING}).scalar_one())
    else:
        total = 0
    page, more = rows[:limit], len(rows) > limit
    units = _units_of_page(conn, [int(r.unit_key) for r in page])
    return QueueSection(
        kind="pending_review",
        total=total,
        units=units,
        next_cursor=encode_cursor(page[-1].booked_on, int(page[-1].anchor)) if more else None,
    )


def _units_of_page(conn: Connection, keys: list[int]) -> tuple[UnitView, ...]:
    if not keys:
        return ()
    ids = [int(i) for i in conn.execute(_ENTRIES_OF_UNITS, {"keys": keys}).scalars()]
    by_key: dict[int, list[EntryRow]] = {k: [] for k in keys}
    for row in entries_by_ids(conn, ids):
        if row.unit_key in by_key:
            by_key[row.unit_key].append(row)
    # the page order is the order of `keys` (the section's order), not of the anchors' ids
    return tuple(_view(k, by_key[k]) for k in keys)


def _empty(kind: SectionKind) -> QueueSection:
    """`needs_account` and `waiting` need pairing's notion of waiting (step 8): nothing is in them yet."""
    return QueueSection(kind=kind, total=0, units=(), next_cursor=None)


def review_queue(
    conn: Connection,
    *,
    limit: int = DEFAULT_LIMIT,
    section: SectionKind | None = None,
    cursor: str | None = None,
) -> ReviewQueue:
    """The first page of every section, or the page after `cursor` of one `section`.

    `snapshot` is read first, so a unit imported while the page is being built counts as new later.
    """
    snapshot = encode_snapshot(int(conn.execute(_MAX_ENTRY_ID).scalar_one()))
    wanted = SECTIONS if section is None else (section,)
    built = tuple(
        _pending_review(conn, limit=limit, cursor=cursor if section == kind else None)
        if kind == "pending_review"
        else _empty(kind)
        for kind in wanted
    )
    total = built[0].total if section in (None, "pending_review") else _pending_total(conn)
    return ReviewQueue(sections=built, total=total, snapshot=snapshot)


def _pending_total(conn: Connection) -> int:
    return int(conn.execute(_QUEUE_TOTAL, {"standing": STANDING}).scalar_one())


def new_unit_count(conn: Connection, since: str) -> tuple[int, str]:
    """Units in the queue now whose anchor entry was created after the snapshot `since`, and a fresh snapshot.

    An entry's id grows with creation, so "the anchor is newer than the snapshot" is a unit that arrived (an
    import, an entry form) rather than one that was already there and changed (a split, a reopened unit).
    One CTE pass; no per-unit work.
    """
    after = decode_snapshot(since)
    count = int(conn.execute(_NEW_UNITS, {"standing": STANDING, "since": after}).scalar_one())
    return count, encode_snapshot(int(conn.execute(_MAX_ENTRY_ID).scalar_one()))
