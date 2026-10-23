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
from app.core.resolution.confirmed import charged_sql, units_binds, units_sql
from app.core.units.closure import UnitEntry
from app.core.units.documents import OrderWait
from app.core.units.lookup import unit_ids_of
from app.core.units.state import UnitState, document_facts_of_flags, leg_states_of_flags, unit_state

SectionKind = Literal["pending_review", "needs_account", "waiting"]
SECTIONS: tuple[SectionKind, ...] = ("pending_review", "needs_account", "waiting")
DEFAULT_LIMIT = 100
MAX_LIMIT = 500


class InvalidCursor(ValueError):
    """A cursor that this server did not issue."""

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
    waiting_order: OrderWait | None = None  # ... or the rest of a document's order


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


def unit_entry_of(row: EntryRow) -> UnitEntry:
    return UnitEntry(
        id=row.id,
        source_transaction_id=row.source_transaction_id,
        type=row.type,
        category_id=row.category_id,
        counterpart_entry_id=row.counterpart_entry_id,
        derivation=row.derivation,
        document_id=row.document_id,
    )


def _view(
    unit_key: int,
    rows: Sequence[EntryRow],
    needs_account: str | None = None,
    waiting: WaitingFor | None = None,
    waiting_document: WaitingForDocument | None = None,
    waiting_order: OrderWait | None = None,
) -> UnitView:
    ordered = tuple(sorted(rows, key=lambda r: r.id))
    return UnitView(
        anchor_entry_id=ordered[0].id,
        unit_key=unit_key,
        state=unit_state(
            [unit_entry_of(r) for r in ordered],
            leg_states_of_flags({r.id: r.review_flags for r in ordered}),
            document_facts_of_flags(
                [(r.id, r.review_flags, r.document_id) for r in ordered if r.type == "flow"]
            ),
        ),
        entries=ordered,
        needs_account=needs_account,
        waiting=waiting,
        waiting_document=waiting_document,
        waiting_order=waiting_order,
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
# or, on a flow, for its document, or for the rest of the order of the document it carries (`doc_waiting`,
# documents.md §7: told apart by the link).
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
           dw.provider AS doc_provider, dw.covered_through AS doc_covered,
           ow.external_id AS order_id, ow.provider AS order_provider, ow.charged AS order_charged,
           ow.total AS order_total, ow.currency AS order_currency
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
              JOIN unnest(CAST(:doc_instances AS bigint[]), CAST(:doc_providers AS text[]))
                       AS r(instance_id, provider) ON r.provider = lower(pp.document_provider)
              JOIN importer_instance AS ii ON ii.id = r.instance_id AND NOT ii.disabled
                   AND (ii.settings ->> 'start_date' IS NULL
                        OR CAST(ii.settings ->> 'start_date' AS date) <= de.booked_on)
              LEFT JOIN v_document_coverage AS dc ON dc.importer_instance_id = ii.id
             WHERE de.id = p.doc_entry AND de.document_id IS NULL
               AND (dc.covered_through IS NULL
                    OR dc.covered_through
                       < de.booked_on + current_setting('ledger.document_window_ahead_days')::int)
             GROUP BY pp.document_provider) AS dw ON p.doc_entry IS NOT NULL
      LEFT JOIN LATERAL (
            SELECT od.external_id, od.provider, od.total, od.currency, """
    + charged_sql("od")
    + """ AS charged
              FROM ledger_entry AS oe
              JOIN external_document AS od ON od.id = oe.document_id
             WHERE oe.id = p.doc_entry) AS ow ON p.doc_entry IS NOT NULL
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

_ACTIONABLE_COUNT = text(
    _SECTIONED_SQL + "SELECT q.section, count(*) AS n FROM q WHERE q.section <> 'waiting' GROUP BY q.section"
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
        OR e.source_transaction_id IN (
              SELECT c.source_transaction_id
                FROM ledger_entry AS o
                JOIN ledger_entry AS c ON c.document_id = o.document_id
               WHERE o.source_transaction_id = ANY(:keys))
    """
)


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


def _section(conn: Connection, kind: SectionKind, *, limit: int, cursor: str | None) -> QueueSection:
    after_on, after_anchor = decode_cursor(cursor) if cursor else (None, 0)
    rows = conn.execute(
        _QUEUE_PAGE,
        {
            **units_binds(conn),
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
        found = conn.execute(_NEEDS_ACCOUNT_GROUPS, units_binds(conn)).all()
        groups = tuple(CurrencyGroup(currency=str(r.currency), count=int(r.n)) for r in found)
    return QueueSection(
        kind=kind,
        total=total,
        units=units,
        next_cursor=encode_cursor(page[-1].booked_on, int(page[-1].anchor)) if more else None,
        groups=groups,
    )


def _section_total(conn: Connection, kind: SectionKind) -> int:
    return int(conn.execute(_SECTION_TOTAL, {**units_binds(conn), "section": kind}).scalar_one())


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


def _facts_of(
    row: Row[Any],
) -> tuple[str | None, WaitingFor | None, WaitingForDocument | None, OrderWait | None]:
    """What the section says of a unit: the currency it needs an account in, or what it waits for (the
    account of a partner leg, else the provider of a document, else the rest of an order)."""
    needs = str(row.currency) if row.currency is not None else None
    waiting = None
    waiting_document = None
    waiting_order = None
    if needs is None and row.wait_account is not None:
        waiting = WaitingFor(account_id=int(row.wait_account), synced_through=row.synced_through)
    elif needs is None and row.doc_provider is not None:
        waiting_document = WaitingForDocument(provider=str(row.doc_provider), covered_through=row.doc_covered)
    elif needs is None and row.order_id is not None:
        waiting_order = OrderWait(
            order=str(row.order_id),
            provider=str(row.order_provider),
            charged=int(row.order_charged),
            total=int(row.order_total),
            currency=str(row.order_currency).strip(),
        )
    return needs, waiting, waiting_document, waiting_order


def review_queue(
    conn: Connection,
    *,
    limit: int = DEFAULT_LIMIT,
    section: SectionKind | None = None,
    cursor: str | None = None,
) -> ReviewQueue:
    """The first page of every section, or the page after `cursor` of one `section`."""
    wanted = SECTIONS if section is None else (section,)
    built = tuple(
        _section(conn, kind, limit=limit, cursor=cursor if section == kind else None) for kind in wanted
    )
    if section is None:
        total = sum(s.total for s in built)
    else:
        total = int(conn.execute(_QUEUE_TOTAL, units_binds(conn)).scalar_one())
    return ReviewQueue(sections=built, total=total)


@dataclass(frozen=True)
class ActionableCounts:
    pending_review: int
    needs_account: int

    @property
    def count(self) -> int:
        return self.pending_review + self.needs_account


def actionable_counts(conn: Connection) -> ActionableCounts:
    """Units that can be acted on now, by section: pending review and needs an account, not waiting (a
    waiting unit completes itself). The queue's own sections, one cheap pass."""
    n = {str(r.section): int(r.n) for r in conn.execute(_ACTIONABLE_COUNT, units_binds(conn))}
    return ActionableCounts(
        pending_review=n.get("pending_review", 0), needs_account=n.get("needs_account", 0)
    )


def actionable_count(conn: Connection) -> int:
    """Both sections together: what the Review item shows."""
    return actionable_counts(conn).count
