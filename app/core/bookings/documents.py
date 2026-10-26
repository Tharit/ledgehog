"""What a document calls for (spec §5.8 'Documents as a booking source', features/documents.md §1-§2).

Pure functions over plain facts, no database: which clearance account takes a document, why one is not
booked, and the booking's fields and entries. The step's reads and writes are `load.py` and `write.py`;
the documents read model of the API uses `not_booked` too.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

from app.core.bookings.spread import spread

DOCUMENT_SOURCE = "document"

# the reasons a document is not booked, in the order they apply (features/documents.md §1)
ZERO_TOTAL = "zero_total"
NO_ACCOUNT = "no_account"
NO_START = "no_start"
BEFORE_START = "before_start"


def document_source_id(document_id: int) -> str:
    """The `source_id` of the booking made from a document."""
    return f"{DOCUMENT_SOURCE}:{document_id}"


@dataclass(frozen=True, slots=True)
class ClearanceAccount:
    """A clearance account as a document sees it: its currency, its providers, and its start, the date of
    its earliest balance record (None while it has none)."""

    id: int
    currency: str
    providers: tuple[str, ...]
    start: date | None


@dataclass(frozen=True, slots=True)
class DocumentFacts:
    id: int
    provider: str
    external_id: str
    occurred_on: date
    total: int
    currency: str
    lines: tuple[tuple[str, int], ...] = ()  # (description, amount), in line order


@dataclass(frozen=True, slots=True)
class NotBooked:
    """Why a document is not booked, with what the reason needs to say what to do about it."""

    reason: str
    currency: str | None = None  # no_account: the provider is not taken in this currency
    account_id: int | None = None  # no_start, before_start
    start: date | None = None  # before_start


def provider_key(provider: str, currency: str) -> tuple[str, str]:
    """How a provider is compared: without regard to case, per currency (`ux_clearance_provider`)."""
    return (provider.strip().lower(), currency)


def provider_index(accounts: Iterable[ClearanceAccount]) -> dict[tuple[str, str], ClearanceAccount]:
    """The account that takes each (provider, currency); a provider is taken by at most one per currency."""
    return {provider_key(p, a.currency): a for a in accounts for p in a.providers}


def account_for(
    provider: str, currency: str, index: Mapping[tuple[str, str], ClearanceAccount]
) -> ClearanceAccount | None:
    return index.get(provider_key(provider, currency))


def not_booked(doc: DocumentFacts, index: Mapping[tuple[str, str], ClearanceAccount]) -> NotBooked | None:
    """None when a document not yet booked is to be booked; else the first reason that applies."""
    if doc.total == 0:
        return NotBooked(ZERO_TOTAL)
    account = account_for(doc.provider, doc.currency, index)
    if account is None:
        return NotBooked(NO_ACCOUNT, currency=doc.currency)
    if account.start is None:
        return NotBooked(NO_START, account_id=account.id)
    if doc.occurred_on <= account.start:
        return NotBooked(BEFORE_START, account_id=account.id, start=account.start)
    return None


def purpose_of(doc: DocumentFacts) -> str:
    return f"{'Refund' if doc.total > 0 else 'Order'} {doc.external_id}"


@dataclass(frozen=True, slots=True)
class EntryPlan:
    amount: int
    source_text: str | None


@dataclass(frozen=True, slots=True)
class BookingPlan:
    """The booking a document calls for on its account: the row's fields and its entries, in order."""

    source_id: str
    booked_on: date
    amount: int
    purpose: str
    counterparty_name: str
    entries: tuple[EntryPlan, ...]


def entries_of(doc: DocumentFacts) -> tuple[EntryPlan, ...]:
    """One entry per entry line (features/documents.md §2), each with its line's description as text."""
    shares = spread(doc.total, [amount for _, amount in doc.lines])
    return tuple(EntryPlan(s.amount, None if s.line is None else doc.lines[s.line][0]) for s in shares)


def booking_plan(doc: DocumentFacts) -> BookingPlan:
    """What a document of a total other than 0 calls for, whichever account it is on."""
    return BookingPlan(
        source_id=document_source_id(doc.id),
        booked_on=doc.occurred_on,
        amount=doc.total,
        purpose=purpose_of(doc),
        counterparty_name=doc.provider,
        entries=entries_of(doc),
    )
