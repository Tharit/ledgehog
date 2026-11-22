"""Deleting a document (spec §5.5): the document and its lines go, in one write; the booking made from it
goes with the settling that ends the operation (spec §5.8), which removes any booking whose source is gone.
"""

from __future__ import annotations

from sqlalchemy import Engine, text

from app.core.settle.settle import SettleResult, settle
from app.utils.db.locks import lock_rows, lock_settle_shared, retry_on_deadlock


class DocumentNotFound(LookupError):
    def __init__(self, document_id: int) -> None:
        self.document_id = document_id
        super().__init__(f"document {document_id} does not exist")


def delete_document(engine: Engine, document_id: int) -> SettleResult:
    """Delete the document (its lines cascade), then settle: its booking, its entries and their tags go."""

    def run() -> None:
        with engine.begin() as conn:
            lock_settle_shared(conn)
            if not lock_rows(conn, "external_document", [document_id]):
                raise DocumentNotFound(document_id)
            conn.execute(text("DELETE FROM external_document WHERE id = :i"), {"i": document_id})

    retry_on_deadlock(run)
    return settle(engine)
