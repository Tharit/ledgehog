"""Builders for the booking tests: clearance accounts, document deliveries, and reading the ledger back."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from types import EllipsisType
from typing import Any

from sqlalchemy import Engine, text

from app.core.accounts import create_account
from app.core.ingest.documents import DocumentRunResult, Redelivery, ingest_documents
from app.core.ingest.run import start_run
from app.core.plugins.importer import IncomingDocument, IncomingDocumentLine
from tests.plugins.importers.fakes import document, line

START = date(2026, 1, 31)
THROUGH = date(2026, 12, 31)

__all__ = ["START", "Scene", "doc", "line"]


def doc(
    source_id: str = "A1",
    *lines: IncomingDocumentLine,
    total: int | None = None,
    provider: str = "Amazon",
    occurred_on: date = date(2026, 2, 1),
    currency: str = "EUR",
    reference: str | None | EllipsisType = ...,
) -> IncomingDocument:
    """An order of `lines`; the total is the lines' sum unless given. No lines and no total: one line of
    -1000; no lines and a total: a document without lines. Its reference is its `source_id` unless given
    (None: it has none)."""
    lines = lines or (() if total is not None else (line("Item", -1000),))
    return document(
        source_id,
        reference=source_id if reference is ... else reference,
        provider=provider,
        occurred_on=occurred_on,
        currency=currency,
        total_minor=sum(ln.amount_minor for ln in lines) if total is None else total,
        lines=lines,
    )


@dataclass
class Scene:
    engine: Engine

    def clearance(
        self,
        name: str = "Amazon.de",
        *,
        currency: str = "EUR",
        start: date = START,
        providers: Sequence[str] = ("Amazon",),
    ) -> int:
        return create_account(
            self.engine, name=name, kind="clearance", currency=currency, start_date=start, providers=providers
        )

    def deliver(self, *docs: IncomingDocument, redelivery: Redelivery = "replace") -> DocumentRunResult:
        run_id = start_run(self.engine, None, "documents", importer="fake")
        return ingest_documents(self.engine, run_id, docs, covered_through=THROUGH, redelivery=redelivery)

    def q(self, sql: str, **params: Any) -> list[Any]:
        with self.engine.connect() as conn:
            return list(conn.execute(text(sql), params).all())

    def document_id(self, source_id: str = "A1") -> int:
        return int(self.q("SELECT id FROM external_document WHERE source_id = :e", e=source_id)[0].id)

    def booking(self, source_id: str = "A1") -> Any | None:
        rows = self.q(
            "SELECT s.* FROM source_transaction s WHERE s.source_id = :s",
            s=f"document:{self.document_id(source_id)}",
        )
        return rows[0] if rows else None

    def bookings(self) -> list[Any]:
        return self.q("SELECT * FROM source_transaction WHERE origin = 'booking' ORDER BY id")

    def entries(self, source_id: str = "A1") -> list[Any]:
        return self.q(
            "SELECT e.* FROM ledger_entry e JOIN source_transaction s ON s.id = e.source_transaction_id"
            " WHERE s.source_id = :s ORDER BY e.id",
            s=f"document:{self.document_id(source_id)}",
        )

    def balance(self, account_id: int) -> int:
        return int(
            self.q("SELECT balance FROM v_account_balance WHERE account_id = :a", a=account_id)[0].balance
        )

    def exec(self, sql: str, **params: Any) -> None:
        with self.engine.begin() as conn:
            conn.execute(text(sql), params)

    def exec_returning(self, sql: str, **params: Any) -> int:
        with self.engine.begin() as conn:
            return int(conn.execute(text(sql), params).scalar_one())

    def category(self, name: str = "Books") -> int:
        with self.engine.begin() as conn:
            return int(
                conn.execute(
                    text("INSERT INTO category (name, kind) VALUES (:n, 'expense') RETURNING id"), {"n": name}
                ).scalar_one()
            )
