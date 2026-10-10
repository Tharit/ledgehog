"""Reverting a run (spec §5.6 'Reverting a run', I30; architecture §5.2 'revert').

One transaction: settle lock shared, then the accounts' locks ascending (the run's account and
those of every transfer partner its entries have), then the entries' row locks ascending; it
commits, and only then settles (a settling failure is reported on the result, never raised
into the committed write). `dry_run` runs the same code and rolls it back.

Order inside the transaction:

0. the run is set `reverted`, so its balance record stops counting (`v_balance_record`) before
   any recompute;
1. rows of OTHER runs that duplicate a row of this run get a new original: the lowest id is
   cleared and given its entry, the rest are repointed to it;
2. the run's entries are removed through the removal routine;
3. the run's source rows are deleted in one statement;
4. the derived entries of every affected account are recomputed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import Connection, Engine, text

from app.core.balance.derived import recompute_derived
from app.core.ingest.duplicates import _check_versions
from app.core.ingest.entries import insert_entry
from app.core.ingest.removal import entry_scope, remove_entries
from app.core.settle.settle import SettleResult, settle
from app.utils import clock
from app.utils.db.locks import WriteConflict, lock_accounts, lock_rows, lock_settle_shared, retry_on_deadlock


class RevertError(Exception):
    """A revert was refused; the message states the rule. Nothing was written."""


class RunMissing(RevertError):
    def __init__(self, run_id: int) -> None:
        self.run_id = run_id
        super().__init__(f"import run {run_id} does not exist")


class NotRevertible(RevertError):
    def __init__(self, run_id: int, reason: str) -> None:
        self.run_id = run_id
        self.reason = reason
        super().__init__(f"import run {run_id} cannot be reverted: {reason}")


class NotLatestRun(RevertError):
    def __init__(self, run_id: int, newer_run_id: int) -> None:
        self.run_id = run_id
        self.newer_run_id = newer_run_id
        super().__init__(
            f"import run {run_id} is not the account's latest run: "
            f"revert run {newer_run_id} (and any later run) first"
        )


@dataclass(frozen=True)
class DerivedEntry:
    type: str
    booked_on: date
    amount: int


@dataclass(frozen=True)
class DerivedChange:
    """An account whose derived entries (opening, reconciliations, valuations) differ after the revert."""

    account_id: int
    before: tuple[DerivedEntry, ...]
    after: tuple[DerivedEntry, ...]


@dataclass(frozen=True)
class RevertResult:
    run_id: int
    removed_entry_ids: tuple[int, ...] = ()
    partner_entry_ids: tuple[int, ...] = ()  # unpaired and returned to review
    freed_document_ids: tuple[int, ...] = ()
    repointed_source_ids: tuple[tuple[int, int], ...] = ()  # (row id, its new original)
    cleared_duplicate_ids: tuple[int, ...] = ()  # rows that stopped being duplicates, now with an entry
    derived_changes: tuple[DerivedChange, ...] = ()
    versions: Mapping[int, int] = field(default_factory=dict)  # entry id -> version, every entry written
    settle: SettleResult | None = None  # None on a dry run


def revert_run(
    engine: Engine,
    run_id: int,
    *,
    user_id: int | None,
    expected_versions: Mapping[int, int] | None = None,
    dry_run: bool = False,
) -> RevertResult:
    """Revert `run_id`, the latest successful, non-reverted run of its account."""
    result = retry_on_deadlock(lambda: _revert(engine, run_id, user_id, expected_versions, dry_run))
    if dry_run:
        return result
    return _with_settle(result, settle(engine))


def _with_settle(result: RevertResult, settled: SettleResult) -> RevertResult:
    return RevertResult(**{**result.__dict__, "settle": settled})


class _AccountsMissing(Exception):
    """The partner set involved accounts that were not locked; retry with them added."""

    def __init__(self, accounts: set[int]) -> None:
        super().__init__("accounts to lock: " + ", ".join(map(str, sorted(accounts))))
        self.accounts = accounts


class _Preview(Exception):
    """Carries a dry run's result out of the transaction, which it rolls back."""

    def __init__(self, result: RevertResult) -> None:
        super().__init__("dry run")
        self.result = result


