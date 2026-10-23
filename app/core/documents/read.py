"""The documents list and detail (architecture §4.1, spec §5.8, documents.md §9).

Reads only: no lock, no write, no settle. Documents are browsed here and linked only through a unit's
commit. SQLAlchemy Core composes the filter (architecture §5.2), as the ledger list does.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Connection,
    FromClause,
    Select,
    column,
    exists,
    func,
    or_,
    select,
    table,
    text,
)

from app.core.documents.filters import DocumentFilter
from app.core.importers.providers import importer_names
from app.core.ledger.entries import display_text
from app.core.ledger.sql import like_pattern
from app.core.matching.documents import DocTxn, fully_charged, reverse_matches
from app.core.resolution.confirmed import units_binds, units_sql
from app.core.resolution.doc_load import load_document
from app.core.settle.window import document_window

doc = table(
    "external_document",
    column("id"),
    column("provider"),
    column("external_id"),
    column("importer_instance_id"),
    column("occurred_on"),
    column("total"),
    column("currency"),
    column("merchant_name"),
    column("title"),
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
# a document with its first carrier (the lowest entry id), None where none carries it; the list and detail
# still show a single carrier (a document may have several, spec §5.8)
_links = table("v_document_link", column("document_id"), column("ledger_entry_id"))
link = (
    select(_links.c.document_id, func.min(_links.c.ledger_entry_id).label("ledger_entry_id"))
    .group_by(_links.c.document_id)
    .subquery("link")
)
carrier = table("ledger_entry", column("id"), column("account_id"), column("source_transaction_id"))
src = table(
    "source_transaction",
    column("id"),
    column("booked_on"),
    column("amount"),
    column("currency"),
)

MAX_PAGE = 500


@dataclass(frozen=True)
class Carrier:
    """The transaction carrying a document: its original entry, with the transaction's own date and amount."""

    entry_id: int
    source_transaction_id: int
    account_id: int
    booked_on: date
    amount: int  # signed minor units, in `currency`
    currency: str


@dataclass(frozen=True)
class DocumentRow:
    id: int
    provider: str
    external_id: str
    importer_instance_id: int | None
    occurred_on: date
    total: int  # signed minor units, in `currency`; a refund is positive
    currency: str
    merchant_name: str | None
    title: str | None
    version: int
    line_count: int
    carrier: Carrier | None  # None: carried by no entry


@dataclass(frozen=True)
class DocumentLine:
    line_no: int
    description: str
    amount: int  # signed like the total
    qty: int | None


@dataclass(frozen=True)
class DocumentMatch:
    """A transaction a document would match (documents.md §9), with its unit's state."""

    entry_id: int  # the original entry: what opens the review panel
    source_transaction_id: int
    account_id: int
    booked_on: date
    amount: int
    currency: str
    instructed_amount: int | None
    instructed_currency: str | None
    display_text: str | None
    payee_id: int | None
    document_id: int | None  # the document it already carries: picking replaces that link
    confirmed: bool  # its unit is confirmed (spec I20)


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
    matches: tuple[DocumentMatch, ...]  # empty for a linked document


def _where(flt: DocumentFilter) -> tuple[ColumnElement[bool], ...]:
    where: list[ColumnElement[bool]] = []
    if flt.providers:
        where.append(doc.c.provider.in_(flt.providers))
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
    if flt.linked is not None:
        where.append(link.c.ledger_entry_id.is_not(None) if flt.linked else link.c.ledger_entry_id.is_(None))
    if flt.text is not None:
        for word in flt.text.split():
            pattern = like_pattern(word)
            where.append(
                or_(
                    doc.c.merchant_name.ilike(pattern, escape="\\"),
                    doc.c.title.ilike(pattern, escape="\\"),
                    exists(
                        select(1).where(
                            line.c.document_id == doc.c.id, line.c.description.ilike(pattern, escape="\\")
                        )
                    ),
                )
            )
    return tuple(where)


def _source() -> FromClause:
    return doc.outerjoin(link, link.c.document_id == doc.c.id)


_LINES = select(func.count()).where(line.c.document_id == doc.c.id).scalar_subquery()


def _rows_stmt() -> Select[Any]:
    return (
        select(
            doc.c.id,
            doc.c.provider,
            doc.c.external_id,
            doc.c.importer_instance_id,
            doc.c.occurred_on,
            doc.c.total,
            doc.c.currency,
            doc.c.merchant_name,
            doc.c.title,
            doc.c.version,
            _LINES.label("line_count"),
            carrier.c.id.label("entry_id"),
            carrier.c.account_id,
            carrier.c.source_transaction_id,
            src.c.booked_on,
            src.c.amount,
            src.c.currency.label("source_currency"),
        )
        .select_from(
            _source()
            .outerjoin(carrier, carrier.c.id == link.c.ledger_entry_id)
            .outerjoin(src, src.c.id == carrier.c.source_transaction_id)
        )
        .order_by(doc.c.occurred_on.desc(), doc.c.id.desc())
    )


def _build(rows: Sequence[Any]) -> tuple[DocumentRow, ...]:
    return tuple(
        DocumentRow(
            id=r.id,
            provider=r.provider,
            external_id=r.external_id,
            importer_instance_id=r.importer_instance_id,
            occurred_on=r.occurred_on,
            total=r.total,
            currency=r.currency.strip(),
            merchant_name=r.merchant_name,
            title=r.title,
            version=r.version,
            line_count=r.line_count,
            carrier=None
            if r.entry_id is None
            else Carrier(
                entry_id=r.entry_id,
                source_transaction_id=r.source_transaction_id,
                account_id=r.account_id,
                booked_on=r.booked_on,
                amount=r.amount,
                currency=r.source_currency.strip(),
            ),
        )
        for r in rows
    )


