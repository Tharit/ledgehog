"""Reading units as stored (spec §6, §8): one unit, and the review queue.

The membership of the queue is the unit CTE of `core/resolution/confirmed.py` (set-based: no query per
unit); the per-unit reasons come from the pure `unit_state`, over the rows of the page only. The two agree
by `tests/core/units/test_equivalence.py`. Reads only: no lock, no write, no settle.

The queue has three disjoint sections; a unit that is not confirmed is in exactly one (spec §5.7, §6):
`needs_account` when any of its entries is a leg that needs an account (an unpaired transfer leg with no
counter-account, an instructed currency, and no open account other than its own in that currency: the
currency rule of `core/resolution/accounts.py`, restated in SQL and covered by the section tests), else
`waiting` when any entry carries the `waiting` flag, else `pending_review`. Each is ordered by the date of
the unit's anchor entry (its lowest id), then the anchor id: a total order, so a keyset cursor
`(booked_on, anchor)` stays valid when units come and go while the client pages.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from sqlalchemy import Connection, Row, text

from app.core.ledger.entries import EntryRow, entries_by_ids
from app.core.resolution.confirmed import units_binds, units_sql
from app.core.units.closure import UnitEntry
from app.core.units.lookup import unit_ids_of
from app.core.units.state import UnitState, document_facts_of_flags, leg_states_of_flags, unit_state

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
class WaitingFor:
    account_id: int  # the counter-account of the first waiting leg
    synced_through: date | None  # how far that account has been fetched; None = never


@dataclass(frozen=True)
class WaitingForDocument:
    """The document variant of `WaitingFor` (documents.md §7): a unit waits for a document of `provider`."""

    provider: str
    # how far the sources still holding the transaction have covered: the earliest of them; None when one of
    # them has never run ("not synced yet")
    covered_through: date | None


@dataclass(frozen=True)
class UnitView:
    anchor_entry_id: int  # the lowest entry id of the unit: what opens it
    unit_key: int
    state: UnitState
    entries: tuple[EntryRow, ...]  # ascending by id
    needs_account: str | None = None  # queue only: the instructed currency a unit in `needs_account` needs
    waiting: WaitingFor | None = None  # queue only: what a unit in `waiting` waits for (a partner)...
    waiting_document: WaitingForDocument | None = None  # ... or a document


@dataclass(frozen=True)
class CurrencyGroup:
    currency: str
    count: int  # units in the section that need an account in it


@dataclass(frozen=True)
class QueueSection:
    kind: SectionKind
    total: int  # units in the section, whatever the page
    units: tuple[UnitView, ...]
    next_cursor: str | None
    groups: tuple[CurrencyGroup, ...] = ()  # `needs_account` only: per currency, over the whole section


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


def _view(
    unit_key: int,
    rows: Sequence[EntryRow],
    needs_account: str | None = None,
    waiting: WaitingFor | None = None,
    waiting_document: WaitingForDocument | None = None,
) -> UnitView:
    ordered = tuple(sorted(rows, key=lambda r: r.id))
    return UnitView(
        anchor_entry_id=ordered[0].id,
        unit_key=unit_key,
        state=unit_state(
            [unit_entry_of(r) for r in ordered],
            leg_states_of_flags({r.id: r.review_flags for r in ordered}),
            document_facts_of_flags([(r.id, r.review_flags) for r in ordered if r.type == "flow"]),
        ),
        entries=ordered,
        needs_account=needs_account,
        waiting=waiting,
        waiting_document=waiting_document,
    )


def get_unit(conn: Connection, entry_id: int) -> UnitView | None:
    """The unit holding `entry_id`, as stored; None when there is no such entry or it is derived."""
    ids = unit_ids_of(conn, entry_id)
    if ids is None:
        return None
    return _view(ids.unit_key, entries_by_ids(conn, ids.entry_ids))


# ---- the queue ----------------------------------------------------------------------------------

# The unclassified units, one row each, with their section. A leg NEEDS AN ACCOUNT (spec §5.7) when it is an
# unpaired transfer with no counter-account and an instructed currency (of its source), and no account other
# than its own, open on its booking date, is in that currency (`arrival_currency_ok`, `open_on_booking_date`).
# A leg is WAITING when it carries the flag `core/settle/flags.py` writes: for its partner (a transfer leg)
# or, on a flow, for its document (`doc_waiting`, documents.md §7).
_SECTIONED = """
    WITH units AS ({units}),
         legs AS (
            SELECT u.unit_key, u.id, le.booked_on, st.instructed_currency, le.counter_account_id,
                   (le.type = 'transfer' AND le.counterpart_entry_id IS NULL
                    AND le.counter_account_id IS NULL AND st.instructed_currency IS NOT NULL
                    AND NOT EXISTS (
                        SELECT 1 FROM account AS a
                         WHERE a.currency = st.instructed_currency AND a.id <> le.account_id
                           AND (a.closed_on IS NULL OR le.booked_on <= a.closed_on))) AS needs_account,
                   ('waiting' = ANY(le.review_flags)) AS waiting,
                   (le.type IS DISTINCT FROM 'transfer' AND 'waiting' = ANY(le.review_flags)) AS doc_waiting
              FROM units AS u JOIN ledger_entry AS le ON le.id = u.id
              JOIN source_transaction AS st ON st.id = le.source_transaction_id
             WHERE NOT u.unit_ok),
         q AS (
            SELECT l.unit_key, min(l.id) AS anchor,
                   CASE WHEN bool_or(l.needs_account) THEN 'needs_account'
                        WHEN bool_or(l.waiting) THEN 'waiting' ELSE 'pending_review' END AS section,
                   (array_agg(l.instructed_currency ORDER BY l.id) FILTER (WHERE l.needs_account))[1]
                       AS currency,
                   (array_agg(l.counter_account_id ORDER BY l.id)
                        FILTER (WHERE l.waiting AND NOT l.doc_waiting))[1] AS wait_account,
                   (array_agg(l.id ORDER BY l.id) FILTER (WHERE l.doc_waiting))[1] AS doc_entry
              FROM legs AS l GROUP BY l.unit_key)
