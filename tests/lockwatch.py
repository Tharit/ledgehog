"""Advisory-lock probes for tests, scoped to the current database.

`pg_locks` spans the whole cluster. Concurrent test runs in other databases (parallel agents,
developers) hold advisory locks of their own, which would satisfy or break assertions such as
"the write is waiting" or "exactly one lock is held". Advisory locks are per database and
`pg_locks.database` carries the OID of the database of the session that took them, so every
probe here filters on the current database. Never query `pg_locks` directly in a test.

Probes take an Engine (a short-lived probe connection per call) or a Connection.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, Row, text

Source = Engine | Connection

HERE = "pg_locks.database = (SELECT oid FROM pg_database WHERE datname = current_database())"
_ADVISORY = f"pg_locks.locktype = 'advisory' AND {HERE}"


def _run(src: Source, sql: str, params: dict[str, Any]) -> list[Row[Any]]:
    if isinstance(src, Engine):
        with src.connect() as conn:
            return list(conn.execute(text(sql), params).all())
    return list(src.execute(text(sql), params).all())


def advisory_waiters(src: Source) -> int:
    """Backends in this database currently waiting for an advisory lock."""
    return int(_run(src, f"SELECT count(*) FROM pg_locks WHERE {_ADVISORY} AND NOT granted", {})[0][0])


def advisory_held(
    src: Source,
    *,
    exclude_pid: int | None = None,
    classid: int | None = None,
    mode: str | None = None,
) -> int:
    """Granted advisory locks in this database, optionally not those of `exclude_pid`, of one
    `classid` (high 32 bits of the key) and/or one lock `mode`."""
    sql = f"SELECT count(*) FROM pg_locks WHERE {_ADVISORY} AND granted"
    params: dict[str, Any] = {}
    if exclude_pid is not None:
        sql += " AND pid <> :pid"
        params["pid"] = exclude_pid
    if classid is not None:
        sql += " AND classid = :classid"
        params["classid"] = classid
    if mode is not None:
        sql += " AND mode = :mode"
        params["mode"] = mode
    return int(_run(src, sql, params)[0][0])


def own_advisory_locks(conn: Connection) -> list[tuple[str, int]]:
    """(mode, key >> 56) of the granted advisory locks held by `conn`'s own backend."""
    rows = _run(
        conn,
        "SELECT mode, (classid::bigint << 32 | objid::bigint) >> 56 AS ns FROM pg_locks "
        f"WHERE {_ADVISORY} AND pid = pg_backend_pid() AND granted",
        {},
    )
    return [(r.mode, int(r.ns)) for r in rows]


def wait_until_waiting(src: Source, what: str, *, at_least: int = 1, timeout: float = 8.0) -> None:
    """Poll until at least `at_least` backends wait for an advisory lock; fail on timeout."""
    deadline = time.monotonic() + timeout
    while advisory_waiters(src) < at_least:
        if time.monotonic() > deadline:
            pytest.fail(f"timed out waiting for {what}")
        if isinstance(src, Connection):
            src.rollback()  # a fresh snapshot of pg_locks each poll
        time.sleep(0.01)


def row_lock_waiters(src: Source) -> int:
    """Backends in this database currently waiting for a row lock (a wait on another transaction).

    Row-lock waits show in `pg_locks` as a `transactionid` lock without a database, so the
    database filter is applied on `pg_stat_activity` instead.
    """
    sql = (
        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
        " AND wait_event_type = 'Lock' AND wait_event = 'transactionid'"
    )
    return int(_run(src, sql, {})[0][0])


def wait_until_row_waiting(src: Source, what: str, *, at_least: int = 1, timeout: float = 8.0) -> None:
    """Poll until at least `at_least` backends wait for a row lock; fail on timeout."""
    deadline = time.monotonic() + timeout
    while row_lock_waiters(src) < at_least:
        if time.monotonic() > deadline:
            pytest.fail(f"timed out waiting for {what}")
        if isinstance(src, Connection):
            src.rollback()
        time.sleep(0.01)