def provider_names(conn: Connection) -> list[str]:
    """Suggestions for a provider (spec §5.8; a payee may name any): the names importers give and the
    distinct providers of stored documents, one spelling per name regardless of case (an importer's wins),
    sorted."""
    names: dict[str, str] = {p.lower(): p for p in importer_names()}
    for p in sorted(conn.execute(select(doc.c.provider).distinct()).scalars()):  # code points: stable
        names.setdefault(str(p).lower(), str(p))
    return sorted(names.values())


def list_documents(conn: Connection, flt: DocumentFilter, *, limit: int, offset: int) -> DocumentPage:
    """One page of the documents matching `flt`, newest first (`occurred_on DESC, id DESC`)."""
    where = _where(flt)
    total = conn.execute(select(func.count()).select_from(_source()).where(*where)).scalar_one()
    rows = conn.execute(_rows_stmt().where(*where).limit(limit).offset(offset)).all()
    return DocumentPage(_build(rows), int(total), limit, offset)


def get_document(conn: Connection, document_id: int) -> DocumentDetail | None:
    """A document with its lines and, when no entry carries it, the transactions it would match;
    None when there is no such document."""
    found = _build(conn.execute(_rows_stmt().where(doc.c.id == document_id)).all())
    if not found:
        return None
    row = found[0]
    lines = tuple(
        DocumentLine(r.line_no, r.description, r.amount, r.qty)
        for r in conn.execute(
            select(line.c.line_no, line.c.description, line.c.amount, line.c.qty)
            .where(line.c.document_id == document_id)
            .order_by(line.c.line_no)
        )
    )
    matches = _matches(conn, row)
    return DocumentDetail(row, lines, matches)


# The original entry (I31: the lowest id of its source transaction) of each non-duplicate transaction without
# a transfer entry whose booking date is within the window and which has an amount in the document's
# currency; `reverse_matches` then decides.
_CANDIDATE_TXNS = text(
    """
    SELECT e.id, e.account_id, e.source_transaction_id, e.payee_id, e.document_id, e.description,
           st.booked_on, st.amount, st.currency, st.instructed_amount, st.instructed_currency,
           st.counterparty_name, st.purpose
      FROM ledger_entry AS e
      JOIN source_transaction AS st ON st.id = e.source_transaction_id
     WHERE st.duplicate_of IS NULL
       AND NOT EXISTS (SELECT 1 FROM ledger_entry AS lo
                        WHERE lo.source_transaction_id = e.source_transaction_id AND lo.id < e.id)
       AND NOT EXISTS (SELECT 1 FROM ledger_entry AS t
                        WHERE t.source_transaction_id = e.source_transaction_id AND t.type = 'transfer')
       AND st.booked_on BETWEEN :lo AND :hi
       AND (st.currency = :currency
            OR (st.instructed_currency = :currency AND st.instructed_amount IS NOT NULL))
    """
)

_UNIT_OK = text(f"SELECT u.id, u.unit_ok FROM ({units_sql(of_entries=True)}) AS u WHERE u.id = ANY(:ids)")  # noqa: S608


def _matches(conn: Connection, row: DocumentRow) -> tuple[DocumentMatch, ...]:
    document = load_document(conn, row.id)
    if document is None or fully_charged(document):
        return ()
    window = document_window(conn)
    candidates = conn.execute(
        _CANDIDATE_TXNS,
        {
            # a booking within [occurred_on - ahead, occurred_on + back]: the document is dated within
            # [booked_on - back, booked_on + ahead]
            "lo": row.occurred_on - timedelta(days=window.ahead),
            "hi": row.occurred_on + timedelta(days=window.back),
            "currency": row.currency,
        },
    ).all()
    by_entry = {int(r.id): r for r in candidates}
    txns = [
        DocTxn(
            entry_id=int(r.id),
            account_id=int(r.account_id),
            booked_on=r.booked_on,
            amount=int(r.amount),
            currency=str(r.currency).strip(),
            instructed_amount=r.instructed_amount,
            instructed_currency=r.instructed_currency.strip() if r.instructed_currency else None,
        )
        for r in candidates
    ]
    ordered = reverse_matches(document, txns, window)
    if not ordered:
        return ()
    state = {
        int(r.id): bool(r.unit_ok)
        for r in conn.execute(_UNIT_OK, {**units_binds(conn), "ids": [t.entry_id for t in ordered]})
    }
    out: list[DocumentMatch] = []
    for t in ordered:
        r = by_entry[t.entry_id]
        out.append(
            DocumentMatch(
                entry_id=t.entry_id,
                source_transaction_id=int(r.source_transaction_id),
                account_id=t.account_id,
                booked_on=t.booked_on,
                amount=t.amount,
                currency=t.currency,
                instructed_amount=t.instructed_amount,
                instructed_currency=t.instructed_currency,
                display_text=display_text(r.description, r.counterparty_name, r.purpose),
                payee_id=r.payee_id,
                document_id=r.document_id,
                confirmed=state.get(t.entry_id, False),
            )
        )
    return tuple(out)
