"""What the booking step does: the difference between what the sources call for and what is booked (spec
§5.8, features/documents.md §3-§4). Pure: facts in, a plan of writes out.

A document not yet booked is booked when `not_booked` says nothing against it. A booking follows its
document while the document's total is not 0 and its currency is the account's: its row and entries are
re-derived, the entries matched to the entry lines by position. Otherwise it is removed, and the document,
now not booked, is booked again in the same plan where it calls for it (another currency's account).
Where a booked document sits never changes with the providers or the start.

A charge decided as a transfer to a clearance account (`transfers.py`) is booked as its counter-leg on that
account in the same way: the booking follows the charge while it points at the same account and the
account takes it, is removed otherwise (and booked where the charge now points), and is paired with it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from app.core.bookings.documents import (
    DOCUMENT_SOURCE,
    BookingPlan,
    ClearanceAccount,
    DocumentFacts,
    EntryPlan,
    account_for,
    booking_plan,
    not_booked,
    provider_index,
)
from app.core.bookings.load import BookingKey, StoredBooking
from app.core.bookings.transfers import TRANSFER_SOURCE, ChargeFacts, transfer_booking_plan


@dataclass(frozen=True, slots=True)
class EntryUpdate:
    """An entry that keeps its position, with the values it takes. `text_changed` is a change of input:
    the entry resolves afresh (spec §5.9)."""

    entry_id: int
    amount: int
    booked_on: date
    source_text: str | None
    text_changed: bool


@dataclass(frozen=True, slots=True)
class Rederivation:
    booking: StoredBooking
    plan: BookingPlan
    row_changed: bool
    updates: tuple[EntryUpdate, ...]  # only entries that differ
    surplus: tuple[int, ...]  # entries whose position the new computation no longer has
    added: tuple[EntryPlan, ...]  # new positions
    repair_pair: bool = False  # a transfer booking whose pair with its charge is broken: made again


@dataclass(frozen=True, slots=True)
class Sync:
    create: tuple[tuple[int, BookingPlan], ...] = ()  # (account id, plan)
    rederive: tuple[Rederivation, ...] = ()
    remove: tuple[StoredBooking, ...] = ()

    @property
    def empty(self) -> bool:
        return not (self.create or self.rederive or self.remove)

    def account_ids(self) -> list[int]:
        """The clearance accounts the plan writes on, ascending."""
        return sorted(
            {a for a, _ in self.create}
            | {r.booking.account_id for r in self.rederive}
            | {b.account_id for b in self.remove}
        )


def rederivation(booking: StoredBooking, plan: BookingPlan) -> Rederivation | None:
    """What re-deriving `booking` to `plan` (what its source calls for) writes, None when it is as called
    for."""
    row_changed = (
        booking.booked_on != plan.booked_on
        or booking.amount != plan.amount
        or booking.purpose != plan.purpose
        or booking.counterparty_name != plan.counterparty_name
    )
    stored, wanted = booking.entries, plan.entries
    updates = tuple(
        EntryUpdate(e.id, w.amount, plan.booked_on, w.source_text, e.source_text != w.source_text)
        for e, w in zip(stored, wanted, strict=False)
        if (e.amount, e.booked_on, e.source_text) != (w.amount, plan.booked_on, w.source_text)
    )
    surplus = tuple(e.id for e in stored[len(wanted) :])
    added = tuple(wanted[len(stored) :])
    repair = plan.pair is not None and not booking.paired
    if not (row_changed or updates or surplus or added or repair):
        return None
    return Rederivation(booking, plan, row_changed, updates, surplus, added, repair)


def plan_sync(
    documents: Iterable[DocumentFacts],
    accounts: Sequence[ClearanceAccount],
    bookings: Mapping[BookingKey, StoredBooking],
    charges: Iterable[ChargeFacts] = (),
) -> Sync:
    """The writes that bring the bookings to what the sources call for."""
    index = provider_index(accounts)
    by_id = {a.id: a for a in accounts}
    create: list[tuple[int, BookingPlan]] = []
    rederive: list[Rederivation] = []
    remove: list[StoredBooking] = []
    seen: set[BookingKey] = set()
    for doc in documents:
        key = (DOCUMENT_SOURCE, doc.id)
        seen.add(key)
        booking = bookings.get(key)
        if booking is not None and doc.total != 0 and doc.currency == booking.currency:
            if (r := rederivation(booking, booking_plan(doc))) is not None:
                rederive.append(r)
            continue
        if booking is not None:  # its total is 0 or its currency is no longer its account's: the booking goes
            remove.append(booking)
        # what it calls for now, in the same settle (settling twice changes nothing): a document that lost its
        # booking to another currency is booked where that currency's account takes it
        if not_booked(doc, index) is None and (account := account_for(doc.provider, doc.currency, index)):
            create.append((account.id, booking_plan(doc)))
    for charge in charges:
        key = (TRANSFER_SOURCE, charge.entry_id)
        seen.add(key)
        booking = bookings.get(key)
        account = by_id.get(charge.counter_account_id)
        wanted = transfer_booking_plan(charge, None if account is None else account.currency)
        if (
            booking is not None
            and wanted is not None
            and account is not None
            and booking.account_id == account.id
        ):
            if (r := rederivation(booking, wanted)) is not None:
                rederive.append(r)
            continue
        if booking is not None:  # the charge points elsewhere, or its account no longer takes it
            remove.append(booking)
        if wanted is not None and account is not None:
            create.append((account.id, wanted))
    # a booking whose source is gone is called for by nothing
    remove.extend(b for key, b in bookings.items() if key not in seen)
    return Sync(tuple(create), tuple(rederive), tuple(sorted(remove, key=lambda b: b.id)))
