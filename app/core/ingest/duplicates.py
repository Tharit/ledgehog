"""Marking and clearing duplicates by hand (spec §5.6, architecture §5.2).

Each operation is ONE transaction: settle lock shared, then the account's lock, then row
locks in ascending id; it commits, and only then settles (settling takes the settle lock
exclusively in its own transaction, so it can never run inside this one). A settling
failure is reported on the result, never raised into the committed write.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Connection, Engine, text

from app.core.domain.errors import (
    AlreadyDuplicate,
    DuplicateChain,
    DuplicateCrossAccount,
    DuplicateOfSelf,
    DuplicateRowMissing,
    NotADuplicate,
    UserAuthoredRow,
    VersionConflict,
)
from app.core.ingest.entries import insert_entry
from app.core.ingest.removal import Affected, entry_scope, remove_entries
from app.core.ingest.run import recompute_derived
from app.core.settle.settle import SettleResult, settle
from app.utils.db.locks import lock_accounts, lock_rows, lock_settle_shared, retry_on_deadlock


@dataclass(frozen=True)
class OpResult:
    """Response of a duplicate operation: what settling touched, what the removal affected."""

    settle: SettleResult
    affected: Affected = field(default_factory=Affected)
    created_entry_id: int | None = None  # clear: the entry the row got


def mark_duplicate(
    engine: Engine,
    row_id: int,
    of_row_id: int,
    *,
    expected_versions: Mapping[int, int] | None = None,
) -> OpResult:
    """Mark imported row `row_id` as a duplicate of `of_row_id` (same account, not a duplicate).

    `expected_versions` maps entry id -> the version the caller saw. `None` means "no check".
    A map, even an empty one, must cover EVERY entry the operation writes: the marked row's
    entries and the transfer partners the removal unpairs (architecture §4.1). If a covered
    entry has moved (or is gone), or an entry the operation would write has no version in the
    map (the caller's view was incomplete), `VersionConflict` names them all and nothing is
    written. The marked row's entries are removed through `remove_entries` in the same
    transaction that sets `duplicate_of`, and rows that pointed at it are repointed to `of_row_id`.
    """
    if row_id == of_row_id:
        raise DuplicateOfSelf(row_id)
    affected = retry_on_deadlock(lambda: _mark(engine, row_id, of_row_id, expected_versions))
    return OpResult(settle=_settle(engine), affected=affected)


def clear_duplicate(engine: Engine, row_id: int) -> OpResult:
    """'Not a duplicate': clear `duplicate_of` and give the row its one entry, as ingest would."""
    entry_id = retry_on_deadlock(lambda: _clear(engine, row_id))
    return OpResult(settle=_settle(engine), created_entry_id=entry_id)


def _settle(engine: Engine) -> SettleResult:
    try:
        return settle(engine)
    except Exception as exc:  # the write stands (architecture §5.2)
        return SettleResult(error=f"{type(exc).__name__}: {exc}")


def _begin(conn: Connection, *row_ids: int) -> dict[int, Any]:
    """Lock in the fixed order and load the rows: settle shared, the account, the rows ascending."""
    lock_settle_shared(conn)
    account = conn.execute(
        text("SELECT account_id FROM source_transaction WHERE id = :i"), {"i": row_ids[0]}
    ).scalar_one_or_none()
    if account is None:
        raise DuplicateRowMissing(row_ids[0])
    lock_accounts(conn, [int(account)])
    lock_rows(conn, "source_transaction", row_ids)
    rows = {
        r.id: r
        for r in conn.execute(
            text(
                "SELECT id, account_id, importer, duplicate_of FROM source_transaction WHERE id = ANY(:ids)"
            ),
            {"ids": list(row_ids)},
        )
    }
    for rid in row_ids:
        if rid not in rows:
            raise DuplicateRowMissing(rid)
    return rows


def _mark(engine: Engine, row_id: int, of_row_id: int, expected: Mapping[int, int] | None) -> Affected:
    with engine.begin() as conn:
        rows = _begin(conn, row_id, of_row_id)
        row, of = rows[row_id], rows[of_row_id]
        if row.account_id != of.account_id:
            raise DuplicateCrossAccount(row_id, of_row_id)
        if row.importer is None:
            raise UserAuthoredRow(row_id, of_row_id, row_id)
        if of.importer is None:
            raise UserAuthoredRow(row_id, of_row_id, of_row_id)
        if row.duplicate_of is not None:
            raise AlreadyDuplicate(row_id)
        if of.duplicate_of is not None:
            raise DuplicateChain(row_id, of_row_id)
        entry_ids = [
            int(i)
            for i in conn.execute(
                text("SELECT id FROM ledger_entry WHERE source_transaction_id = :s ORDER BY id"),
                {"s": row_id},
            ).scalars()
        ]
        if expected is not None:
            removed, partners = entry_scope(conn, entry_ids)
            _check_versions(conn, expected, written=[*removed, *partners])
        # rows that pointed at the marked row follow it to its original (no chains)
        conn.execute(
            text("UPDATE source_transaction SET duplicate_of = :o WHERE duplicate_of = :r"),
            {"o": of_row_id, "r": row_id},
        )
        conn.execute(
            text("UPDATE source_transaction SET duplicate_of = :o WHERE id = :r"),
            {"o": of_row_id, "r": row_id},
        )
        return remove_entries(conn, entry_ids)


def _check_versions(conn: Connection, expected: Mapping[int, int], *, written: Sequence[int]) -> None:
    """Lock the entries the operation writes and those the caller carries versions for (one
    ascending statement) and compare, before any write. Refuses entries whose version moved
    and written entries the caller supplied no version for."""
    lock_rows(conn, "ledger_entry", [*written, *expected])
    ids = sorted({*written, *expected})
    current = {
        int(r.id): int(r.version)
        for r in conn.execute(text("SELECT id, version FROM ledger_entry WHERE id = ANY(:ids)"), {"ids": ids})
    }
    moved = {i for i, v in expected.items() if current.get(i) != v}
    unsupplied = {i for i in written if i not in expected}
    stale = tuple(sorted(moved | unsupplied))
    if stale:
        raise VersionConflict(stale)


def _clear(engine: Engine, row_id: int) -> int:
    with engine.begin() as conn:
        rows = _begin(conn, row_id)
        row = rows[row_id]
        if row.duplicate_of is None:
            raise NotADuplicate(row_id)
        conn.execute(text("UPDATE source_transaction SET duplicate_of = NULL WHERE id = :r"), {"r": row_id})
        entry_id = insert_entry(conn, row_id)
        recompute_derived(conn, int(row.account_id))
        return entry_id
