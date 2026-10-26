"""Documents (architecture §4.1, spec §5.8): `GET /api/documents` and `GET /api/documents/{id}`.

Reads: no lock, no write, no settle. Money travels as `{"amount": <integer minor units>, "currency":
<code>}`; a refund document is positive.
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
    DocumentDetail,
    DocumentFilter,
    DocumentLine,
    DocumentRow,
    get_document,
    list_documents,
    provider_names,
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


class DocumentOut(BaseModel):
    id: int
    version: int  # detects a conflicting edit (spec §5.5)
    provider: str
    external_id: str
    importer_instance_id: int | None
    occurred_on: date
    total: Money
    merchant_name: str | None
    title: str | None
    line_count: int

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


class DocumentDetailOut(DocumentOut):
    lines: list[DocumentLineOut]

    @staticmethod
    def detail(d: DocumentDetail) -> DocumentDetailOut:
        base = DocumentOut.of(d.document)
        return DocumentDetailOut(
            **base.model_dump(),
            lines=[DocumentLineOut.of(line, d.document.currency) for line in d.lines],
        )


class DocumentProvidersOut(BaseModel):
    providers: list[str]  # sorted; the names importers give and the providers of stored documents


@router.get("/providers")
def list_document_providers(user: CurrentUser, engine: EngineDep) -> DocumentProvidersOut:
    """Suggestions for a clearance account's provider list and the documents filter (any may be named)."""
    with engine.connect() as conn:
        return DocumentProvidersOut(providers=provider_names(conn))


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
    """A document with its lines."""
    with engine.connect() as conn:
        found = get_document(conn, document_id)
    if found is None:
        raise DocumentMissing(document_id)
    return DocumentDetailOut.detail(found)
