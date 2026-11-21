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

The pending section can instead be cut by counterparty (`cut="counterparty"`, `ux/views/review-queue.md`): a
unit's counterparty is the counterparty name of its anchor entry's source, lower-cased with whitespace
collapsed and trimmed. A counterparty with more than one unit in the section (after the account filter) is a
group, labelled as its first unit (by booked date, then anchor) spells it; the rest, and units whose source
names none, form one last "Other" group. Groups are ordered by count (largest first), then by key, "Other"
last; within a group by booked date, then anchor: a total order again, and its cursor carries
`(other, -count, key, booked_on, anchor)`. The groups are the server's, whole-section, so a page continues the
last band or starts the next. A cursor of one cut is not valid for the other.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from sqlalchemy import Connection, Row, text

from app.core.ledger.entries import EntryRow, entries_by_ids
from app.core.resolution.confirmed import units_binds, units_sql
from app.core.units.closure import UnitEntry
from app.core.units.lookup import unit_ids_of
from app.core.units.state import UnitState, leg_states_of_flags, unit_state

SectionKind = Literal["pending_review", "needs_account", "waiting"]
SECTIONS: tuple[SectionKind, ...] = ("pending_review", "needs_account", "waiting")
QueueCut = Literal["date", "counterparty"]
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
class UnitView:
    anchor_entry_id: int  # the lowest entry id of the unit: what opens it
    unit_key: int
    state: UnitState
    entries: tuple[EntryRow, ...]  # ascending by id
    needs_account: str | None = None  # queue only: the instructed currency a unit in `needs_account` needs
    waiting: WaitingFor | None = None  # queue only: what a unit in `waiting` waits for (a partner)
    # the unit holds a booking (spec §5.8): the kind of its source, `document` or `transfer`
    booking: str | None = None
    # queue only, pending review cut by counterparty: the key of the unit's group (None: the "Other" group)
    counterparty_key: str | None = None


@dataclass(frozen=True)
class CounterpartyGroup:
    key: str | None  # the normalised counterparty name; None for the "Other" group
    label: str | None  # the name as the group's first unit spells it; None for "Other"
    count: int  # units in the section in the group
    other: bool  # the last group: single-unit counterparties and units without one


@dataclass(frozen=True)
class CurrencyGroup:
    currency: str
    count: int  # units in the section that need an account in it


@dataclass(frozen=True)
class AccountGroup:
    account_id: int
    synced_through: date | None  # how far that account has been fetched; None = never
    count: int  # units in the section that wait for it


@dataclass(frozen=True)
class QueueSection:
    kind: SectionKind
    total: int  # units in the section, whatever the page
    units: tuple[UnitView, ...]
    next_cursor: str | None
    groups: tuple[CurrencyGroup, ...] = ()  # `needs_account` only: per currency, over the whole section
    account_groups: tuple[AccountGroup, ...] = ()  # `waiting` only: per account waited for, whole section
    # `pending_review` cut by counterparty only: the groups in order, over the whole section
    counterparty_groups: tuple[CounterpartyGroup, ...] = ()


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
    )


def _view(
    unit_key: int,
    rows: Sequence[EntryRow],
    needs_account: str | None = None,
    waiting: WaitingFor | None = None,
    counterparty_key: str | None = None,
) -> UnitView:
    ordered = tuple(sorted(rows, key=lambda r: r.id))
    return UnitView(
        anchor_entry_id=ordered[0].id,
        unit_key=unit_key,
        state=unit_state(
            [unit_entry_of(r) for r in ordered],
            leg_states_of_flags({r.id: r.review_flags for r in ordered}),
        ),
        entries=ordered,
        needs_account=needs_account,
        waiting=waiting,
        booking=next((r.booking[0] for r in ordered if r.booking is not None), None),
        counterparty_key=counterparty_key,
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
# A leg is WAITING when it carries the flag `core/settle/flags.py` writes: for its partner.
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
                   ('waiting' = ANY(le.review_flags)) AS waiting
              FROM units AS u JOIN ledger_entry AS le ON le.id = u.id
              JOIN source_transaction AS st ON st.id = le.source_transaction_id
             WHERE NOT u.unit_ok
               AND (cardinality(CAST(:accounts AS bigint[])) = 0
                    OR u.unit_key IN (
                        SELECT m.unit_key FROM units AS m JOIN ledger_entry AS me ON me.id = m.id
                         WHERE me.account_id = ANY(CAST(:accounts AS bigint[]))))),
         q AS (
            SELECT l.unit_key, min(l.id) AS anchor,
                   CASE WHEN bool_or(l.needs_account) THEN 'needs_account'
                        WHEN bool_or(l.waiting) THEN 'waiting' ELSE 'pending_review' END AS section,
                   (array_agg(l.instructed_currency ORDER BY l.id) FILTER (WHERE l.needs_account))[1]
                       AS currency,
                   (array_agg(l.counter_account_id ORDER BY l.id) FILTER (WHERE l.waiting))[1] AS wait_account
              FROM legs AS l GROUP BY l.unit_key)
