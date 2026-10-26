"""Settle steps 2 and 3: the bookings on clearance accounts and the resolution of their entries.

Step 2 (architecture §5.2, spec §5.8) books what a source calls for and is not yet booked, re-derives what
changed and removes what is no longer called for. Its sources are the documents a clearance account takes
and the charges decided, under standing keys, as transfers to a clearance account, whose counter-leg it
books paired with them (`core/bookings`). It reads only its sources, the provider lists and the accounts'
starts, none of which a round changes (a charge's decision is what step 1 and the writes leave), so after
the first round it writes nothing. It keeps the document entries it created or whose source text changed in
the settle's scratch (`SettleRun.afresh`), which step 3 resolves afresh; a transfer booking's entry is
written whole, its type, counter-account and pair carrying the key `booking`.
"""

from __future__ import annotations

from sqlalchemy import Connection

from app.core.bookings.load import load_bookings, load_charges, load_clearance_accounts, load_documents
from app.core.bookings.sync import plan_sync
from app.core.bookings.write import apply_sync
from app.core.settle.resolution import resolve_afresh_step
from app.core.settle.run import StepOutcome, current_run


def book_clearance_step(conn: Connection) -> StepOutcome:
    """Step 2: bookings on clearance accounts (spec §5.8), from documents and from charges."""
    accounts = load_clearance_accounts(conn)
    if not accounts:
        return StepOutcome()  # no clearance account, nothing is booked
    bookings = load_bookings(conn)
    documents = (
        load_documents(conn)
        if any(a.providers for a in accounts) or any(kind == "document" for kind, _ in bookings)
        else []
    )
    sync = plan_sync(documents, accounts, bookings, load_charges(conn))
    written = apply_sync(conn, sync)
    current_run().afresh.update(written.afresh)
    return StepOutcome(touched=written.touched)


def resolve_bookings_step(conn: Connection) -> StepOutcome:
    """Step 3: resolve afresh the booking entries step 2 created or whose source text it changed."""
    run = current_run()
    entry_ids = sorted(run.afresh)
    run.afresh.clear()
    return resolve_afresh_step(conn, entry_ids)
