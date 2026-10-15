"""A transfer leg as the matcher reads it: plain values, no database (spec §5.7)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.core.ingest.identity import canonical_text
from app.core.plugins.classifier import EntryInput


@dataclass(frozen=True, slots=True)
class Leg:
    """One entry the matcher considers. Amounts are signed minor units.

    `purpose` is already canonical (§5.2). `counter_account_id` is whatever the entry holds under any
    key, proposals included, or None. `instructed_amount` is in `instructed_currency` (§3.8).
    """

    entry_id: int
    account_id: int
    currency: str
    amount: int
    booked_on: date
    type: str | None = "transfer"
    counter_account_id: int | None = None
    end_to_end_id: str | None = None
    instructed_amount: int | None = None
    instructed_currency: str | None = None
    purpose: str = ""


def leg_of(entry: EntryInput, *, type: str | None, counter_account_id: int | None) -> Leg:  # noqa: A002
    """A leg from resolution's input and the entry's current type and counter-account."""
    return Leg(
        entry_id=entry.entry_id,
        account_id=entry.account_id,
        currency=entry.currency,
        amount=entry.amount,
        booked_on=entry.booked_on,
        type=type,
        counter_account_id=counter_account_id,
        end_to_end_id=entry.end_to_end_id,
        instructed_amount=entry.instructed_amount,
        instructed_currency=entry.instructed_currency,
        purpose=canonical_text(entry.purpose),
    )
