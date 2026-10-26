"""The writes of the booking step (architecture §5.2 step 2): apply a `Sync` in the caller's transaction.

The caller holds the settle lock exclusively; this takes the locks of the clearance accounts it writes on,
in ascending id order, and recomputes their derived entries before it returns. Source rows and entries are
written set-based. A document's booking is created split, one entry per line (the I7 exception); its
entries' type is `flow` under the standing key `booking` (spec §5.9). A transfer booking has the one entry,
typed `transfer`, its counter-account the charge's account, paired with the charge: type, counter-account and
pair carry the key `booking` on it, the pair on the charge too (spec §5.7). Removed entries go through the
removal routine, which takes their tags with them and releases the charge a booking was paired with.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import Connection, text

from app.core.balance.derived import recompute_derived
from app.core.bookings.documents import DOCUMENT_SOURCE, EntryPlan, PairPlan
from app.core.bookings.sync import Sync
from app.core.ingest.removal import remove_entries
from app.utils.db.changes import DOCUMENTS, note_change
from app.utils.db.locks import lock_accounts

_KEY: dict[str, object] = {"pass": "booking", "basis": {}}
_BOOKING_KEY = json.dumps({"type": _KEY})
_TRANSFER_KEYS = json.dumps({"type": _KEY, "counter_account": _KEY})
_PAIR_KEY = json.dumps(_KEY)


@dataclass(frozen=True, slots=True)
class Written:
    """What the writes touched: entries created or updated, those that resolve afresh (new, or their source
    text changed), and the accounts written on."""

    touched: tuple[int, ...] = ()
    afresh: tuple[int, ...] = ()
    accounts: tuple[int, ...] = ()


def _is_document(source_id: str) -> bool:
    return source_id.startswith(f"{DOCUMENT_SOURCE}:")


def apply_sync(conn: Connection, sync: Sync) -> Written:
    if sync.empty:
        return Written()
    accounts = lock_accounts(conn, sync.account_ids())
    if (
        any(_is_document(p.source_id) for _, p in sync.create)
        or any(_is_document(r.plan.source_id) for r in sync.rederive)
        or any(b.kind == DOCUMENT_SOURCE for b in sync.remove)
    ):
        note_change(conn, DOCUMENTS)  # the documents' bookings changed what a document shows
    touched: list[int] = []
    afresh: list[int] = []

    # removals first: a charge released from a booking that goes is paired again with the booking it now has
    gone = sorted(
        [i for r in sync.rederive for i in r.surplus] + [e.id for b in sync.remove for e in b.entries]
    )
    if gone:
        remove_entries(conn, gone)
    if sync.remove:
        conn.execute(
            text("DELETE FROM source_transaction WHERE id = ANY(:ids)"), {"ids": [b.id for b in sync.remove]}
        )
    # the charges the removed bookings were paired with: their pair is released
    touched.extend(int(b.key) for b in sync.remove if b.kind != DOCUMENT_SOURCE)

    created, created_pairs = _create(conn, sync)
    touched.extend(created)
    afresh.extend(i for i in created if i not in {b for b, _c, _a in created_pairs})

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

    repairs = [
        (r.booking.entries[0].id, r.plan.pair.entry_id, r.plan.pair.account_id)
        for r in sync.rederive
        if r.repair_pair and r.plan.pair is not None and r.booking.entries
    ]
    _pair(conn, [*created_pairs, *repairs])
    for booking_entry, charge, _account in repairs:
        touched.extend((booking_entry, charge))
    touched.extend(charge for _b, charge, _a in created_pairs)
    for account_id in accounts:
        recompute_derived(conn, account_id)
    return Written(tuple(sorted(set(touched))), tuple(sorted(set(afresh))), tuple(accounts))


def _pair(conn: Connection, pairs: list[tuple[int, int, int]]) -> None:
    """Pair each booking entry with its charge, `(booking entry, charge entry, charge account)`: both legs'
    counterpart and the pair's key `booking`, the booking entry's type and counter-account set. Both legs are
    cleared first (the unique index and the deferred pair trigger only see the end)."""
    if not pairs:
        return
    conn.execute(
        text("UPDATE ledger_entry SET counterpart_entry_id = NULL WHERE id = ANY(:ids)"),
        {"ids": sorted({i for b, c, _ in pairs for i in (b, c)})},
    )
    conn.execute(
        text(
            "UPDATE ledger_entry AS e SET counterpart_entry_id = v.partner,"
            " type = COALESCE(v.typed, e.type),"
            " counter_account_id = COALESCE(v.counter, e.counter_account_id),"
            " derivation = e.derivation || CASE WHEN v.typed IS NULL THEN '{}'::jsonb"
            "                                   ELSE CAST(:keys AS jsonb) END"
            "                           || jsonb_build_object('counterpart', CAST(:pair_key AS jsonb))"
            " FROM unnest(CAST(:ids AS bigint[]), CAST(:partners AS bigint[]), CAST(:typed AS text[]),"
            "             CAST(:counters AS bigint[])) AS v(id, partner, typed, counter)"
            " WHERE e.id = v.id"
        ),
        {
            "ids": [b for b, _c, _a in pairs] + [c for _b, c, _a in pairs],
            "partners": [c for _b, c, _a in pairs] + [b for b, _c, _a in pairs],
            "typed": ["transfer"] * len(pairs) + [None] * len(pairs),
            "counters": [a for _b, _c, a in pairs] + [None] * len(pairs),
            "keys": _TRANSFER_KEYS,
            "pair_key": _PAIR_KEY,
        },
    )


def _create(conn: Connection, sync: Sync) -> tuple[list[int], list[tuple[int, int, int]]]:
    """New bookings, each with one entry per entry line; the new entries' ids, and the pairs still to make
    `(booking entry, charge entry, charge account)`."""
    if not sync.create:
        return [], []
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
    items = [(created[p.source_id], e, p.pair) for _, p in sync.create for e in p.entries]
    ids = _insert_entries(conn, items)
    pairs = [
        (entry_id, pair.entry_id, pair.account_id)
        for entry_id, (_s, _e, pair) in zip(ids, items, strict=True)
        if pair is not None
    ]
    return ids, pairs


def _add_entries(conn: Connection, sync: Sync) -> list[int]:
    return _insert_entries(
        conn,
        [(r.booking.id, e, None) for r in sync.rederive for e in r.added],
    )


def _insert_entries(conn: Connection, items: list[tuple[int, EntryPlan, PairPlan | None]]) -> list[int]:
    """The entries of bookings, in the order given (their id order is their position). A transfer booking's
    is typed `transfer` with the charge's account as counter-account, not yet paired (`_pair`)."""
    if not items:
        return []
    return [
        int(i)
        for i in conn.execute(
            text(
                "INSERT INTO ledger_entry (source_transaction_id, account_id, amount, currency, booked_on,"
                " source_text, type, counter_account_id, derivation)"
                " SELECT v.source_id, s.account_id, v.amount, s.currency, s.booked_on, v.source_text, v.type,"
                "        v.counter, CAST(v.key AS jsonb)"
                " FROM unnest(CAST(:sources AS bigint[]), CAST(:amounts AS bigint[]), CAST(:texts AS text[]),"
                "             CAST(:types AS text[]), CAST(:counters AS bigint[]), CAST(:keys AS text[]))"
                "      WITH ORDINALITY AS v(source_id, amount, source_text, type, counter, key, ord)"
                " JOIN source_transaction s ON s.id = v.source_id"
                " ORDER BY v.ord RETURNING id"
            ),
            {
                "sources": [s for s, _, _ in items],
                "amounts": [e.amount for _, e, _ in items],
                "texts": [e.source_text for _, e, _ in items],
                "types": ["flow" if p is None else "transfer" for _, _, p in items],
                "counters": [None if p is None else p.account_id for _, _, p in items],
                "keys": [_BOOKING_KEY if p is None else _TRANSFER_KEYS for _, _, p in items],
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
