"""What the booking step reads (architecture §5.2 step 2): clearance accounts, the two sources (documents,
and the charges decided as transfers to a clearance account) and the bookings made.

Set-based, one query each, nothing written. The step reads its sources under the exclusive settle lock and
locks none (architecture §5.2 'Lock order'): the charges are entries of accounts that are not clearance
accounts, which only the writes lock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Connection, text

from app.core.bookings.documents import ClearanceAccount, DocumentFacts
from app.core.bookings.transfers import TRANSFER_SOURCE, ChargeFacts
from app.core.plugins.classifier import STANDING_PASSES


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
            "SELECT d.id, d.provider, d.reference, d.occurred_on, d.total, d.currency,"
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
            out[r.id] = DocumentFacts(r.id, r.provider, r.reference, r.occurred_on, r.total, r.currency)
            lines[r.id] = []
        if r.description is not None:
            lines[r.id].append((r.description, r.amount))
    return [
        DocumentFacts(d.id, d.provider, d.reference, d.occurred_on, d.total, d.currency, tuple(lines[d.id]))
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
    """A booking, as stored: its row and its entries in id order (their position). `kind` and `key` name its
    source (`document` and the document's id, `transfer` and the charge's entry id). `paired` (a transfer
    booking): its entry and the charge point at each other."""

    id: int
    kind: str
    key: int
    account_id: int
    currency: str
    booked_on: date
    amount: int
    purpose: str | None
    counterparty_name: str | None
    entries: tuple[StoredEntry, ...]
    paired: bool = True


BookingKey = tuple[str, int]  # (kind, the source's id)


def load_bookings(conn: Connection) -> dict[BookingKey, StoredBooking]:
    """Every booking, by its source (`(kind, id)`)."""
    rows = conn.execute(
        text(
            "SELECT s.id, s.source_id, s.account_id, s.currency, s.booked_on, s.amount, s.purpose,"
            " s.counterparty_name, e.id AS entry_id, e.amount AS entry_amount, e.booked_on AS entry_on,"
            " e.source_text,"
            " (s.source_id NOT LIKE :transfer_prefix OR EXISTS ("
            "    SELECT 1 FROM ledger_entry b JOIN ledger_entry c ON c.id = b.counterpart_entry_id"
            "     WHERE b.source_transaction_id = s.id AND c.counterpart_entry_id = b.id"
            "       AND c.id = CAST(split_part(s.source_id, ':', 2) AS bigint))) AS paired"
            " FROM source_transaction s LEFT JOIN ledger_entry e ON e.source_transaction_id = s.id"
            " WHERE s.origin = 'booking' ORDER BY s.id, e.id"
        ),
        {"transfer_prefix": f"{TRANSFER_SOURCE}:%"},
    )
    heads: dict[int, Any] = {}
    entries: dict[int, list[StoredEntry]] = {}
    for r in rows:
        if r.id not in heads:
            heads[r.id] = r
            entries[r.id] = []
        if r.entry_id is not None:
            entries[r.id].append(StoredEntry(r.entry_id, r.entry_amount, r.entry_on, r.source_text))
    out: dict[BookingKey, StoredBooking] = {}
    for st_id, r in heads.items():
        kind, _, key = r.source_id.partition(":")
        out[(kind, int(key))] = StoredBooking(
            id=st_id,
            kind=kind,
            key=int(key),
            account_id=r.account_id,
            currency=r.currency,
            booked_on=r.booked_on,
            amount=r.amount,
            purpose=r.purpose,
            counterparty_name=r.counterparty_name,
            entries=tuple(entries[st_id]),
            paired=bool(r.paired),
        )
    return out


def load_charges(conn: Connection) -> list[ChargeFacts]:
    """The charges that call for a counter-leg (spec §5.7): a transfer entry, not a duplicate's, on an
    account that is not a clearance account, whose counter-account is a clearance account, its type and
    counter-account decided under standing keys, and not paired with anything but its own booking."""
    return [
        ChargeFacts(
            entry_id=r.id,
            account_id=r.account_id,
            currency=r.currency,
            amount=r.amount,
            booked_on=r.booked_on,
            purpose=r.purpose,
            counter_account_id=r.counter_account_id,
            instructed_currency=r.instructed_currency,
            instructed_amount=r.instructed_amount,
        )
        for r in conn.execute(
            text(
                "SELECT e.id, e.account_id, e.currency, e.amount, e.booked_on, s.purpose,"
                " e.counter_account_id, s.instructed_currency, s.instructed_amount"
                " FROM ledger_entry e"
                " JOIN source_transaction s ON s.id = e.source_transaction_id"
                " JOIN account c ON c.id = e.counter_account_id AND c.kind = 'clearance'"
                " JOIN account o ON o.id = e.account_id AND o.kind <> 'clearance'"
                " LEFT JOIN ledger_entry p ON p.id = e.counterpart_entry_id"
                " LEFT JOIN source_transaction ps ON ps.id = p.source_transaction_id"
                " WHERE e.type = 'transfer' AND s.duplicate_of IS NULL"
                "   AND e.derivation #>> '{type,pass}' = ANY(:standing)"
                "   AND e.derivation #>> '{counter_account,pass}' = ANY(:standing)"
                "   AND (e.counterpart_entry_id IS NULL"
                "        OR (ps.origin = 'booking' AND ps.source_id = :prefix || CAST(e.id AS text)))"
                " ORDER BY e.id"
            ),
            {"standing": sorted(STANDING_PASSES), "prefix": f"{TRANSFER_SOURCE}:"},
        )
    ]
