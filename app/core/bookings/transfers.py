"""What a charge decided as a transfer to a clearance account calls for (spec §5.7 'Transfers to a clearance
account', §5.8): its counter-leg, a booking on that account.

Pure functions over plain facts, no database, like `documents.py`: which charges are sources, and the
booking each calls for. The step's reads and writes are `load.py` and `write.py`; the preview's simulation
of settling (`core/units/overlay.py`) uses the same functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.core.bookings.documents import BookingPlan, EntryPlan, PairPlan

TRANSFER_SOURCE = "transfer"


def transfer_source_id(entry_id: int) -> str:
    """The `source_id` of the booking made as the counter-leg of a charge."""
    return f"{TRANSFER_SOURCE}:{entry_id}"


@dataclass(frozen=True, slots=True)
class ChargeFacts:
    """A charge: a transfer entry on an account that is not a clearance account, decided as a transfer to
    `counter_account_id` under standing keys (type and counter-account). `instructed_*` are its source's."""

    entry_id: int
    account_id: int
    currency: str
    amount: int  # the entry's, signed
    booked_on: date
    purpose: str | None
    counter_account_id: int
    instructed_currency: str | None = None
    instructed_amount: int | None = None


def arrival_currency(charge: ChargeFacts) -> str:
    """The currency the money arrived in by the charge's own report: its instructed currency, else its own."""
    return charge.instructed_currency or charge.currency


def counter_amount(charge: ChargeFacts) -> int | None:
    """The amount of the counter-leg, negated: the charge's in one currency; across currencies the instructed
    amount (the charge's source's). None where the charge says no amount in its arrival currency."""
    if charge.instructed_currency is None:
        return -charge.amount
    if charge.instructed_amount is None:
        return None
    return -charge.instructed_amount


def transfer_booking_plan(
    charge: ChargeFacts, account_currency: str | None, account_start: date | None, booked: bool = False
) -> BookingPlan | None:
    """The booking `charge` calls for on the clearance account it points at (`account_currency` its currency,
    None where it points at none; `account_start` its start), None when it calls for none: the account is not
    a clearance account, or not in the currency the money arrived in (a clearance account takes a charge only
    in that currency; the user's choice of another, with an amount received typed, does not apply), or the
    charge is dated on or before the account's start (or it has none): the leg stays unpaired, in review
    (spec §5.7). The start decides only where a charge not yet booked goes: `booked` (the charge already
    has its booking on this account) skips that check, so a start change never removes a booking (§5.8)."""
    if account_currency is None or account_currency != arrival_currency(charge):
        return None
    if not booked and (account_start is None or charge.booked_on <= account_start):
        return None
    amount = counter_amount(charge)
    if amount is None or amount == 0:
        return None
    return BookingPlan(
        source_id=transfer_source_id(charge.entry_id),
        booked_on=charge.booked_on,
        amount=amount,
        purpose=charge.purpose,
        counterparty_name=None,
        entries=(EntryPlan(amount, None),),
        pair=PairPlan(charge.entry_id, charge.account_id),
    )
