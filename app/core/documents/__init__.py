"""The document list and detail (spec §5.8, architecture §4.1): read-only queries."""

from app.core.documents.delete import DocumentNotFound, delete_document
from app.core.documents.filters import DocumentFilter
from app.core.documents.read import (
    BookingEntry,
    DocumentBooking,
    DocumentDetail,
    DocumentLine,
    DocumentPage,
    DocumentRow,
    get_document,
    list_documents,
    provider_names,
)

__all__ = [
    "BookingEntry",
    "DocumentBooking",
    "DocumentDetail",
    "DocumentFilter",
    "DocumentNotFound",
    "DocumentLine",
    "DocumentPage",
    "DocumentRow",
    "delete_document",
    "get_document",
    "list_documents",
    "provider_names",
]
