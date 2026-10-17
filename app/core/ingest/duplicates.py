"""Marking and clearing duplicates by hand (spec §5.6, architecture §5.2).

Each operation is ONE transaction: settle lock shared, then the account's lock, then row
locks in ascending id; it commits, and only then settles (settling takes the settle lock
exclusively in its own transaction, so it can never run inside this one). A settling
failure is reported on the result, never raised into the committed write. Marking takes
`dry_run`: the same code in a transaction that is rolled back, reporting what a real run would
do and the versions it must carry (as a revert's preview does).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from sqlalchemy import Connection, Engine, text

from app.core.balance.derived import recompute_derived
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
from app.core.ingest.removal import (
    Affected,
    DerivedChange,
    derived_snapshot,
    entry_scope,
    entry_versions,
    remove_entries,
)
from app.core.settle.settle import SettleResult, settle
from app.utils.db.locks import WriteConflict, lock_accounts, lock_rows, lock_settle_shared, retry_on_deadlock


@dataclass(frozen=True)
class OpResult:
    """Response of a duplicate operation: what settling touched, what the removal affected.

    `settle` is None on a dry run. `versions` are the entries the marking writes (removed and unpaired),
    which a real run must carry in `expected_versions`.
    """

    settle: SettleResult | None
    affected: Affected = field(default_factory=Affected)
    created_entry_id: int | None = None  # clear: the entry the row got
    repointed_source_ids: tuple[
        int, ...
    ] = ()  # mark: rows that pointed at the marked row, now at its original
    derived_changes: tuple[DerivedChange, ...] = ()  # mark: accounts whose derived entries differ afterwards
    versions: Mapping[int, int] = field(default_factory=dict)  # mark


def mark_duplicate(
    engine: Engine,
    row_id: int,
    of_row_id: int,
    *,
    expected_versions: Mapping[int, int] | None = None,
    dry_run: bool = False,
) -> OpResult:
    """Mark imported row `row_id` as a duplicate of `of_row_id` (same account, not a duplicate).

    `expected_versions` maps entry id -> the version the caller saw. `None` means "no check".
    A map, even an empty one, must cover EVERY entry the operation writes: the marked row's
    entries and the transfer partners the removal unpairs (architecture §4.1). If a covered
    entry has moved (or is gone), or an entry the operation would write has no version in the
    map (the caller's view was incomplete), `VersionConflict` names them all and nothing is
    written. The marked row's entries are removed through `remove_entries` in the same
    transaction that sets `duplicate_of`, and rows that pointed at it are repointed to `of_row_id`.
    A dry run reports the same result without a settle and writes nothing.
    """
    if row_id == of_row_id:
        raise DuplicateOfSelf(row_id)
    done = retry_on_deadlock(lambda: _mark(engine, row_id, of_row_id, expected_versions, dry_run))
    return done if dry_run else replace(done, settle=settle(engine))


def clear_duplicate(engine: Engine, row_id: int) -> OpResult:
    """'Not a duplicate': clear `duplicate_of` and give the row its one entry, as ingest would."""
    entry_id = retry_on_deadlock(lambda: _clear(engine, row_id))
    return OpResult(settle=settle(engine), created_entry_id=entry_id)


class _AccountsMissing(Exception):
    """The partner set involved accounts that were not locked; retry with them added."""

    def __init__(self, accounts: set[int]) -> None:
        super().__init__("accounts to lock: " + ", ".join(map(str, sorted(accounts))))
        self.accounts = accounts


_LOCK_ROUNDS = 3


def _begin(
    conn: Connection, *row_ids: int, extra_accounts: Iterable[int] = (), partners_of: int | None = None
) -> tuple[dict[int, Any], set[int]]:
    """Lock in the fixed order and load the rows (with the accounts locked): settle shared,
    the accounts ascending (the first row's, `extra_accounts`, and the accounts of the transfer
    partners of `partners_of`'s entries, read before locking), the rows ascending."""
    lock_settle_shared(conn)
    account = conn.execute(
        text("SELECT account_id FROM source_transaction WHERE id = :i"), {"i": row_ids[0]}
    ).scalar_one_or_none()
    if account is None:
        raise DuplicateRowMissing(row_ids[0])
    accounts = {int(account), *extra_accounts}
    if partners_of is not None:
        _, partners = entry_scope(conn, _entry_ids(conn, partners_of))
        accounts |= _accounts_of_entries(conn, partners)
    lock_accounts(conn, accounts)
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
    return rows, accounts


def _entry_ids(conn: Connection, row_id: int) -> list[int]:
    return [
        int(i)
        for i in conn.execute(
            text("SELECT id FROM ledger_entry WHERE source_transaction_id = :s ORDER BY id"), {"s": row_id}
        ).scalars()
    ]


def _accounts_of_entries(conn: Connection, entry_ids: Sequence[int]) -> set[int]:
    if not entry_ids:
        return set()
    return {
        int(a)
        for a in conn.execute(
            text("SELECT DISTINCT account_id FROM ledger_entry WHERE id = ANY(:ids)"),
            {"ids": list(entry_ids)},
        ).scalars()
    }


class _Preview(Exception):
    """Carries a dry run's result out of the transaction, which it rolls back."""

    def __init__(self, result: OpResult) -> None:
        super().__init__("dry run")
        self.result = result


def _mark(
    engine: Engine, row_id: int, of_row_id: int, expected: Mapping[int, int] | None, dry_run: bool
) -> OpResult:
    """Removal rewrites transfer partners that may sit on other accounts, so those are locked
    too (architecture §5.2). They are read before the locks, and read again under them; a
    change in between extends the lock set and the transaction runs again."""
    extra: set[int] = set()
    for _ in range(_LOCK_ROUNDS):
        try:
            return _mark_once(engine, row_id, of_row_id, expected, extra, dry_run)
        except _AccountsMissing as missing:
            extra |= missing.accounts
        except _Preview as preview:
            return preview.result
    raise WriteConflict()


def _mark_once(
    engine: Engine,
    row_id: int,
    of_row_id: int,
    expected: Mapping[int, int] | None,
    extra: set[int],
    dry_run: bool,
) -> OpResult:
    with engine.begin() as conn:
        rows, locked = _begin(conn, row_id, of_row_id, extra_accounts=extra, partners_of=row_id)
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
        scope = entry_scope(conn, _entry_ids(conn, row_id))
        removed, partners = scope
        involved = _accounts_of_entries(conn, partners)
        if not involved <= locked:
            raise _AccountsMissing(involved)
        if expected is not None:
            _check_versions(conn, expected, written=[*removed, *partners])
        else:
            lock_rows(conn, "ledger_entry", [*removed, *partners])
        versions = entry_versions(conn, [*removed, *partners])
        accounts = sorted({int(row.account_id), *involved})
        before = derived_snapshot(conn, accounts)
        # rows that pointed at the marked row follow it to its original (no chains)
        repointed = [
            int(i)
            for i in conn.execute(
                text("UPDATE source_transaction SET duplicate_of = :o WHERE duplicate_of = :r RETURNING id"),
                {"o": of_row_id, "r": row_id},
            ).scalars()
        ]
        conn.execute(
            text("UPDATE source_transaction SET duplicate_of = :o WHERE id = :r"),
            {"o": of_row_id, "r": row_id},
        )
        affected = remove_entries(conn, removed, scope=scope)
        after = derived_snapshot(conn, accounts)
        result = OpResult(
            settle=None,
            affected=affected,
            repointed_source_ids=tuple(sorted(repointed)),
            derived_changes=tuple(
                DerivedChange(a, before[a], after[a]) for a in accounts if before[a] != after[a]
            ),
            versions=versions,
        )
        if dry_run:
            raise _Preview(result)
        return result


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
        rows, _ = _begin(conn, row_id)
        row = rows[row_id]
        if row.duplicate_of is None:
            raise NotADuplicate(row_id)
        conn.execute(text("UPDATE source_transaction SET duplicate_of = NULL WHERE id = :r"), {"r": row_id})
        entry_id = insert_entry(conn, row_id)
        recompute_derived(conn, int(row.account_id))
        return entry_id
