"""The source-transaction fields an entry read carries (architecture §4.1 `source`, D206).

One shape, defined once: the ledger list, `GET /api/ledger/entries/{id}` and the rows of a rule's
preview all hold an entry's source as this record. Never the raw record, never the content hash.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceFields:
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
