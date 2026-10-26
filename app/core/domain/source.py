"""The source-transaction fields an entry read carries (architecture §4.1 `source`, D206).

One shape, defined once: the ledger list, `GET /api/ledger/entries/{id}` and the rows of a rule's
preview all hold an entry's source as this record. Never the raw record, never the content hash.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class BookingRef:
    """A booking's source, read only for navigation (spec §5.8, architecture §4.1): `document` with the
    document's id, provider and external id, or `transfer` with the charge's entry id and its account."""

    kind: str  # `document` | `transfer`
    id: int  # the document's id, or the charge's entry id
    provider: str | None = None  # document
    external_id: str | None = None  # document
    account_id: int | None = None  # transfer: the charge's account


@dataclass(frozen=True, slots=True)
class SourceFields:
    amount: int  # the source transaction's own signed amount in minor units, in `currency`
    currency: str  # (a split part's entry carries only its part; this is the whole)
    counterparty_name: str | None = None
    counterparty_ref: str | None = None
    counterparty_bic: str | None = None
    purpose: str | None = None
    booking_text: str | None = None
    end_to_end_id: str | None = None
    mandate_ref: str | None = None
    instructed_amount: int | None = None  # signed minor units, in `instructed_currency`
    instructed_currency: str | None = None
    source_format: str | None = None
    booking: BookingRef | None = None  # a booking's source only; filled where the row is read for the list

    @staticmethod
    def of_row(r: Any) -> SourceFields:
        """From a row exposing the source columns (`source_amount`, `source_currency` and the rest)."""
        return SourceFields(
            amount=r.source_amount,
            currency=r.source_currency,
            counterparty_name=r.counterparty_name,
            counterparty_ref=r.counterparty_ref,
            counterparty_bic=r.counterparty_bic,
            purpose=r.purpose,
            booking_text=r.booking_text,
            end_to_end_id=r.end_to_end_id,
            mandate_ref=r.mandate_ref,
            instructed_amount=r.instructed_amount,
            instructed_currency=r.instructed_currency,
            source_format=r.source_format,
        )