_LOCK_ROUNDS = 3


def _revert(
    engine: Engine, run_id: int, user_id: int | None, expected: Mapping[int, int] | None, dry_run: bool
) -> RevertResult:
    extra: set[int] = set()
    for _ in range(_LOCK_ROUNDS):
        try:
            return _revert_once(engine, run_id, user_id, expected, dry_run, extra)
        except _AccountsMissing as missing:
            extra |= missing.accounts
        except _Preview as preview:
            return preview.result
    raise WriteConflict()


def _run_ids(conn: Connection, run_id: int) -> tuple[list[int], list[int]]:
    """(the run's source row ids, the ids of their entries), ascending."""
    rows = [
        int(i)
        for i in conn.execute(
            text("SELECT id FROM source_transaction WHERE import_run_id = :r ORDER BY id"), {"r": run_id}
        ).scalars()
    ]
    entries = [
        int(i)
        for i in conn.execute(
            text("SELECT id FROM ledger_entry WHERE source_transaction_id = ANY(:s) ORDER BY id"), {"s": rows}
        ).scalars()
    ]
    return rows, entries


def _accounts_of_entries(conn: Connection, entry_ids: list[int]) -> set[int]:
    if not entry_ids:
        return set()
    return {
        int(a)
        for a in conn.execute(
            text("SELECT DISTINCT account_id FROM ledger_entry WHERE id = ANY(:ids)"), {"ids": entry_ids}
        ).scalars()
    }


def _check_revertible(conn: Connection, run_id: int, *, locked: bool) -> Any:
    run = conn.execute(
        text(
            "SELECT id, account_id, emits, status FROM import_run WHERE id = :i"
            + (" FOR UPDATE" if locked else "")
        ),
        {"i": run_id},
    ).one_or_none()
    if run is None:
        raise RunMissing(run_id)
    if run.emits != "transactions":
        raise NotRevertible(run_id, f"a {run.emits} run is never reverted")
    if run.status != "ok":
        raise NotRevertible(run_id, f"the run is {run.status}, only a successful run is reverted")
    return run


def _reassign_duplicates(
    conn: Connection, run_id: int, row_ids: list[int]
) -> tuple[tuple[int, ...], tuple[tuple[int, int], ...]]:
    """For each deleted row that rows of other runs duplicate: the lowest id of those stops being a
    duplicate and gets its entry (as 'not a duplicate' does), the others now duplicate it."""
    groups = conn.execute(
        text(
            "SELECT duplicate_of AS original, array_agg(id ORDER BY id) AS dups FROM source_transaction"
            " WHERE duplicate_of = ANY(:rows) AND import_run_id IS DISTINCT FROM :run"
            " GROUP BY duplicate_of ORDER BY duplicate_of"
        ),
        {"rows": row_ids, "run": run_id},
    ).all()
    cleared: list[int] = []
    repointed: list[tuple[int, int]] = []
    for group in groups:
        first, *rest = (int(i) for i in group.dups)
        conn.execute(text("UPDATE source_transaction SET duplicate_of = NULL WHERE id = :i"), {"i": first})
        insert_entry(conn, first)
        if rest:
            conn.execute(
                text("UPDATE source_transaction SET duplicate_of = :o WHERE id = ANY(:ids)"),
                {"o": first, "ids": rest},
            )
        cleared.append(first)
        repointed.extend((i, first) for i in rest)
    return tuple(sorted(cleared)), tuple(sorted(repointed))


