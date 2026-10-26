"""The document list and detail (spec §5.8, architecture §4.1): read-only queries."""

from app.core.documents.filters import DocumentFilter
from app.core.documents.read import (
    DocumentDetail,
    DocumentLine,
    DocumentPage,
    DocumentRow,
    get_document,
    list_documents,
    provider_names,
)

__all__ = [
    "DocumentDetail",
    "DocumentFilter",
    "DocumentLine",
    "DocumentPage",
    "DocumentRow",
    "get_document",
    "list_documents",
    "provider_names",
]
