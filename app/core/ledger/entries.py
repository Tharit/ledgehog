"""The filtered, paged ledger list (architecture §4.1) and the id selection behind tag-apply.

SQLAlchemy Core composes the filter (architecture §5.2). Reads only: no lock, no write, no settle.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Connection, FromClause, func, select, text

from app.core.domain.source import SourceFields
from app.core.ledger.filters import LedgerFilter
from app.core.ledger.sql import compose, le, partner, st
from app.core.units.lookup import unit_keys_of


@dataclass(frozen=True)
class PartnerSummary:
    """The other leg of a transfer as a row shows it: where, when and how much."""

    entry_id: int
    account_id: int
    booked_on: date
    amount: int  # signed minor units, in `currency`
    currency: str


@dataclass(frozen=True)
class EntryRow:
    id: int
    version: int
    account_id: int
    booked_on: date
    value_on: date | None
    amount: int  # signed minor units, in `currency`
    currency: str
    type: str | None
    description: str | None
    note: str | None
    display_text: str | None  # description, else counterparty_name, else purpose
    payee_id: int | None
    category_id: int | None
    counter_account_id: int | None
    counterpart_entry_id: int | None
    source_transaction_id: int | None
    review_flags: tuple[str, ...]  # sorted
    tag_ids: tuple[int, ...]  # sorted
    source: SourceFields | None  # None only for derived entries
    derivation: Mapping[str, Any]  # as stored: key name -> {"pass", "basis", ...}
    unit_key: int | None  # the unit it is reviewed in (core/units); None for a derived entry
    authored: bool  # a user-authored movement (its source has the origin `user`)
    partner: PartnerSummary | None  # the other leg of a paired transfer
    importer: str | None = None  # the source's importer; None for an authored, booked or derived entry
    origin: str | None = None  # the source's origin (`import`, `user`, `booking`); None for a derived entry
    # a booking's source (spec §5.8): its kind (`document`, `transfer`) and the source's id (the document's,
    # or the charge's entry id); None for an entry that is not a booking's
    booking: tuple[str, int] | None = None


@dataclass(frozen=True)
class EntryPage:
    entries: tuple[EntryRow, ...]
    total: int  # entries matching the filter, whatever the page
    limit: int
    offset: int


def display_text(description: str | None, counterparty: str | None, purpose: str | None) -> str | None:
    return description or counterparty or purpose or None


# the list's order, shared by the page and the stream
_ORDER = (le.c.booked_on.desc(), le.c.source_transaction_id.desc().nulls_last(), le.c.id.desc())


def _paged(conn: Connection, stmt: Any) -> tuple[EntryRow, ...]:
    rows = conn.execute(stmt).all()
    return _build(conn, rows)


def list_entries(conn: Connection, flt: LedgerFilter, *, limit: int, offset: int) -> EntryPage:
    """One page of the entries matching `flt`, newest first; ties are total.

    Order: `booked_on DESC, source_transaction_id DESC NULLS LAST, id DESC`, so the siblings of a
    split (one source transaction, one date) are adjacent and derived entries sort after movements
    of the same day.
    """
    parts = compose(flt)
    total = conn.execute(select(func.count()).select_from(parts.source).where(*parts.where)).scalar_one()
    entries = _paged(
        conn,
        select(*_COLUMNS)
        .select_from(_with_partner(parts.source))
        .where(*parts.where)
        .order_by(*_ORDER)
        .limit(limit)
        .offset(offset),
    )
    return EntryPage(entries, int(total), limit, offset)


def stream_entries(
    conn: Connection, flt: LedgerFilter, *, batch: int = 500
) -> Iterator[tuple[EntryRow, ...]]:
    """Every entry matching `flt` in the list's order, in batches of up to `batch` rows.

    The rows come from a server-side cursor (no page, no cap, never the whole set in memory); each
    batch is completed (tags, documents, unit keys) like a page of the list.
    """
    parts = compose(flt)
    stmt = select(*_COLUMNS).select_from(_with_partner(parts.source)).where(*parts.where).order_by(*_ORDER)
    result = conn.execution_options(stream_results=True, max_row_buffer=batch).execute(stmt)
    try:
        for rows in result.partitions(batch):
            yield _build(conn, rows)
    finally:
        result.close()


def get_entry(conn: Connection, entry_id: int) -> EntryRow | None:
    """One entry in the row shape of the list, or None when there is none."""
    found = entries_by_ids(conn, [entry_id])
    return found[0] if found else None


def entries_by_ids(conn: Connection, entry_ids: Sequence[int]) -> tuple[EntryRow, ...]:
    """The rows of these entries in the row shape of the list, ascending by id."""
    if not entry_ids:
        return ()
    return _paged(
        conn,
        select(*_COLUMNS)
        .select_from(_with_partner(le.outerjoin(st, st.c.id == le.c.source_transaction_id)))
        .where(le.c.id.in_(list(entry_ids)))
        .order_by(le.c.id),
    )


def _with_partner(source: FromClause) -> FromClause:
    """`source` with the other leg of a transfer joined in: one unique-index lookup per row."""
    return source.outerjoin(partner, partner.c.id == le.c.counterpart_entry_id)


# the entry's own columns and the source's, from ledger_entry LEFT JOIN source_transaction: one query
_COLUMNS = (
    le.c.id,
    le.c.version,
    le.c.account_id,
    le.c.booked_on,
    le.c.value_on,
    le.c.amount,
    le.c.currency,
    le.c.type,
    le.c.description,
    le.c.note,
    le.c.payee_id,
    le.c.category_id,
    le.c.counter_account_id,
    le.c.counterpart_entry_id,
    le.c.source_transaction_id,
    le.c.review_flags,
    le.c.derivation,
    partner.c.id.label("partner_id"),
    partner.c.account_id.label("partner_account_id"),
    partner.c.booked_on.label("partner_booked_on"),
    partner.c.amount.label("partner_amount"),
    partner.c.currency.label("partner_currency"),
    st.c.importer,
    st.c.origin,
    st.c.source_id,
    st.c.amount.label("source_amount"),
    st.c.currency.label("source_currency"),
    st.c.counterparty_name,
    st.c.counterparty_ref,
    st.c.counterparty_bic,
    st.c.purpose,
    st.c.booking_text,
    st.c.end_to_end_id,
    st.c.mandate_ref,
    st.c.instructed_amount,
    st.c.instructed_currency,
    st.c.source_format,
)


def _build(conn: Connection, rows: Sequence[Any]) -> tuple[EntryRow, ...]:
    tags = tag_ids_of(conn, [r.id for r in rows])
    unit_keys = unit_keys_of(conn, {r.source_transaction_id for r in rows if r.source_transaction_id})
    return tuple(
        EntryRow(
            id=r.id,
            version=r.version,
            account_id=r.account_id,
            booked_on=r.booked_on,
            value_on=r.value_on,
            amount=r.amount,
            currency=r.currency,
            type=r.type,
            description=r.description,
            note=r.note,
            display_text=display_text(r.description, r.counterparty_name, r.purpose),
            payee_id=r.payee_id,
            category_id=r.category_id,
            counter_account_id=r.counter_account_id,
            counterpart_entry_id=r.counterpart_entry_id,
            source_transaction_id=r.source_transaction_id,
            review_flags=tuple(sorted(r.review_flags)),
            tag_ids=tags.get(r.id, ()),
            source=_source(r),
            derivation=r.derivation,
            unit_key=unit_keys.get(r.source_transaction_id) if r.source_transaction_id else None,
            authored=r.source_transaction_id is not None and r.origin == "user",
            partner=None
            if r.partner_id is None
            else PartnerSummary(
                entry_id=r.partner_id,
                account_id=r.partner_account_id,
                booked_on=r.partner_booked_on,
                amount=r.partner_amount,
                currency=r.partner_currency,
            ),
            importer=r.importer,
            origin=r.origin,
            booking=_booking_of(r),
        )
        for r in rows
    )


def _booking_of(r: Any) -> tuple[str, int] | None:
    if r.origin != "booking" or not r.source_id:
        return None
    kind, _, key = r.source_id.partition(":")
    return kind, int(key)


def _source(r: Any) -> SourceFields | None:
    """The nested source: none only for a derived entry (no source transaction)."""
    if r.source_transaction_id is None:
        return None
    return SourceFields.of_row(r)


def matching_entry_ids(conn: Connection, flt: LedgerFilter) -> list[int]:
    """Ids of every entry matching `flt`, ascending: the selection behind a bulk operation."""
    parts = compose(flt)
    stmt = select(le.c.id).select_from(parts.source).where(*parts.where).order_by(le.c.id)
    return [int(i) for i in conn.execute(stmt).scalars()]


_TAGS = text(
    "SELECT ledger_entry_id, array_agg(tag_id ORDER BY tag_id) AS tag_ids"
    " FROM ledger_entry_tag WHERE ledger_entry_id = ANY(:ids) GROUP BY ledger_entry_id"
)


def tag_ids_of(conn: Connection, entry_ids: list[int]) -> Mapping[int, tuple[int, ...]]:
    if not entry_ids:
        return {}
    found: Any = conn.execute(_TAGS, {"ids": entry_ids})
    return {int(r.ledger_entry_id): tuple(int(t) for t in r.tag_ids) for r in found}
