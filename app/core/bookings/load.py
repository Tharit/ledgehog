"""What the booking step reads (architecture §5.2 step 2): clearance accounts, documents, document bookings.

Set-based, one query each, nothing written. The step reads documents under the exclusive settle lock and
locks none (architecture §5.2 'Lock order').
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Connection, text

from app.core.bookings.documents import DOCUMENT_SOURCE, ClearanceAccount, DocumentFacts


def load_clearance_accounts(conn: Connection) -> list[ClearanceAccount]:
    """Every clearance account with its providers and its start (its earliest balance record's date)."""
    return [
        ClearanceAccount(r.id, r.currency, tuple(r.providers), r.start)
        for r in conn.execute(
            text(
                "SELECT a.id, a.currency,"
                " COALESCE((SELECT array_agg(p.provider ORDER BY p.provider) FROM clearance_provider p"
                "           WHERE p.account_id = a.id), '{}') AS providers,"
                " (SELECT min(r.balance_on) FROM balance_record r WHERE r.account_id = a.id) AS start"
                " FROM account a WHERE a.kind = 'clearance' ORDER BY a.id"
            )
        )
    ]


def load_documents(conn: Connection, ids: list[int] | None = None) -> list[DocumentFacts]:
    """The documents (all, or the given ids) with their lines in line order, by id."""
    where = "" if ids is None else " WHERE d.id = ANY(:ids)"
    rows = conn.execute(
        text(
            "SELECT d.id, d.provider, d.external_id, d.occurred_on, d.total, d.currency,"
            " l.description, l.amount"
            " FROM external_document d LEFT JOIN external_document_line l ON l.document_id = d.id"
            f"{where} ORDER BY d.id, l.line_no"  # noqa: S608
        ),
        {} if ids is None else {"ids": ids},
    )
    out: dict[int, DocumentFacts] = {}
    lines: dict[int, list[tuple[str, int]]] = {}
    for r in rows:
        if r.id not in out:
            out[r.id] = DocumentFacts(r.id, r.provider, r.external_id, r.occurred_on, r.total, r.currency)
            lines[r.id] = []
        if r.description is not None:
            lines[r.id].append((r.description, r.amount))
    return [
        DocumentFacts(d.id, d.provider, d.external_id, d.occurred_on, d.total, d.currency, tuple(lines[d.id]))
        for d in out.values()
    ]


@dataclass(frozen=True, slots=True)
class StoredEntry:
    id: int
    amount: int
    booked_on: date
    source_text: str | None


@dataclass(frozen=True, slots=True)
class StoredBooking:
    """A booking made from a document, as stored: its row and its entries in id order (their position)."""

    id: int
    document_id: int
    account_id: int
    currency: str
    booked_on: date
    amount: int
    purpose: str | None
    counterparty_name: str | None
    entries: tuple[StoredEntry, ...]


def load_document_bookings(conn: Connection) -> dict[int, StoredBooking]:
    """The bookings made from documents, by document id."""
    rows = conn.execute(
        text(
            "SELECT s.id, s.source_id, s.account_id, s.currency, s.booked_on, s.amount, s.purpose,"
            " s.counterparty_name, e.id AS entry_id, e.amount AS entry_amount, e.booked_on AS entry_on,"
            " e.source_text"
            " FROM source_transaction s LEFT JOIN ledger_entry e ON e.source_transaction_id = s.id"
            " WHERE s.origin = 'booking' AND s.source_id LIKE :prefix ORDER BY s.id, e.id"
        ),
        {"prefix": f"{DOCUMENT_SOURCE}:%"},
    )
    heads: dict[int, Any] = {}
    entries: dict[int, list[StoredEntry]] = {}
    for r in rows:
        if r.id not in heads:
            heads[r.id] = r
            entries[r.id] = []
        if r.entry_id is not None:
            entries[r.id].append(StoredEntry(r.entry_id, r.entry_amount, r.entry_on, r.source_text))
    out: dict[int, StoredBooking] = {}
    for st_id, r in heads.items():
        doc_id = int(r.source_id.split(":", 1)[1])
        out[doc_id] = StoredBooking(
            id=st_id,
            document_id=doc_id,
            account_id=r.account_id,
            currency=r.currency,
            booked_on=r.booked_on,
            amount=r.amount,
            purpose=r.purpose,
            counterparty_name=r.counterparty_name,
            entries=tuple(entries[st_id]),
        )
    return out
