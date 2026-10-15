"""Loading what a plan needs from the database (reads only): the stored closure and the world around it."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

from sqlalchemy import Connection, text

from app.core.resolution.load import load_accounts, load_rules
from app.core.resolution.registry import classifiers_for
from app.core.resolution.snapshot import HistorySnapshot, load_votes
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
           s.instructed_currency
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


def load_world(conn: Connection, stored: StoredUnit, draft: UnitDraft) -> World:
    """Accounts, the classifiers for the current rules, and the history of every vote but the closure's own
    (the unit's entries never vote about themselves; the overlay adds the plan's confirmed units back)."""
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
    return World(
        accounts=load_accounts(conn),
        classifiers=classifiers_for(load_rules(conn)),
        history=history,
        categories=found_categories,
        payees=found_payees,
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