"""

_SECTIONED_SQL = _SECTIONED.format(units=units_sql())

_QUEUE_PAGE = text(
    _SECTIONED_SQL
    + """
    SELECT p.unit_key, p.anchor, p.booked_on, p.total, p.currency, p.wait_account, cv.synced_through,
           dw.provider AS doc_provider, dw.covered_through AS doc_covered
      FROM (SELECT t.*
              FROM (SELECT q.unit_key, q.anchor, q.currency, q.wait_account, q.doc_entry, e.booked_on,
                           count(*) OVER () AS total
                      FROM q JOIN ledger_entry AS e ON e.id = q.anchor
                     WHERE q.section = :section) AS t
             WHERE (CAST(:after_on AS date) IS NULL
                    OR (t.booked_on, t.anchor) > (CAST(:after_on AS date), CAST(:after_anchor AS bigint)))
             ORDER BY t.booked_on, t.anchor
             LIMIT :limit) AS p
      LEFT JOIN v_account_coverage AS cv ON cv.account_id = p.wait_account
      LEFT JOIN LATERAL (
            SELECT pp.document_provider AS provider,
                   CASE WHEN bool_or(dc.covered_through IS NULL) THEN NULL
                        ELSE min(dc.covered_through) END AS covered_through
              FROM ledger_entry AS de
              JOIN payee AS pp ON pp.id = de.payee_id
              JOIN unnest(CAST(:doc_importers AS text[]), CAST(:doc_providers AS text[]))
                       AS r(importer, provider) ON r.provider = pp.document_provider
              JOIN importer_instance AS ii ON ii.importer = r.importer AND NOT ii.disabled
                   AND (ii.settings ->> 'start_date' IS NULL
                        OR CAST(ii.settings ->> 'start_date' AS date) <= de.booked_on)
              LEFT JOIN v_document_coverage AS dc ON dc.importer_instance_id = ii.id
             WHERE de.id = p.doc_entry
               AND (dc.covered_through IS NULL
                    OR dc.covered_through
                       < de.booked_on + current_setting('ledger.document_window_days')::int)
             GROUP BY pp.document_provider) AS dw ON p.doc_entry IS NOT NULL
     ORDER BY p.booked_on, p.anchor
    """
)

_SECTION_TOTAL = text(_SECTIONED_SQL + "SELECT count(*) FROM q WHERE q.section = :section")

_NEEDS_ACCOUNT_GROUPS = text(
    _SECTIONED_SQL
    + """
    SELECT q.currency, count(*) AS n FROM q WHERE q.section = 'needs_account'
     GROUP BY q.currency ORDER BY q.currency
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


