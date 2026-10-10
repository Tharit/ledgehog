"""The removal routine (spec §5.6 'Removing an entry and its consequences').

Applied by marking a duplicate, reverting a run, breaking a pair and deleting a
user-authored transaction, always inside the caller's transaction (the caller holds the
settle lock shared and the accounts' locks). What it does for the entries removed:

* a partner loses its counterpart and the counter-account its pair set (key basis
  ``{"from": "counterpart"}``), and keeps every other value; a counter-leg the system
  created stays;
* a document an entry carried is free again (the link is the entry's column, so it goes
  with the row; the ids are reported);
* the derived entries of every affected account are recomputed.

Contract: the routine deletes entries and nothing else of their source rows. Deleting the
last entry of a source row that is neither a duplicate nor gone breaks I3, and the deferred
triggers (``trg_split_sum``, ``trg_duplicate_state``) fail the caller's commit. So the caller,
in the SAME transaction, either sets ``duplicate_of`` on the row (mark a duplicate) or deletes
the row (revert, deleting a user-authored transaction). Setting ``duplicate_of`` and removing
the entries are one commit either way; the order within it does not matter.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Connection, text

from app.core.ingest.run import IngestError, recompute_derived
from app.utils.db.locks import lock_rows

_PAIR_BASIS = '{"from": "counterpart"}'


@dataclass(frozen=True)
class Affected:
    """What a removal touched; ids ascending."""

    removed_entry_ids: tuple[int, ...] = ()
    partner_entry_ids: tuple[int, ...] = ()
    account_ids: tuple[int, ...] = ()
    freed_document_ids: tuple[int, ...] = ()


def entry_scope(conn: Connection, entry_ids: Sequence[int]) -> tuple[list[int], list[int]]:
    """(entries to remove, ascending; their partners that stay, ascending). Reads only."""
    removed = sorted(set(entry_ids))
    if not removed:
        return [], []
    partners = conn.execute(
        text(
            "SELECT DISTINCT p.id FROM ledger_entry r JOIN ledger_entry p"
            " ON p.id = r.counterpart_entry_id OR p.counterpart_entry_id = r.id"
            " WHERE r.id = ANY(:ids) AND NOT p.id = ANY(:ids) ORDER BY p.id"
        ),
        {"ids": removed},
    ).scalars()
    return removed, [int(p) for p in partners]


def remove_entries(conn: Connection, entry_ids: Sequence[int]) -> Affected:
    """Apply the removal routine to `entry_ids` and delete them, in the caller's transaction.

    Preconditions: settle lock shared and the affected accounts' locks are held. The caller
    must also leave every source row it emptied a duplicate or deleted before it commits (see
    the module docstring). Raises `IngestError` for unknown or derived entry ids.
    """
    removed, partners = entry_scope(conn, entry_ids)
    if not removed:
        return Affected()
    # Row locks in ascending id order, removed and partners together.
    lock_rows(conn, "ledger_entry", [*removed, *partners])
    rows = conn.execute(
        text(
            "SELECT id, account_id, document_id, source_transaction_id FROM ledger_entry"
            " WHERE id = ANY(:ids) ORDER BY id"
        ),
        {"ids": removed},
    ).all()
    if len(rows) != len(removed):
        missing = sorted(set(removed) - {r.id for r in rows})
        raise IngestError(f"no such entries: {missing}")
    derived = [r.id for r in rows if r.source_transaction_id is None]
    if derived:
        raise IngestError(f"derived entries are recomputed, never removed: {derived}")

    # Partners first: a unique index (ux_le_counterpart) and the pair trigger must see a
    # pair undone from the surviving side. Only a counter-account the pair itself set goes.
    partner_rows = conn.execute(
        text(
            "UPDATE ledger_entry SET counterpart_entry_id = NULL,"
            " counter_account_id = CASE WHEN derivation #> '{counter_account,basis}' @> CAST(:basis AS jsonb)"
            "                           THEN NULL ELSE counter_account_id END,"
            " derivation = CASE WHEN derivation #> '{counter_account,basis}' @> CAST(:basis AS jsonb)"
            "                   THEN derivation - 'counter_account' ELSE derivation END"
            " WHERE id = ANY(:ids) RETURNING account_id"
        ),
        {"ids": partners, "basis": _PAIR_BASIS},
    ).all()
    # Delete in ascending id order (the rows are locked in that order already).
    for entry_id in removed:
        conn.execute(text("DELETE FROM ledger_entry WHERE id = :i"), {"i": entry_id})

    accounts = sorted({r.account_id for r in rows} | {r.account_id for r in partner_rows})
    for account_id in accounts:
        recompute_derived(conn, account_id)
    return Affected(
        removed_entry_ids=tuple(removed),
        partner_entry_ids=tuple(partners),
        account_ids=tuple(accounts),
        freed_document_ids=tuple(sorted(r.document_id for r in rows if r.document_id is not None)),
    )
