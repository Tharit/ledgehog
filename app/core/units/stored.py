"""Loading what a plan needs from the database (reads only): the stored closure and the world around it."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from typing import Any, cast

from sqlalchemy import Connection, text

from app.core.ingest.identity import canonical_text
from app.core.matching import MAX_WINDOW, Leg, PoolEntry, Summary
from app.core.resolution.load import load_accounts, load_rules
from app.core.resolution.registry import classifiers_for
from app.core.resolution.snapshot import HistorySnapshot, load_votes
from app.core.settle.pairing import load_unpaired_legs
from app.core.settle.window import matching_window_days
from app.core.units.draft import UnitDraft
from app.core.units.lookup import unit_ids_of
from app.core.units.plan import Stored, StoredSource, StoredUnit, World

_ENTRIES = text(
    """
    SELECT e.id, e.version, e.source_transaction_id, e.account_id, e.currency, e.booked_on, e.value_on,
           e.amount, e.type, e.payee_id, e.category_id, e.counter_account_id, e.counterpart_entry_id,
           e.description, e.note, e.derivation, e.document_id,
           COALESCE((SELECT array_agg(t.tag_id ORDER BY t.tag_id)
                       FROM ledger_entry_tag AS t WHERE t.ledger_entry_id = e.id), '{}') AS tag_ids
      FROM ledger_entry AS e
     WHERE e.id = ANY(:ids)
     ORDER BY e.id
    """
)

_SOURCES = text(
    """
    SELECT s.id, s.amount, s.account_id, s.currency, s.booked_on, s.value_on,
           (s.importer IS NULL) AS authored,
           s.counterparty_ref, s.counterparty_name, s.purpose, s.booking_text, s.mandate_ref,
           s.instructed_currency, s.end_to_end_id, s.instructed_amount
      FROM source_transaction AS s
     WHERE s.id = ANY(:ids)
    """
)


def load_stored_unit(conn: Connection, anchor_entry_id: int) -> StoredUnit | None:
    """The closure of `anchor_entry_id` as stored; None when there is no such entry or it is derived."""
    ids = unit_ids_of(conn, anchor_entry_id)
    if ids is None:
        return None
    return load_stored_entries(conn, anchor_entry_id, ids.entry_ids)


def load_stored_entries(conn: Connection, anchor_entry_id: int, entry_ids: Iterable[int]) -> StoredUnit:
    rows = conn.execute(_ENTRIES, {"ids": sorted(set(entry_ids))}).all()
    entries = tuple(
        Stored(
            id=r.id,
            version=r.version,
            source_transaction_id=r.source_transaction_id,
            account_id=r.account_id,
            currency=r.currency,
            booked_on=r.booked_on,
            value_on=r.value_on,
            amount=r.amount,
            type=r.type,
            payee_id=r.payee_id,
            category_id=r.category_id,
            counter_account_id=r.counter_account_id,
            counterpart_entry_id=r.counterpart_entry_id,
            description=r.description,
            note=r.note,
            derivation=cast(dict[str, Any], r.derivation),
            tag_ids=tuple(int(t) for t in r.tag_ids),
            document_id=r.document_id,
        )
        for r in rows
    )
    sources = {
        int(r.id): StoredSource(
            id=r.id,
            amount=r.amount,
            account_id=r.account_id,
            currency=r.currency,
            booked_on=r.booked_on,
            value_on=r.value_on,
            user_authored=r.authored,
            counterparty_ref=r.counterparty_ref,
            counterparty_name=r.counterparty_name,
            purpose=r.purpose,
            booking_text=r.booking_text,
            mandate_ref=r.mandate_ref,
            instructed_currency=r.instructed_currency,
            end_to_end_id=r.end_to_end_id,
            instructed_amount=r.instructed_amount,
        )
        for r in conn.execute(_SOURCES, {"ids": sorted({e.source_transaction_id for e in entries})})
    }
    return StoredUnit(anchor_entry_id=anchor_entry_id, sources=sources, entries=entries)


def _named(draft: UnitDraft) -> tuple[list[int], list[int]]:
    categories: set[int] = set()
    payees: set[int] = set()
    for e in draft.entries:
        if e.category.mode == "fixed" and isinstance(e.category.value, int):
            categories.add(e.category.value)
        if e.payee.mode == "fixed" and isinstance(e.payee.value, int):
            payees.add(e.payee.value)
    return sorted(categories), sorted(payees)


def load_world(conn: Connection, stored: StoredUnit, draft: UnitDraft, *, ledger_wide: bool = False) -> World:
    """Accounts, the classifiers for the current rules, and the history of every vote but the closure's own
    (the unit's entries never vote about themselves; the overlay adds the plan's confirmed units back).

    `ledger_wide` (the preview) also loads every unpaired transfer leg of the ledger, so that the simulation
    of settling can pair the unit's legs with legs outside it. A commit leaves it off: settling follows."""
    closure = {e.id for e in stored.entries}
    history = HistorySnapshot(v for v in load_votes(conn) if v.entry_id not in closure)
    categories, payees = _named(draft)
    found_categories = (
        frozenset(
            int(i)
            for i in conn.execute(
                text("SELECT id FROM category WHERE id = ANY(:ids)"), {"ids": categories}
            ).scalars()
        )
        if categories
        else frozenset[int]()
    )
    found_payees = (
        frozenset(
            int(i)
            for i in conn.execute(
                text("SELECT id FROM payee WHERE id = ANY(:ids)"), {"ids": payees}
            ).scalars()
        )
        if payees
        else frozenset[int]()
    )
    sync = {
        int(r.account_id): (bool(r.synced), r.synced_through)
        for r in conn.execute(
            text(
                "SELECT s.account_id, s.synced, c.synced_through FROM v_account_synced AS s"
                " JOIN v_account_coverage AS c ON c.account_id = s.account_id"
            )
        )
    }
    return World(
        account_sync=sync,
        matching_window=matching_window_days(conn),
        accounts=load_accounts(conn),
        classifiers=classifiers_for(load_rules(conn)),
        history=history,
        categories=found_categories,
        payees=found_payees,
        ledger_legs=load_unpaired_legs(conn) if ledger_wide else (),
    )


