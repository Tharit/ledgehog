"""Importer-facing record types (architecture §5.5, spec §5.1).

Only what ingest needs so far; the protocol itself and the error taxonomy are
added by the importer tasks. Importers never dedup or hash: they emit
`IncomingRow`s and ingest derives identity from them (spec §5.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True, slots=True)
class IncomingRow:
    """One final, booked transaction record in ledger sign convention.

    Field names follow `source_transaction`. `amount_minor` is signed integer
    minor units and never zero: the importer drops zero
    bookings and reports their count (`filtered`); ingest fails the run on one (`zero_amount`).
    """

    amount_minor: int
    currency: str
    booked_on: date
    source_format: str
    raw: Any
    value_on: date | None = None
    instructed_amount_minor: int | None = None
    instructed_currency: str | None = None
    counterparty_ref: str | None = None
    counterparty_bic: str | None = None
    counterparty_name: str | None = None
    purpose: str | None = None
    end_to_end_id: str | None = None
    mandate_ref: str | None = None
    booking_text: str | None = None
    # The id the SOURCE assigns, None when it does not (spec §5.2).
    source_id: str | None = None
