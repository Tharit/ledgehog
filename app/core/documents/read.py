"""The documents list and detail (architecture §4.1, spec §5.8, documents.md §9).

Reads only: no lock, no write, no settle. SQLAlchemy Core composes the filter (architecture §5.2), as the
ledger list does. A document is listed with its lines; whether and where it is booked is the booking's
(a later wave).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Connection,
    FromClause,
    Select,
    String,
    cast,
    column,
    exists,
    func,
    or_,
    select,
    table,
)

from app.core.bookings.documents import (
    DocumentFacts,
    NotBooked,
    document_source_id,
    not_booked,
    provider_index,
)
from app.core.bookings.load import load_clearance_accounts
from app.core.documents.filters import DocumentFilter
from app.core.importers.providers import importer_names
from app.core.ledger.sql import like_pattern

doc = table(
    "external_document",
    column("id"),
    column("provider"),
    column("source_id"),
    column("importer_instance_id"),
    column("occurred_on"),
    column("total"),
    column("currency"),
    column("merchant_name"),
    column("title"),
    column("reference"),
    column("version"),
)
line = table(
    "external_document_line",
    column("document_id"),
    column("line_no"),
    column("description"),
    column("amount"),
    column("qty"),
)

source = table(
    "source_transaction", column("id"), column("origin"), column("source_id"), column("account_id")
)
entry = table(
    "ledger_entry", column("id"), column("source_transaction_id"), column("amount"), column("source_text")
)

# a document is booked while its booking (a source transaction of origin `booking`) exists
_booked = exists(
    select(1).where(
        source.c.origin == "booking", source.c.source_id == func.concat("document:", cast(doc.c.id, String))
    )
)

MAX_PAGE = 500


@dataclass(frozen=True)
class DocumentRow:
    id: int
    provider: str
    source_id: str
    importer_instance_id: int | None
    occurred_on: date
    total: int  # signed minor units, in `currency`; a refund is positive
    currency: str
    merchant_name: str | None
    title: str | None
    reference: str | None
    version: int
    line_count: int
    booking: DocumentBooking | None = None  # the booking made from it, if any
    not_booked: NotBooked | None = None  # else the first reason that applies (None: settling will book it)


@dataclass(frozen=True)
class BookingEntry:
    id: int
    amount: int  # minor units of the document's currency
    source_text: str | None


@dataclass(frozen=True)
class DocumentBooking:
    """Where a document is booked: the clearance account and the booking's source transaction; the entries
    (in line order) only on a detail."""

    account_id: int
    source_transaction_id: int
    entries: tuple[BookingEntry, ...] = ()


@dataclass(frozen=True)
class DocumentLine:
    line_no: int
    description: str
    amount: int  # signed like the total
    qty: int | None


@dataclass(frozen=True)
class DocumentPage:
    documents: tuple[DocumentRow, ...]
    total: int  # documents matching the filter, whatever the page
    limit: int
    offset: int


@dataclass(frozen=True)
class DocumentDetail:
    document: DocumentRow
    lines: tuple[DocumentLine, ...]


def _where(flt: DocumentFilter) -> tuple[ColumnElement[bool], ...]:
    where: list[ColumnElement[bool]] = []
    if flt.providers:
        where.append(func.lower(doc.c.provider).in_([p.lower() for p in flt.providers]))
    if flt.date_from is not None:
        where.append(doc.c.occurred_on >= flt.date_from)
    if flt.date_to is not None:
        where.append(doc.c.occurred_on <= flt.date_to)
    if flt.currency is not None:
        where.append(doc.c.currency == flt.currency)
    magnitude = func.abs(doc.c.total)
    if flt.amount_min is not None:
        where.append(magnitude >= flt.amount_min)
    if flt.amount_max is not None:
        where.append(magnitude <= flt.amount_max)
    if flt.text is not None:
        for word in flt.text.split():
            pattern = like_pattern(word)
            where.append(
                or_(
                    doc.c.merchant_name.ilike(pattern, escape="\\"),
                    doc.c.title.ilike(pattern, escape="\\"),
                    doc.c.reference.ilike(pattern, escape="\\"),
                    exists(
                        select(1).where(
                            line.c.document_id == doc.c.id, line.c.description.ilike(pattern, escape="\\")
                        )
                    ),
                )
            )
    if flt.booked is not None:
        where.append(_booked if flt.booked else ~_booked)
    return tuple(where)


def _source() -> FromClause:
    return doc


_LINES = select(func.count()).where(line.c.document_id == doc.c.id).scalar_subquery()


def _rows_stmt() -> Select[Any]:
    return (
        select(
            doc.c.id,
            doc.c.provider,
            doc.c.source_id,
            doc.c.importer_instance_id,
            doc.c.occurred_on,
            doc.c.total,
            doc.c.currency,
            doc.c.merchant_name,
            doc.c.title,
            doc.c.reference,
            doc.c.version,
            _LINES.label("line_count"),
        )
        .select_from(_source())
        .order_by(doc.c.occurred_on.desc(), doc.c.id.desc())
    )


def _build(rows: Sequence[Any]) -> tuple[DocumentRow, ...]:
    return tuple(
        DocumentRow(
            id=r.id,
            provider=r.provider,
            source_id=r.source_id,
            importer_instance_id=r.importer_instance_id,
            occurred_on=r.occurred_on,
            total=r.total,
            currency=r.currency.strip(),
            merchant_name=r.merchant_name,
            title=r.title,
            reference=r.reference,
            version=r.version,
            line_count=r.line_count,
        )
        for r in rows
    )


def _with_booking(
    conn: Connection, rows: tuple[DocumentRow, ...], *, entries: bool = False
) -> tuple[DocumentRow, ...]:
    """Each row with its booking, or the reason it has none (`not_booked`, spec §5.8)."""
    if not rows:
        return rows
    keys = {document_source_id(r.id): r.id for r in rows}
    booked = {
        keys[r.source_id]: DocumentBooking(r.account_id, r.id)
        for r in conn.execute(
            select(source.c.id, source.c.account_id, source.c.source_id).where(
                source.c.origin == "booking", source.c.source_id.in_(list(keys))
            )
        )
    }
    if entries:
        for document_id, booking in list(booked.items()):
            booked[document_id] = DocumentBooking(
                booking.account_id,
                booking.source_transaction_id,
                tuple(
                    BookingEntry(r.id, r.amount, r.source_text)
                    for r in conn.execute(
                        select(entry.c.id, entry.c.amount, entry.c.source_text)
                        .where(entry.c.source_transaction_id == booking.source_transaction_id)
                        .order_by(entry.c.id)
                    )
                ),
            )
    index = provider_index(load_clearance_accounts(conn))
    return tuple(
        replace(
            r,
            booking=booked.get(r.id),
            not_booked=None
            if r.id in booked
            else not_booked(
                DocumentFacts(r.id, r.provider, r.reference, r.occurred_on, r.total, r.currency), index
            ),
        )
        for r in rows
    )


def provider_names(conn: Connection) -> list[str]:
    """Suggestions for a provider (a clearance account's provider list, a filter): the names importers give
    and the distinct providers of stored documents, one spelling per name regardless of case (an importer's
    wins), sorted."""
    names: dict[str, str] = {p.lower(): p for p in importer_names()}
    for p in sorted(conn.execute(select(doc.c.provider).distinct()).scalars()):  # code points: stable
        names.setdefault(str(p).lower(), str(p))
    return sorted(names.values())


def list_documents(conn: Connection, flt: DocumentFilter, *, limit: int, offset: int) -> DocumentPage:
    """One page of the documents matching `flt`, newest first (`occurred_on DESC, id DESC`)."""
    where = _where(flt)
    total = conn.execute(select(func.count()).select_from(_source()).where(*where)).scalar_one()
    rows = conn.execute(_rows_stmt().where(*where).limit(limit).offset(offset)).all()
    return DocumentPage(_with_booking(conn, _build(rows)), int(total), limit, offset)


def _lines(conn: Connection, document_id: int) -> tuple[DocumentLine, ...]:
    return tuple(
        DocumentLine(r.line_no, r.description, r.amount, r.qty)
        for r in conn.execute(
            select(line.c.line_no, line.c.description, line.c.amount, line.c.qty)
            .where(line.c.document_id == document_id)
            .order_by(line.c.line_no)
        )
    )


def get_document(conn: Connection, document_id: int) -> DocumentDetail | None:
    """A document with its lines; None when there is no such document."""
    found = _build(conn.execute(_rows_stmt().where(doc.c.id == document_id)).all())
    if not found:
        return None
    (row,) = _with_booking(conn, found, entries=True)
    return DocumentDetail(row, _lines(conn, document_id))