def _versions(conn: Connection, entry_ids: list[int]) -> dict[int, int]:
    return {
        int(r.id): int(r.version)
        for r in conn.execute(
            text("SELECT id, version FROM ledger_entry WHERE id = ANY(:ids) ORDER BY id"), {"ids": entry_ids}
        )
    }


def _derived(conn: Connection, accounts: list[int]) -> dict[int, tuple[DerivedEntry, ...]]:
    out: dict[int, tuple[DerivedEntry, ...]] = {a: () for a in accounts}
    for r in conn.execute(
        text(
            "SELECT account_id, type, booked_on, amount FROM ledger_entry WHERE account_id = ANY(:a)"
            " AND balance_record_id IS NOT NULL ORDER BY account_id, booked_on, id"
        ),
        {"a": accounts},
    ):
        out[r.account_id] = (*out[r.account_id], DerivedEntry(r.type, r.booked_on, r.amount))
    return out


def _revert_once(
    engine: Engine,
    run_id: int,
    user_id: int | None,
    expected: Mapping[int, int] | None,
    dry_run: bool,
    extra: set[int],
) -> RevertResult:
    with engine.begin() as conn:
        lock_settle_shared(conn)
        run = _check_revertible(conn, run_id, locked=False)
        account_id = int(run.account_id)
        _, first_entries = _run_ids(conn, run_id)
        _, first_partners = entry_scope(conn, first_entries)
        accounts = {account_id, *extra, *_accounts_of_entries(conn, first_partners)}
        locked = set(lock_accounts(conn, accounts))
        # The first look was before the lock wait: judge the run as it is now, row-locked.
        _check_revertible(conn, run_id, locked=True)
        newer = conn.execute(
            text(
                "SELECT id FROM import_run WHERE account_id = :a AND emits = 'transactions' AND status = 'ok'"
                " ORDER BY finished_at DESC NULLS LAST, id DESC LIMIT 1"
            ),
            {"a": account_id},
        ).scalar_one()
        if int(newer) != run_id:
            raise NotLatestRun(run_id, int(newer))

        row_ids, entry_ids = _run_ids(conn, run_id)
        scope = entry_scope(conn, entry_ids)
        removed, partners = scope
        involved = _accounts_of_entries(conn, partners)
        if not involved <= locked:
            raise _AccountsMissing(involved)
        written = [*removed, *partners]
        if expected is not None:
            _check_versions(conn, expected, written=written)  # locks, compares, before any write
        else:
            lock_rows(conn, "ledger_entry", written)
        versions = _versions(conn, written)
        affected_accounts = sorted({account_id} | involved)
        before = _derived(conn, affected_accounts)

        # 0. the run stops counting before any recompute
        conn.execute(
            text(
                "UPDATE import_run SET status = 'reverted', reverted_at = :at, reverted_by = :by"
                " WHERE id = :i"
            ),
            {"at": clock.now(), "by": user_id, "i": run_id},
        )
        # 1. rows of other runs that duplicate a row of this run get a new original
        cleared, repointed = _reassign_duplicates(conn, run_id, row_ids)
        # 2. entries (the removal routine), 3. rows, 4. derived entries
        affected = remove_entries(conn, removed, scope=scope)
        if row_ids:
            conn.execute(text("DELETE FROM source_transaction WHERE id = ANY(:ids)"), {"ids": row_ids})
        for acct in affected_accounts:
            recompute_derived(conn, acct)
        after = _derived(conn, affected_accounts)
        result = RevertResult(
            run_id=run_id,
            removed_entry_ids=affected.removed_entry_ids,
            partner_entry_ids=affected.partner_entry_ids,
            freed_document_ids=affected.freed_document_ids,
            repointed_source_ids=repointed,
            cleared_duplicate_ids=cleared,
            versions=versions,
            derived_changes=tuple(
                DerivedChange(a, before[a], after[a]) for a in affected_accounts if before[a] != after[a]
            ),
        )
        if dry_run:
            raise _Preview(result)
        return result