def missing_tag(conn: Connection, draft: UnitDraft) -> tuple[int, int] | None:
    """The first `(index of the draft entry, tag id)` the draft adds that no longer exists, else None."""
    named = sorted({t for e in draft.entries for t in e.tags_add})
    if not named:
        return None
    found = {
        int(i)
        for i in conn.execute(text("SELECT id FROM tag WHERE id = ANY(:ids)"), {"ids": named}).scalars()
    }
    for i, e in enumerate(draft.entries):
        for t in sorted(e.tags_add):
            if t not in found:
                return i, t
    return None


# The movements offers are made of: for each leg (date, sign, account, counter-account or none) the entries of
# the OPPOSITE sign within `cap` days, on the counter-account where there is one, else on any other account;
# unpaired or paired transfer legs and untyped entries. One statement for all the legs, served by
# `ix_le_account_date` (a known counter-account) or `ix_le_date`; a duplicate has no entries (I3).
_POOL = text(
    """
    WITH legs AS (
        SELECT * FROM unnest(CAST(:dates AS date[]), CAST(:signs AS int[]), CAST(:accounts AS bigint[]),
                             CAST(:counters AS bigint[])) AS v(d, s, acc, counter)
    ), hit AS (
        SELECT DISTINCT e.id
          FROM legs AS v
          JOIN ledger_entry AS e
            ON e.booked_on BETWEEN v.d - CAST(:cap AS int) AND v.d + CAST(:cap AS int)
           AND (v.counter IS NULL OR e.account_id = v.counter)
           AND e.account_id <> v.acc
           AND ((v.s > 0 AND e.amount < 0) OR (v.s < 0 AND e.amount > 0))
           AND (e.type = 'transfer' OR e.type IS NULL)
           AND e.source_transaction_id IS NOT NULL
         WHERE e.id <> ALL(CAST(:skip AS bigint[]))
    )
    SELECT e.id, e.account_id, e.currency, e.amount, e.booked_on, e.type, e.counter_account_id,
           e.description, e.counterpart_entry_id,
           s.end_to_end_id, s.instructed_amount, s.instructed_currency, s.purpose,
           NOT EXISTS (SELECT 1 FROM ledger_entry AS o
                        WHERE o.source_transaction_id = e.source_transaction_id AND o.id < e.id) AS original,
           p.account_id AS p_account, p.booked_on AS p_booked_on, p.amount AS p_amount,
           p.currency AS p_currency, p.description AS p_description
      FROM hit
      JOIN ledger_entry AS e ON e.id = hit.id
      JOIN source_transaction AS s ON s.id = e.source_transaction_id
      LEFT JOIN ledger_entry AS p ON p.id = e.counterpart_entry_id
     ORDER BY e.booked_on, e.id
    """
)


