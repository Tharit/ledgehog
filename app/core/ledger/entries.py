"""The filtered, paged ledger list (architecture §4.1) and the id selection behind tag-apply.

SQLAlchemy Core composes the filter (architecture §5.2). Reads only: no lock, no write, no settle.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Connection, func, select, text

from app.core.domain.source import SourceFields
from app.core.ledger.filters import LedgerFilter
from app.core.ledger.sql import compose, le, st


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
    document_id: int | None
    review_flags: tuple[str, ...]  # sorted
    tag_ids: tuple[int, ...]  # sorted
    source: SourceFields | None  # None for derived and user-authored entries


@dataclass(frozen=True)
class EntryPage:
    entries: tuple[EntryRow, ...]
    total: int  # entries matching the filter, whatever the page
    limit: int
    offset: int


def display_text(description: str | None, counterparty: str | None, purpose: str | None) -> str | None:
    return description or counterparty or purpose or None


def list_entries(conn: Connection, flt: LedgerFilter, *, limit: int, offset: int) -> EntryPage:
    """One page of the entries matching `flt`, newest first; ties are total.

    Order: `booked_on DESC, source_transaction_id DESC NULLS LAST, id DESC`, so the siblings of a
    split (one source transaction, one date) are adjacent and derived entries sort after movements
    of the same day.
    """
    parts = compose(flt)
    total = conn.execute(select(func.count()).select_from(parts.source).where(*parts.where)).scalar_one()
    rows = conn.execute(
        select(*_COLUMNS)
        .select_from(parts.source)
        .where(*parts.where)
        .order_by(
            le.c.booked_on.desc(),
            le.c.source_transaction_id.desc().nulls_last(),
            le.c.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    ).all()
    return EntryPage(_build(rows, tag_ids_of(conn, [r.id for r in rows])), int(total), limit, offset)


def get_entry(conn: Connection, entry_id: int) -> EntryRow | None:
    """One entry in the row shape of the list, or None when there is none."""
    rows = conn.execute(
        select(*_COLUMNS)
        .select_from(le.outerjoin(st, st.c.id == le.c.source_transaction_id))
        .where(le.c.id == entry_id)
    ).all()
    if not rows:
        return None
    return _build(rows, tag_ids_of(conn, [entry_id]))[0]


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
    le.c.document_id,
    le.c.review_flags,
    st.c.importer,
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


def _build(rows: Sequence[Any], tags: Mapping[int, tuple[int, ...]]) -> tuple[EntryRow, ...]:
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
            document_id=r.document_id,
            review_flags=tuple(sorted(r.review_flags)),
            tag_ids=tags.get(r.id, ()),
            source=_source(r),
        )
        for r in rows
    )


def _source(r: Any) -> SourceFields | None:
    """The nested source: none for a derived entry or a user-authored row (no importer)."""
    if r.source_transaction_id is None or r.importer is None:
        return None
    return SourceFields(
        counterparty_name=r.counterparty_name,
        counterparty_ref=r.counterparty_ref,
        counterparty_bic=r.counterparty_bic,
        purpose=r.purpose,
        booking_text=r.booking_text,
        end_to_end_id=r.end_to_end_id,
        mandate_ref=r.mandate_ref,
        instructed_amount=r.instructed_amount,
        instructed_currency=r.instructed_currency,
        source_format=r.source_format,
    )


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