"""

_SECTIONED_SQL = _SECTIONED.format(units=units_sql())

_QUEUE_PAGE = text(
    _SECTIONED_SQL
    + """
    SELECT p.unit_key, p.anchor, p.booked_on, p.total, p.currency, p.wait_account, cv.synced_through
      FROM (SELECT t.*
              FROM (SELECT q.unit_key, q.anchor, q.currency, q.wait_account, e.booked_on,
                           count(*) OVER () AS total
                      FROM q JOIN ledger_entry AS e ON e.id = q.anchor
                     WHERE q.section = :section) AS t
             WHERE (CAST(:after_on AS date) IS NULL
                    OR (t.booked_on, t.anchor) > (CAST(:after_on AS date), CAST(:after_anchor AS bigint)))
             ORDER BY t.booked_on, t.anchor
             LIMIT :limit) AS p
      LEFT JOIN v_account_coverage AS cv ON cv.account_id = p.wait_account
     ORDER BY p.booked_on, p.anchor
    """
)

# The pending section cut by counterparty. `cp` is its units with the normalised counterparty name of the
# anchor's source (empty or null: none); a name with more than one unit is a group (`gkey`), the rest are
# "Other" (`gkey` null). `o` is 1 for Other, `neg` the negated group count, `g` the key ('' for Other): the
# section's sort key is (o, neg, g, booked_on, anchor).
_COUNTERPARTY_CTE = r"""
    , cp AS (
        SELECT q.unit_key, q.anchor, q.currency, q.wait_account, e.booked_on, st.counterparty_name AS raw,
               nullif(btrim(regexp_replace(lower(st.counterparty_name), '\s+', ' ', 'g')), '') AS key
          FROM q JOIN ledger_entry AS e ON e.id = q.anchor
          JOIN source_transaction AS st ON st.id = e.source_transaction_id
         WHERE q.section = 'pending_review'),
      cnt AS (SELECT key, count(*) AS n FROM cp WHERE key IS NOT NULL GROUP BY key),
      ranked AS (
        SELECT cp.unit_key, cp.anchor, cp.currency, cp.wait_account, cp.booked_on, cp.raw,
               CASE WHEN c.n > 1 THEN cp.key END AS gkey,
               CASE WHEN c.n > 1 THEN 0 ELSE 1 END AS o,
               CASE WHEN c.n > 1 THEN -c.n ELSE 0 END AS neg,
               CASE WHEN c.n > 1 THEN cp.key ELSE '' END AS g
          FROM cp LEFT JOIN cnt AS c ON c.key = cp.key)
"""

_COUNTERPARTY_PAGE = text(
    _SECTIONED_SQL
    + _COUNTERPARTY_CTE
    + """
    SELECT t.unit_key, t.anchor, t.booked_on, t.total, t.currency, t.wait_account, t.gkey, t.o, t.neg, t.g,
           CAST(NULL AS date) AS synced_through
      FROM (SELECT r.*, count(*) OVER () AS total FROM ranked AS r) AS t
     WHERE (CAST(:after_o AS int) IS NULL
            OR (t.o, t.neg, t.g, t.booked_on, t.anchor)
               > (CAST(:after_o AS int), CAST(:after_neg AS int), CAST(:after_g AS text),
                  CAST(:after_on AS date), CAST(:after_anchor AS bigint)))
     ORDER BY t.o, t.neg, t.g, t.booked_on, t.anchor
     LIMIT :limit
    """
)

_COUNTERPARTY_GROUPS = text(
    _SECTIONED_SQL
    + _COUNTERPARTY_CTE
    + """
    SELECT r.gkey, (array_agg(r.raw ORDER BY r.booked_on, r.anchor))[1] AS label, count(*) AS n
      FROM ranked AS r
     GROUP BY r.gkey, r.o, r.neg, r.g
     ORDER BY r.o, r.neg, r.g
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

