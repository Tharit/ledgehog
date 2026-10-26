"""The removal routine (spec §5.6 'Removing an entry and its consequences').

Applied by marking a duplicate, reverting a run, breaking a pair and deleting a
user-authored transaction, always inside the caller's transaction (the caller holds the
settle lock shared and the accounts' locks). What it does for the entries removed:

* a partner loses its counterpart and the counter-account its pair set (key basis
  ``{"from": "counterpart"}``) and the pair's own key, and keeps every other value; a
  counter-leg the system created stays (`unpair` is that half of the routine on its own);
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
from datetime import date

from sqlalchemy import Connection, text

from app.core.balance.derived import recompute_derived
from app.core.domain.errors import IngestError
from app.utils.db.locks import lock_rows

_PAIR_BASIS = '{"from": "counterpart"}'


@dataclass(frozen=True)
class Affected:
    """What a removal touched; ids ascending."""

    removed_entry_ids: tuple[int, ...] = ()
    partner_entry_ids: tuple[int, ...] = ()
    account_ids: tuple[int, ...] = ()
    # `unpair` only: every entry that lost its link, the ones asked for and their partners
    unpaired_entry_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class DerivedEntry:
    type: str
    booked_on: date
    amount: int


@dataclass(frozen=True)
class DerivedChange:
    """An account whose derived entries (opening, reconciliations, valuations) differ after a write."""

    account_id: int
    before: tuple[DerivedEntry, ...]
    after: tuple[DerivedEntry, ...]


def entry_versions(conn: Connection, entry_ids: Sequence[int]) -> dict[int, int]:
    """entry id -> version, for the entries that exist (what a confirming request must carry)."""
    return {
        int(r.id): int(r.version)
        for r in conn.execute(
            text("SELECT id, version FROM ledger_entry WHERE id = ANY(:ids) ORDER BY id"),
            {"ids": list(entry_ids)},
        )
    }


def derived_snapshot(conn: Connection, accounts: Sequence[int]) -> dict[int, tuple[DerivedEntry, ...]]:
    """The derived entries of each account, by date then id: take it before and after a write."""
    out: dict[int, tuple[DerivedEntry, ...]] = {a: () for a in accounts}
    for r in conn.execute(
        text(
            "SELECT account_id, type, booked_on, amount FROM ledger_entry WHERE account_id = ANY(:a)"
            " AND balance_record_id IS NOT NULL ORDER BY account_id, booked_on, id"
        ),
        {"a": list(accounts)},
    ):
        out[r.account_id] = (*out[r.account_id], DerivedEntry(r.type, r.booked_on, r.amount))
    return out


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


def _release(conn: Connection, ids: Sequence[int]) -> list[int]:
    """Undo the pair of each of `ids`: no counterpart, no counter-account the pair set, no pair key.

    A counter-account the entry had before it was paired (a key that is not `{"from": "counterpart"}`)
    stays, with every other value. Returns the accounts of the entries written, in no order.
    """
    if not ids:
        return []
    rows = conn.execute(
        text(
            "UPDATE ledger_entry SET counterpart_entry_id = NULL,"
            " counter_account_id = CASE WHEN derivation #> '{counter_account,basis}' @> CAST(:basis AS jsonb)"
            "                           THEN NULL ELSE counter_account_id END,"
            " derivation = CASE WHEN derivation #> '{counter_account,basis}' @> CAST(:basis AS jsonb)"
            "                   THEN derivation - 'counter_account' - 'counterpart'"
            "                   ELSE derivation - 'counterpart' END"
            " WHERE id = ANY(:ids) RETURNING account_id"
        ),
        {"ids": list(ids), "basis": _PAIR_BASIS},
    ).all()
    return [int(r.account_id) for r in rows]


def unpair(conn: Connection, entry_ids: Sequence[int]) -> Affected:
    """The unpair half of the removal routine, deleting nothing (spec §5.6, §5.9 'Breaking a pair').

    Every paired entry of `entry_ids` and its partner lose their counterpart link, the counter-account
    the pair set and the pair's key (`_release`), and keep every other value; an entry of `entry_ids` that
    is not paired is left as it is. Both legs return to review through settling: an unpaired transfer
    cannot be confirmed (§6), and a unit that was one is now two. Entries of `entry_ids` take whatever
    state the caller writes next; the partners outside `entry_ids` are the ones left behind.

    Preconditions as for `remove_entries`: the settle lock shared and the accounts' locks are held;
    the ledger_entry rows are locked ascending by the caller, or here. Raises `IngestError` for an
    unknown id. Versions bump (`counterpart_entry_id` is structural), the unit is recomputed by settling.
    """
    asked, partners = entry_scope(conn, entry_ids)
    lock_rows(conn, "ledger_entry", [*asked, *partners])
    if not asked:
        return Affected()
    present = {
        int(i)
        for i in conn.execute(
            text("SELECT id FROM ledger_entry WHERE id = ANY(:ids)"), {"ids": asked}
        ).scalars()
    }
    if missing := sorted(set(asked) - present):
        raise IngestError(f"no such entries: {missing}")
    # only entries that point somewhere or are pointed at are written: an unpaired leg is left alone
    linked = conn.execute(
        text(
            "SELECT e.id FROM ledger_entry e WHERE e.id = ANY(:ids)"
            " AND (e.counterpart_entry_id IS NOT NULL"
            "      OR EXISTS (SELECT 1 FROM ledger_entry q WHERE q.counterpart_entry_id = e.id))"
            " ORDER BY e.id"
        ),
        {"ids": sorted({*asked, *partners})},
    ).scalars()
    unlinked = [int(i) for i in linked]
    # both sides in one statement: the pair trigger is deferred, the unique index only sees NULLs
    accounts = _release(conn, unlinked)
    return Affected(
        partner_entry_ids=tuple(partners),
        account_ids=tuple(sorted(set(accounts))),
        unpaired_entry_ids=tuple(unlinked),
    )


def remove_entries(
    conn: Connection, entry_ids: Sequence[int], *, scope: tuple[list[int], list[int]] | None = None
) -> Affected:
    """Apply the removal routine to `entry_ids` and delete them, in the caller's transaction.

    `scope` is an `entry_scope` result the caller already computed for these ids; passing it
    means the caller has also locked those ledger_entry rows (ascending), so neither is repeated.

    Preconditions: settle lock shared and the affected accounts' locks are held. The caller
    must also leave every source row it emptied a duplicate or deleted before it commits (see
    the module docstring). Raises `IngestError` for unknown or derived entry ids.
    """
    if scope is None:
        removed, partners = entry_scope(conn, entry_ids)
        # Row locks in ascending id order, removed and partners together.
        lock_rows(conn, "ledger_entry", [*removed, *partners])
    else:
        removed, partners = scope
    if not removed:
        return Affected()
    rows = conn.execute(
        text(
            "SELECT id, account_id, source_transaction_id FROM ledger_entry WHERE id = ANY(:ids) ORDER BY id"
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
    partner_accounts = _release(conn, partners)
    # One statement; the rows are locked in ascending id order already.
    conn.execute(text("DELETE FROM ledger_entry WHERE id = ANY(:ids)"), {"ids": removed})

    accounts = sorted({r.account_id for r in rows} | set(partner_accounts))
    for account_id in accounts:
        recompute_derived(conn, account_id)
    return Affected(
        removed_entry_ids=tuple(removed),
        partner_entry_ids=tuple(partners),
        account_ids=tuple(accounts),
    )
