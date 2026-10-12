"""Advisory locks and the deadlock retry (architecture §5.2 'Lock order').

Order, for every write transaction: the settle lock **shared** first; then the
account locks in ascending id; then row locks in ascending id. Settling takes the
settle lock **exclusively**, in its own transaction, and takes no account lock.
All locks are transaction-scoped: they must be taken inside the transaction they
protect and are released by its commit or rollback.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

import psycopg.errors
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

_NS_SHIFT = 56
_SETTLE_KEY = 1 << _NS_SHIFT
_ACCOUNT_NS = 2 << _NS_SHIFT
_MAX_ID = (1 << _NS_SHIFT) - 1

# Tables whose rows a write may lock; a whitelist because the name is interpolated.
LOCKABLE_TABLES = frozenset(
    {
        "account",
        "balance_record",
        "category",
        "external_document",
        "ledger_entry",
        "payee",
        "source_transaction",
    }
)


class WriteConflict(Exception):
    """A write lost a deadlock twice. It wrote nothing; the caller should try again."""

    def __init__(self) -> None:
        super().__init__("conflict with a concurrent write: try again")


def lock_settle_shared(conn: Connection) -> None:
    """Every write takes this first; writes run alongside each other."""
    conn.execute(text("SELECT pg_advisory_xact_lock_shared(:k)"), {"k": _SETTLE_KEY})


def lock_settle_exclusive(conn: Connection) -> None:
    """Settling: waits for in-flight writes, and no write starts until it ends."""
    conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _SETTLE_KEY})


def lock_accounts(conn: Connection, ids: Iterable[int]) -> list[int]:
    """Lock the accounts in ascending id order; returns the ids locked, in that order."""
    ordered = sorted(set(ids))
    for account_id in ordered:
        if not 0 < account_id <= _MAX_ID:
            raise ValueError(f"invalid account id: {account_id}")
    for account_id in ordered:
        conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _ACCOUNT_NS | account_id})
    return ordered


def lock_rows(conn: Connection, table: str, ids: Iterable[int]) -> list[int]:
    """`SELECT ... FOR UPDATE` on rows of `table` in ascending id order; returns the ids found."""
    if table not in LOCKABLE_TABLES:
        raise ValueError(f"rows of {table!r} are not lockable here")
    ordered = sorted(set(ids))
    if not ordered:
        return []
    rows = conn.execute(
        text(f"SELECT id FROM {table} WHERE id = ANY(:ids) ORDER BY id FOR UPDATE"),  # noqa: S608
        {"ids": ordered},
    ).scalars()
    return [int(i) for i in rows]


def _is_deadlock(exc: BaseException) -> bool:
    if isinstance(exc, psycopg.errors.DeadlockDetected):
        return True
    return isinstance(exc, DBAPIError) and isinstance(exc.orig, psycopg.errors.DeadlockDetected)


def retry_on_deadlock[T](fn: Callable[[], T]) -> T:
    """Run a whole write transaction; if PostgreSQL aborts it as a deadlock victim, run it once
    more, holding the same payload. A second deadlock is a named `WriteConflict`."""
    try:
        return fn()
    except Exception as exc:
        if not _is_deadlock(exc):
            raise
    try:
        return fn()
    except Exception as exc:
        if _is_deadlock(exc):
            raise WriteConflict() from exc
        raise
