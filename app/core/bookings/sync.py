"""What the booking step does for documents: the difference between what documents call for and what is
booked (spec §5.8, features/documents.md §3-§4). Pure: facts in, a plan of writes out.

A document not yet booked is booked when `not_booked` says nothing against it. A booking follows its
document while the document's total is not 0 and its currency is the account's: its row and entries are
re-derived, the entries matched to the entry lines by position. Otherwise it is removed, and the document,
now not booked, is booked again in the same plan where it calls for it (another currency's account).
Where a booked document sits never changes with the providers or the start.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from app.core.bookings.documents import (
    BookingPlan,
    ClearanceAccount,
    DocumentFacts,
    EntryPlan,
    account_for,
    booking_plan,
    not_booked,
    provider_index,
)
from app.core.bookings.load import StoredBooking


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


def rederivation(booking: StoredBooking, doc: DocumentFacts) -> Rederivation | None:
    """What re-deriving `booking` from its document writes, None when it is as the document calls for."""
    plan = booking_plan(doc)
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
    if not (row_changed or updates or surplus or added):
        return None
    return Rederivation(booking, plan, row_changed, updates, surplus, added)


def plan_sync(
    documents: Iterable[DocumentFacts],
    accounts: Sequence[ClearanceAccount],
    bookings: Mapping[int, StoredBooking],
) -> Sync:
    """The writes that bring the document bookings to what the documents call for."""
    index = provider_index(accounts)
    create: list[tuple[int, BookingPlan]] = []
    rederive: list[Rederivation] = []
    remove: list[StoredBooking] = []
    seen: set[int] = set()
    for doc in documents:
        seen.add(doc.id)
        booking = bookings.get(doc.id)
        if booking is not None and doc.total != 0 and doc.currency == booking.currency:
            if (r := rederivation(booking, doc)) is not None:
                rederive.append(r)
            continue
        if booking is not None:  # its total is 0 or its currency is no longer its account's: the booking goes
            remove.append(booking)
        # what it calls for now, in the same settle (settling twice changes nothing): a document that lost its
        # booking to another currency is booked where that currency's account takes it
        if not_booked(doc, index) is None and (account := account_for(doc.provider, doc.currency, index)):
            create.append((account.id, booking_plan(doc)))
    # a booking whose document is gone is called for by nothing
    remove.extend(b for doc_id, b in bookings.items() if doc_id not in seen)
    return Sync(tuple(create), tuple(rederive), tuple(sorted(remove, key=lambda b: b.id)))