def load_pool(conn: Connection, legs: Sequence[Leg], skip: Collection[int]) -> list[PoolEntry]:
    """The pool offers are made of, around `legs` and up to the widest window a pick may ask for.

    `skip` holds the entries of the plan (their planned state is what counts, not the stored one).
    """
    if not legs:
        return []
    rows = conn.execute(
        _POOL,
        {
            "dates": [leg.booked_on for leg in legs],
            "signs": [(leg.amount > 0) - (leg.amount < 0) for leg in legs],
            "accounts": [leg.account_id for leg in legs],
            "counters": [leg.counter_account_id for leg in legs],
            "cap": MAX_WINDOW,
            "skip": sorted(skip),
        },
    ).all()
    return [
        PoolEntry(
            leg=Leg(
                entry_id=r.id,
                account_id=r.account_id,
                currency=r.currency,
                amount=r.amount,
                booked_on=r.booked_on,
                type=r.type,
                counter_account_id=r.counter_account_id,
                end_to_end_id=r.end_to_end_id,
                instructed_amount=r.instructed_amount,
                instructed_currency=r.instructed_currency,
                purpose=canonical_text(r.purpose),
            ),
            original=bool(r.original),
            description=r.description,
            partner=None
            if r.counterpart_entry_id is None
            else Summary(
                entry_id=r.counterpart_entry_id,
                account_id=r.p_account,
                booked_on=r.p_booked_on,
                amount=r.p_amount,
                currency=r.p_currency,
                description=r.p_description,
            ),
        )
        for r in rows
    ]


def load_closure_of(conn: Connection, entry_ids: Iterable[int]) -> set[int]:
    """The ids of the units of `entry_ids` (each unit's entries, as `lookup.unit_ids_of`)."""
    out: set[int] = set()
    for entry_id in entry_ids:
        ids = unit_ids_of(conn, entry_id)
        if ids is not None:
            out.update(ids.entry_ids)
    return out


def pick_partner_ids(draft: UnitDraft) -> list[int]:
    """The partners the draft picks, ascending: each brings its own closure into the unit being drafted."""
    return sorted(
        {
            e.pairing.partner_entry_id
            for e in draft.entries
            if e.pairing.mode == "pick" and e.pairing.partner_entry_id is not None
        }
    )


def load_drafted_unit(conn: Connection, draft: UnitDraft) -> tuple[StoredUnit, frozenset[int]] | None:
    """The closure of the anchor extended by the closure of every partner the draft picks (the unit as
    drafted), and the ids of the anchor's own closure. None when the anchor is in no unit. A partner that
    is in no unit is left out: the plan refuses the pick."""
    ids = unit_ids_of(conn, draft.anchor_entry_id)
    if ids is None:
        return None
    all_ids = set(ids.entry_ids) | load_closure_of(conn, pick_partner_ids(draft))
    return load_stored_entries(conn, draft.anchor_entry_id, all_ids), frozenset(ids.entry_ids)
