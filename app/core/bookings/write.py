"""The writes of the booking step (architecture §5.2 step 2): apply a `Sync` in the caller's transaction.

The caller holds the settle lock exclusively; this takes the locks of the clearance accounts it writes on,
in ascending id order, and recomputes their derived entries before it returns. Source rows and entries are
written set-based. A booking is created split, one entry per line (the I7 exception); its entries' type is
`flow` under the standing key `booking` (spec §5.9). Removed entries go through the removal routine, which
takes their tags with them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import Connection, text

from app.core.balance.derived import recompute_derived
from app.core.bookings.documents import EntryPlan
from app.core.bookings.sync import Sync
from app.core.ingest.removal import remove_entries
from app.utils.db.changes import DOCUMENTS, note_change
from app.utils.db.locks import lock_accounts

_BOOKING_KEY = json.dumps({"type": {"pass": "booking", "basis": {}}})


@dataclass(frozen=True, slots=True)
class Written:
    """What the writes touched: entries created or updated, those that resolve afresh (new, or their source
    text changed), and the accounts written on."""

    touched: tuple[int, ...] = ()
    afresh: tuple[int, ...] = ()
    accounts: tuple[int, ...] = ()


def apply_sync(conn: Connection, sync: Sync) -> Written:
    if sync.empty:
        return Written()
    accounts = lock_accounts(conn, sync.account_ids())
    note_change(conn, DOCUMENTS)  # the documents' bookings changed what a document shows
    touched: list[int] = []
    afresh: list[int] = []

    created = _create(conn, sync)
    touched.extend(created)
    afresh.extend(created)

    _update_rows(conn, sync)
    updated = [u for r in sync.rederive for u in r.updates]
    if updated:
        conn.execute(
            text(
                "UPDATE ledger_entry AS e SET amount = v.amount, booked_on = v.booked_on,"
                " source_text = v.source_text"
                " FROM unnest(CAST(:ids AS bigint[]), CAST(:amounts AS bigint[]), CAST(:days AS date[]),"
                "             CAST(:texts AS text[])) AS v(id, amount, booked_on, source_text)"
                " WHERE e.id = v.id"
            ),
            {
                "ids": [u.entry_id for u in updated],
                "amounts": [u.amount for u in updated],
                "days": [u.booked_on for u in updated],
                "texts": [u.source_text for u in updated],
            },
        )
        touched.extend(u.entry_id for u in updated)
        afresh.extend(u.entry_id for u in updated if u.text_changed)
    added = _add_entries(conn, sync)
    touched.extend(added)
    afresh.extend(added)

    gone = sorted(
        [i for r in sync.rederive for i in r.surplus] + [e.id for b in sync.remove for e in b.entries]
    )
    if gone:
        remove_entries(conn, gone)
    if sync.remove:
        conn.execute(
            text("DELETE FROM source_transaction WHERE id = ANY(:ids)"), {"ids": [b.id for b in sync.remove]}
        )
    for account_id in accounts:
        recompute_derived(conn, account_id)
    return Written(tuple(sorted(set(touched))), tuple(sorted(set(afresh))), tuple(accounts))


def _create(conn: Connection, sync: Sync) -> list[int]:
    """New bookings, each with one entry per entry line; the new entries' ids."""
    if not sync.create:
        return []
    created = {
        r.source_id: int(r.id)
        for r in conn.execute(
            text(
                "INSERT INTO source_transaction (origin, account_id, source_id, amount, currency, booked_on,"
                " counterparty_name, purpose, raw)"
                " SELECT 'booking', v.account_id, v.source_id, v.amount, a.currency, v.booked_on,"
                "        v.counterparty_name, v.purpose, jsonb_build_object('booking', v.source_id)"
                " FROM unnest(CAST(:accounts AS bigint[]), CAST(:source_ids AS text[]),"
                "             CAST(:amounts AS bigint[]), CAST(:days AS date[]), CAST(:names AS text[]),"
                "             CAST(:purposes AS text[]))"
                "      AS v(account_id, source_id, amount, booked_on, counterparty_name, purpose)"
                " JOIN account a ON a.id = v.account_id"
                " RETURNING id, source_id"
            ),
            {
                "accounts": [a for a, _ in sync.create],
                "source_ids": [p.source_id for _, p in sync.create],
                "amounts": [p.amount for _, p in sync.create],
                "days": [p.booked_on for _, p in sync.create],
                "names": [p.counterparty_name for _, p in sync.create],
                "purposes": [p.purpose for _, p in sync.create],
            },
        )
    }
    return _insert_entries(conn, [(created[p.source_id], e) for _, p in sync.create for e in p.entries])


def _add_entries(conn: Connection, sync: Sync) -> list[int]:
    return _insert_entries(
        conn,
        [(r.booking.id, e) for r in sync.rederive for e in r.added],
    )


def _insert_entries(conn: Connection, items: list[tuple[int, EntryPlan]]) -> list[int]:
    """The entries of bookings, in the order given (their id order is their position)."""
    if not items:
        return []
    return [
        int(i)
        for i in conn.execute(
            text(
                "INSERT INTO ledger_entry (source_transaction_id, account_id, amount, currency, booked_on,"
                " source_text, type, derivation)"
                " SELECT v.source_id, s.account_id, v.amount, s.currency, s.booked_on, v.source_text, 'flow',"
                "        CAST(:key AS jsonb)"
                " FROM unnest(CAST(:sources AS bigint[]), CAST(:amounts AS bigint[]), CAST(:texts AS text[]))"
                "      WITH ORDINALITY AS v(source_id, amount, source_text, ord)"
                " JOIN source_transaction s ON s.id = v.source_id"
                " ORDER BY v.ord RETURNING id"
            ),
            {
                "sources": [s for s, _ in items],
                "amounts": [e.amount for _, e in items],
                "texts": [e.source_text for _, e in items],
                "key": _BOOKING_KEY,
            },
        ).scalars()
    ]


def _update_rows(conn: Connection, sync: Sync) -> None:
    rows = [r for r in sync.rederive if r.row_changed]
    if not rows:
        return
    conn.execute(
        text(
            "UPDATE source_transaction AS s SET amount = v.amount, booked_on = v.booked_on,"
            " purpose = v.purpose, counterparty_name = v.counterparty_name"
            " FROM unnest(CAST(:ids AS bigint[]), CAST(:amounts AS bigint[]), CAST(:days AS date[]),"
            "             CAST(:purposes AS text[]), CAST(:names AS text[]))"
            "      AS v(id, amount, booked_on, purpose, counterparty_name)"
            " WHERE s.id = v.id"
        ),
        {
            "ids": [r.booking.id for r in rows],
            "amounts": [r.plan.amount for r in rows],
            "days": [r.plan.booked_on for r in rows],
            "purposes": [r.plan.purpose for r in rows],
            "names": [r.plan.counterparty_name for r in rows],
        },
    )
