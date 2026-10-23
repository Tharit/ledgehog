"""The documents list and detail (architecture §4.1, spec §5.8, documents.md §9).

Reads only: no lock, no write, no settle. Documents are browsed here and linked only through a unit's
commit. SQLAlchemy Core composes the filter (architecture §5.2), as the ledger list does.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Connection,
    FromClause,
    Select,
    and_,
    case,
    column,
    exists,
    func,
    not_,
    or_,
    select,
    table,
    text,
)

from app.core.documents.filters import DocumentFilter
from app.core.importers.providers import importer_names
from app.core.ledger.entries import display_text
from app.core.ledger.sql import like_pattern
from app.core.matching.documents import DocInput, DocTxn, fully_charged, reverse_matches
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
    column("category_id"),
    column("category_key"),
)
carrier = table(
    "ledger_entry", column("id"), column("account_id"), column("source_transaction_id"), column("document_id")
)
src = table(
    "source_transaction",
    column("id"),
    column("booked_on"),
    column("amount"),
    column("currency"),
    column("instructed_amount"),
    column("instructed_currency"),
)
category = table("category", column("id"), column("name"))

# What carries each document: the entries whose `document_id` it is (a link sits on a transaction's original
# entry), their number and the sum of their transactions' amounts in the document's currency (a carrier with
# none counts nothing: `core.matching.amount_in`). A document no entry carries has no row here.
_amount_in_doc = case(
    (src.c.currency == doc.c.currency, src.c.amount),
    (
        and_(src.c.instructed_currency == doc.c.currency, src.c.instructed_amount.is_not(None)),
        src.c.instructed_amount,
    ),
    else_=0,
)
carried = (
    select(
        carrier.c.document_id,
        func.count().label("n"),
        func.sum(_amount_in_doc).label("charged"),
    )
    .select_from(
        carrier.join(src, src.c.id == carrier.c.source_transaction_id).join(
            doc, doc.c.id == carrier.c.document_id
        )
    )
    .where(carrier.c.document_id.is_not(None))
    .group_by(carrier.c.document_id)
    .subquery("carried")
)
_CARRIERS_N = func.coalesce(carried.c.n, 0)
# `core.matching.fully_charged`: carried, and the carriers' amounts reach the total by magnitude
_FULLY_CHARGED = and_(
    carried.c.n.is_not(None), func.abs(func.coalesce(carried.c.charged, 0)) >= func.abs(doc.c.total)
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
    carrier_count: int  # the transactions carrying it


@dataclass(frozen=True)
class DocumentLine:
    line_no: int
    description: str
    amount: int  # signed like the total
    qty: int | None
    category_id: int | None  # the model's answer for the line, None until it has answered
    category_name: str | None
    rationale: str | None  # the answer's rationale (also of "no category fits"); None where no answer


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
    carriers: tuple[Carrier, ...]  # by entry id
    fully_charged: bool  # its carriers' amounts reach its total (`core.matching.fully_charged`)
    matches: tuple[DocumentMatch, ...]  # empty for a fully charged document


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
    if flt.linked is not None:
        where.append(carried.c.n.is_not(None) if flt.linked else carried.c.n.is_(None))
    if flt.fully_charged is not None:
        where.append(_FULLY_CHARGED if flt.fully_charged else not_(_FULLY_CHARGED))
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
    return doc.outerjoin(carried, carried.c.document_id == doc.c.id)


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
            _CARRIERS_N.label("carrier_count"),
        )
        .select_from(_source())
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
            carrier_count=int(r.carrier_count),
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


def _answer(key: Any) -> tuple[bool, str | None]:
    """(answered, rationale) of a line's stored key: the model's answer carries its rationale in the key's
    `basis` and says `none` where nothing fits (spec §5.9)."""
    if not isinstance(key, Mapping):
        return False, None
    basis = key.get("basis")
    basis = basis if isinstance(basis, Mapping) else {}
    rationale = basis.get("rationale", key.get("rationale"))
    none = key.get("none") is True or basis.get("none") is True
    return none, rationale.strip() if isinstance(rationale, str) and rationale.strip() else None


def _lines(conn: Connection, document_id: int) -> tuple[DocumentLine, ...]:
    out: list[DocumentLine] = []
    for r in conn.execute(
        select(
            line.c.line_no,
            line.c.description,
            line.c.amount,
            line.c.qty,
            line.c.category_id,
            line.c.category_key,
            category.c.name,
        )
        .select_from(line.outerjoin(category, category.c.id == line.c.category_id))
        .where(line.c.document_id == document_id)
        .order_by(line.c.line_no)
    ):
        none, rationale = _answer(r.category_key)
        answered = r.category_id is not None or none  # a key whose category was deleted is no answer
        out.append(
            DocumentLine(
                r.line_no,
                r.description,
                r.amount,
                r.qty,
                r.category_id,
                r.name,
                rationale if answered else None,
            )
        )
    return tuple(out)


def _carriers(conn: Connection, document_id: int) -> tuple[Carrier, ...]:
    return tuple(
        Carrier(
            entry_id=r.id,
            source_transaction_id=r.source_transaction_id,
            account_id=r.account_id,
            booked_on=r.booked_on,
            amount=r.amount,
            currency=r.currency.strip(),
        )
        for r in conn.execute(
            select(
                carrier.c.id,
                carrier.c.account_id,
                carrier.c.source_transaction_id,
                src.c.booked_on,
                src.c.amount,
                src.c.currency,
            )
            .select_from(carrier.join(src, src.c.id == carrier.c.source_transaction_id))
            .where(carrier.c.document_id == document_id)
            .order_by(carrier.c.id)
        )
    )


def get_document(conn: Connection, document_id: int) -> DocumentDetail | None:
    """A document with its lines and carriers and, while it is not fully charged, the transactions it would
    match; None when there is no such document."""
    found = _build(conn.execute(_rows_stmt().where(doc.c.id == document_id)).all())
    if not found:
        return None
    row = found[0]
    full = load_document(conn, document_id)
    charged = full is not None and fully_charged(full)
    return DocumentDetail(
        row,
        _lines(conn, document_id),
        _carriers(conn, document_id),
        charged,
        () if full is None or charged else _matches(conn, row, full),
    )


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


def _matches(conn: Connection, row: DocumentRow, document: DocInput) -> tuple[DocumentMatch, ...]:
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