def _section(conn: Connection, kind: SectionKind, *, limit: int, cursor: str | None) -> QueueSection:
    after_on, after_anchor = decode_cursor(cursor) if cursor else (None, 0)
    rows = conn.execute(
        _QUEUE_PAGE,
        {
            **units_binds(),
            "section": kind,
            "after_on": after_on,
            "after_anchor": after_anchor,
            "limit": limit + 1,
        },
    ).all()
    if rows:
        total = int(rows[0].total)
    elif cursor:  # a cursor past the end: the page is empty, the section is not
        total = _section_total(conn, kind)
    else:
        total = 0
    page, more = rows[:limit], len(rows) > limit
    by_key = {int(r.unit_key): r for r in page}
    units = _units_of_page(conn, [int(r.unit_key) for r in page], by_key)
    groups: tuple[CurrencyGroup, ...] = ()
    if kind == "needs_account":
        found = conn.execute(_NEEDS_ACCOUNT_GROUPS, units_binds()).all()
        groups = tuple(CurrencyGroup(currency=str(r.currency), count=int(r.n)) for r in found)
    return QueueSection(
        kind=kind,
        total=total,
        units=units,
        next_cursor=encode_cursor(page[-1].booked_on, int(page[-1].anchor)) if more else None,
        groups=groups,
    )


def _section_total(conn: Connection, kind: SectionKind) -> int:
    return int(conn.execute(_SECTION_TOTAL, {**units_binds(), "section": kind}).scalar_one())


def _units_of_page(conn: Connection, keys: list[int], facts: dict[int, Row[Any]]) -> tuple[UnitView, ...]:
    if not keys:
        return ()
    ids = [int(i) for i in conn.execute(_ENTRIES_OF_UNITS, {"keys": keys}).scalars()]
    by_key: dict[int, list[EntryRow]] = {k: [] for k in keys}
    for row in entries_by_ids(conn, ids):
        if row.unit_key in by_key:
            by_key[row.unit_key].append(row)
    # the page order is the order of `keys` (the section's order), not of the anchors' ids
    return tuple(_view(k, by_key[k], *_facts_of(facts[k])) for k in keys)


def _facts_of(row: Row[Any]) -> tuple[str | None, WaitingFor | None, WaitingForDocument | None]:
    """What the section says of a unit: the currency it needs an account in, or what it waits for (the
    account of a partner leg, else the provider of a document)."""
    needs = str(row.currency) if row.currency is not None else None
    waiting = None
    waiting_document = None
    if needs is None and row.wait_account is not None:
        waiting = WaitingFor(account_id=int(row.wait_account), synced_through=row.synced_through)
    elif needs is None and row.doc_provider is not None:
        waiting_document = WaitingForDocument(provider=str(row.doc_provider), covered_through=row.doc_covered)
    return needs, waiting, waiting_document


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
        _section(conn, kind, limit=limit, cursor=cursor if section == kind else None) for kind in wanted
    )
    if section is None:
        total = sum(s.total for s in built)
    else:
        total = int(conn.execute(_QUEUE_TOTAL, units_binds()).scalar_one())
    return ReviewQueue(sections=built, total=total, snapshot=snapshot)


def new_unit_count(conn: Connection, since: str) -> tuple[int, str]:
    """Units in the queue now whose anchor entry was created after the snapshot `since`, and a fresh snapshot.

    An entry's id grows with creation, so "the anchor is newer than the snapshot" is a unit that arrived (an
    import, an entry form) rather than one that was already there and changed (a split, a reopened unit).
    One CTE pass; no per-unit work.
    """
    after = decode_snapshot(since)
    count = int(conn.execute(_NEW_UNITS, {**units_binds(), "since": after}).scalar_one())
    return count, encode_snapshot(int(conn.execute(_MAX_ENTRY_ID).scalar_one()))
