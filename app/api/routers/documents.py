"""Documents (architecture §4.1, spec §5.8): `GET /api/documents` and `GET /api/documents/{id}`.

Reads: no lock, no write, no settle. A document is linked only through a unit's commit. Money travels as
`{"amount": <integer minor units>, "currency": <code>}`; a refund document is positive. The review
panel's pick by hand reuses the list with the `provider` and `linked=false` filters.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, StringConstraints

from app.api.errors import map_error
from app.api.ids import MAX_ID, PathId
from app.api.routers.accounts import CurrencyCode, Money
from app.api.session import CurrentUser, EngineDep
from app.core.documents import (
    Carrier,
    DocumentDetail,
    DocumentFilter,
    DocumentLine,
    DocumentMatch,
    DocumentRow,
    get_document,
    list_documents,
)
from app.core.ledger import InvalidFilter

router = APIRouter(prefix="/api/documents", tags=["documents"])

map_error(
    InvalidFilter,
    422,
    "validation_error",
    details=lambda e: [{"location": ["query", e.parameter], "message": str(e), "type": "invalid_filter"}],
)

SearchText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class CarrierOut(BaseModel):
    """The transaction carrying a document: its original entry, which opens the review panel."""

    entry_id: int
    source_transaction_id: int
    account_id: int
    booked_on: date
    amount: Money

    @staticmethod
    def of(c: Carrier) -> CarrierOut:
        return CarrierOut(
            entry_id=c.entry_id,
            source_transaction_id=c.source_transaction_id,
            account_id=c.account_id,
            booked_on=c.booked_on,
            amount=Money(amount=c.amount, currency=c.currency),
        )


class DocumentOut(BaseModel):
    id: int
    version: int  # what a commit picking it carries (spec §5.5)
    provider: str
    external_id: str
    importer_instance_id: int | None
    occurred_on: date
    total: Money
    merchant_name: str | None
    title: str | None
    line_count: int
    carrier: CarrierOut | None  # null: carried by no entry

    @staticmethod
    def of(r: DocumentRow) -> DocumentOut:
        return DocumentOut(
            id=r.id,
            version=r.version,
            provider=r.provider,
            external_id=r.external_id,
            importer_instance_id=r.importer_instance_id,
            occurred_on=r.occurred_on,
            total=Money(amount=r.total, currency=r.currency),
            merchant_name=r.merchant_name,
            title=r.title,
            line_count=r.line_count,
            carrier=None if r.carrier is None else CarrierOut.of(r.carrier),
        )


class DocumentPageOut(BaseModel):
    documents: list[DocumentOut]
    total: int  # documents matching the filter, whatever the page
    limit: int
    offset: int


class DocumentLineOut(BaseModel):
    line_no: int
    description: str
    amount: Money  # in the document's currency, signed like the total
    qty: int | None

    @staticmethod
    def of(line: DocumentLine, currency: str) -> DocumentLineOut:
        return DocumentLineOut(
            line_no=line.line_no,
            description=line.description,
            amount=Money(amount=line.amount, currency=currency),
            qty=line.qty,
        )


class DocumentMatchOut(BaseModel):
    """A transaction the document would match (documents.md §9), with its unit's state."""

    entry_id: int  # the original entry: opens the review panel with the document picked
    source_transaction_id: int
    account_id: int
    booked_on: date
    amount: Money
    instructed_amount: Money | None
    display_text: str | None
    payee_id: int | None
    document_id: int | None  # the document it already carries; picking replaces that link
    confirmed: bool  # its unit is confirmed

    @staticmethod
    def of(m: DocumentMatch) -> DocumentMatchOut:
        instructed = (
            None
            if m.instructed_amount is None or m.instructed_currency is None
            else Money(amount=m.instructed_amount, currency=m.instructed_currency)
        )
        return DocumentMatchOut(
            entry_id=m.entry_id,
            source_transaction_id=m.source_transaction_id,
            account_id=m.account_id,
            booked_on=m.booked_on,
            amount=Money(amount=m.amount, currency=m.currency),
            instructed_amount=instructed,
            display_text=m.display_text,
            payee_id=m.payee_id,
            document_id=m.document_id,
            confirmed=m.confirmed,
        )


class DocumentDetailOut(DocumentOut):
    lines: list[DocumentLineOut]
    matches: list[DocumentMatchOut]  # for a document carried by no entry; empty otherwise

    @staticmethod
    def detail(d: DocumentDetail) -> DocumentDetailOut:
        base = DocumentOut.of(d.document)
        return DocumentDetailOut(
            **base.model_dump(),
            lines=[DocumentLineOut.of(line, d.document.currency) for line in d.lines],
            matches=[DocumentMatchOut.of(m) for m in d.matches],
        )


@router.get("")
def list_documents_view(
    user: CurrentUser,
    engine: EngineDep,
    provider: Annotated[list[str] | None, Query()] = None,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    amount_min: Annotated[int | None, Query(ge=0, le=2**63 - 1)] = None,
    amount_max: Annotated[int | None, Query(ge=0, le=2**63 - 1)] = None,
    currency: CurrencyCode | None = None,
    q: SearchText | None = None,
    linked: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=MAX_ID)] = 0,
) -> DocumentPageOut:
    flt = DocumentFilter(
        providers=tuple(provider or ()),
        date_from=from_,
        date_to=to,
        amount_min=amount_min,
        amount_max=amount_max,
        currency=currency,
        text=q,
        linked=linked,
    )
    with engine.connect() as conn:
        page = list_documents(conn, flt, limit=limit, offset=offset)
    return DocumentPageOut(
        documents=[DocumentOut.of(d) for d in page.documents],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


class DocumentMissing(LookupError):
    def __init__(self, document_id: int) -> None:
        self.document_id = document_id
        super().__init__(f"document {document_id} does not exist")


map_error(DocumentMissing, 404, "not_found")


@router.get("/{document_id}")
def get_document_view(document_id: PathId, user: CurrentUser, engine: EngineDep) -> DocumentDetailOut:
    """A document with its lines and, when no entry carries it, the transactions it would match."""
    with engine.connect() as conn:
        found = get_document(conn, document_id)
    if found is None:
        raise DocumentMissing(document_id)
    return DocumentDetailOut.detail(found)