# the accounts' own order (as `list_accounts`): open first, then sort order, name, id
_WAITING_GROUPS = text(
    _SECTIONED_SQL
    + """
    SELECT q.wait_account AS account_id, cv.synced_through, count(*) AS n
      FROM q JOIN account AS a ON a.id = q.wait_account
      LEFT JOIN v_account_coverage AS cv ON cv.account_id = q.wait_account
     WHERE q.section = 'waiting'
     GROUP BY q.wait_account, cv.synced_through, a.closed_on, a.sort_order, a.name
     ORDER BY (a.closed_on IS NOT NULL), a.sort_order, a.name, q.wait_account
    """
)

_QUEUE_TOTAL = text(
    f"""
    WITH units AS ({units_sql()})
    SELECT count(DISTINCT u.unit_key) FROM units AS u WHERE NOT u.unit_ok
       AND (cardinality(CAST(:accounts AS bigint[])) = 0
            OR u.unit_key IN (SELECT m.unit_key FROM units AS m JOIN ledger_entry AS me ON me.id = m.id
                               WHERE me.account_id = ANY(CAST(:accounts AS bigint[]))))
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


def encode_counterparty_cursor(o: int, neg: int, g: str, booked_on: date, anchor: int) -> str:
    raw = "c2:" + json.dumps([o, neg, g, booked_on.isoformat(), anchor])
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_counterparty_cursor(token: str) -> tuple[int, int, str, date, int]:
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
        tag, _, body = raw.partition(":")
        o, neg, g, day, anchor = json.loads(body)
        if tag != "c2" or not isinstance(g, str) or o not in (0, 1):
            raise ValueError(raw)
        return int(o), int(neg), g, date.fromisoformat(day), int(anchor)
    except (ValueError, TypeError, binascii.Error, UnicodeDecodeError) as exc:
        raise InvalidCursor("cursor") from exc


def _binds(conn: Connection, accounts: tuple[int, ...]) -> dict[str, object]:
    """The binds of the sectioned queries: the standing passes and the accounts the queue is narrowed to
    (none: the whole queue)."""
    return {**units_binds(conn), "accounts": list(accounts)}


def _section(
    conn: Connection,
    kind: SectionKind,
    *,
    limit: int,
    cursor: str | None,
    accounts: tuple[int, ...],
    cut: QueueCut = "date",
) -> QueueSection:
    by_counterparty = cut == "counterparty" and kind == "pending_review"
    if by_counterparty:
        c_o, c_neg, c_g, after_on, after_anchor = (
            decode_counterparty_cursor(cursor) if cursor else (None, 0, "", None, 0)
        )
        rows = conn.execute(
            _COUNTERPARTY_PAGE,
            {
                **_binds(conn, accounts),
                "after_o": c_o,
                "after_neg": c_neg,
                "after_g": c_g,
                "after_on": after_on,
                "after_anchor": after_anchor,
                "limit": limit + 1,
            },
        ).all()
    else:
        after_on, after_anchor = decode_cursor(cursor) if cursor else (None, 0)
        rows = conn.execute(
            _QUEUE_PAGE,
            {
                **_binds(conn, accounts),
                "section": kind,
                "after_on": after_on,
                "after_anchor": after_anchor,
                "limit": limit + 1,
            },
        ).all()
    if rows:
        total = int(rows[0].total)
    elif cursor:  # a cursor past the end: the page is empty, the section is not
        total = _section_total(conn, kind, accounts)
    else:
        total = 0
    page, more = rows[:limit], len(rows) > limit
    by_key = {int(r.unit_key): r for r in page}
    units = _units_of_page(conn, [int(r.unit_key) for r in page], by_key)
    groups: tuple[CurrencyGroup, ...] = ()
    if kind == "needs_account":
        found = conn.execute(_NEEDS_ACCOUNT_GROUPS, _binds(conn, accounts)).all()
        groups = tuple(CurrencyGroup(currency=str(r.currency), count=int(r.n)) for r in found)
    account_groups: tuple[AccountGroup, ...] = ()
    if kind == "waiting":
        found = conn.execute(_WAITING_GROUPS, _binds(conn, accounts)).all()
        account_groups = tuple(
            AccountGroup(account_id=int(r.account_id), synced_through=r.synced_through, count=int(r.n))
            for r in found
        )
    counterparty_groups: tuple[CounterpartyGroup, ...] = ()
    next_cursor: str | None = None
    if by_counterparty:
        found = conn.execute(_COUNTERPARTY_GROUPS, _binds(conn, accounts)).all()
        counterparty_groups = tuple(
            CounterpartyGroup(
                key=None if r.gkey is None else str(r.gkey),
                label=None if r.gkey is None else str(r.label),
                count=int(r.n),
                other=r.gkey is None,
            )
            for r in found
        )
        if more:
            last = page[-1]
            next_cursor = encode_counterparty_cursor(
                int(last.o), int(last.neg), str(last.g), last.booked_on, int(last.anchor)
            )
    elif more:
        next_cursor = encode_cursor(page[-1].booked_on, int(page[-1].anchor))
    return QueueSection(
        kind=kind,
        total=total,
        units=units,
        next_cursor=next_cursor,
        groups=groups,
        account_groups=account_groups,
        counterparty_groups=counterparty_groups,
    )


def _section_total(conn: Connection, kind: SectionKind, accounts: tuple[int, ...]) -> int:
    return int(conn.execute(_SECTION_TOTAL, {**_binds(conn, accounts), "section": kind}).scalar_one())


def _units_of_page(conn: Connection, keys: list[int], facts: dict[int, Row[Any]]) -> tuple[UnitView, ...]:
    if not keys:
        return ()
    ids = [int(i) for i in conn.execute(_ENTRIES_OF_UNITS, {"keys": keys}).scalars()]
    by_key: dict[int, list[EntryRow]] = {k: [] for k in keys}
    for row in entries_by_ids(conn, ids):
        if row.unit_key in by_key:
            by_key[row.unit_key].append(row)
    # the page order is the order of `keys` (the section's order), not of the anchors' ids
    return tuple(
        _view(k, by_key[k], *_facts_of(facts[k]), counterparty_key=getattr(facts[k], "gkey", None))
        for k in keys
    )


def _facts_of(row: Row[Any]) -> tuple[str | None, WaitingFor | None]:
    """What the section says of a unit: the currency it needs an account in, or what it waits for (the
    account of a partner leg)."""
    needs = str(row.currency) if row.currency is not None else None
    waiting = None
    if needs is None and row.wait_account is not None:
        waiting = WaitingFor(account_id=int(row.wait_account), synced_through=row.synced_through)
    return needs, waiting


def review_queue(
    conn: Connection,
    *,
    limit: int = DEFAULT_LIMIT,
    section: SectionKind | None = None,
    cursor: str | None = None,
    account_ids: tuple[int, ...] = (),
    cut: QueueCut = "date",
) -> ReviewQueue:
    """The first page of every section, or the page after `cursor` of one `section`. `account_ids` narrows
    the queue to the units with an entry on any of them (none: the whole queue); the sections, their groups
    and their counts are those of the units left. `cut="counterparty"` orders the pending section by
    counterparty (module docstring) and gives it its `counterparty_groups`; the other sections keep their
    order."""
    wanted = SECTIONS if section is None else (section,)
    built = tuple(
        _section(
            conn, kind, limit=limit, cursor=cursor if section == kind else None, accounts=account_ids, cut=cut
        )
        for kind in wanted
    )
    if section is None:
        total = sum(s.total for s in built)
    else:
        total = int(conn.execute(_QUEUE_TOTAL, _binds(conn, account_ids)).scalar_one())
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
    n = {str(r.section): int(r.n) for r in conn.execute(_ACTIONABLE_COUNT, _binds(conn, ()))}
    return ActionableCounts(
        pending_review=n.get("pending_review", 0), needs_account=n.get("needs_account", 0)
    )


def actionable_count(conn: Connection) -> int:
    """Both sections together: what the Review item shows."""
    return actionable_counts(conn).count
