"""Noting what a transaction changes, and reporting it once the transaction has committed
(architecture §5.2 'Change values move on commit, from the locks').

The lock helpers (`locks.py`) and settling call `note_change(conn, key)`. The notes live on the
connection's `info` (the pooled DBAPI connection's, so a note survives only as long as we let it) and
move through three states:

* noted        -- in the open transaction;
* committed    -- the transaction's `commit` was issued: the notes are the ones to report;
* reported     -- the connection went back to the pool, which is after the commit took effect, and
                  `sink` was called with the keys. Reporting after the commit rather than at it means a
                  client that reads a new value always finds the data behind it.

A rollback (a dry run, a failed write) drops the notes of the transaction; so does a connection that is
checked out again with notes left over (an invalidated one). The sink is injected by the composition
root (`create_app`): `utils` does not know the register, which lives in `core.tasks`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import Connection, Engine, event

LEDGER = "ledger"
DOCUMENTS = "documents"
ACCOUNT_PREFIX = "account:"

_NOTED = "ledgehog.changes.noted"
_COMMITTED = "ledgehog.changes.committed"


def account_key(account_id: int) -> str:
    return f"{ACCOUNT_PREFIX}{account_id}"


def note_change(conn: Connection, key: str) -> None:
    """Note that the open transaction touches `key`; it counts only if the transaction commits."""
    conn.info.setdefault(_NOTED, set()).add(key)


def install_change_hooks(engine: Engine, sink: Callable[[frozenset[str]], None]) -> None:
    """Report to `sink` the keys of every transaction that commits on `engine`'s connections."""

    @event.listens_for(engine, "commit")
    def _commit(conn: Connection) -> None:
        noted = conn.info.pop(_NOTED, None)
        if noted:
            conn.info.setdefault(_COMMITTED, set()).update(noted)

    @event.listens_for(engine, "rollback")
    def _rollback(conn: Connection) -> None:
        conn.info.pop(_NOTED, None)

    @event.listens_for(engine.pool, "checkout")
    def _checkout(dbapi_conn: Any, record: Any, proxy: Any) -> None:
        record.info.pop(_NOTED, None)
        record.info.pop(_COMMITTED, None)

    @event.listens_for(engine.pool, "checkin")
    def _checkin(dbapi_conn: Any, record: Any) -> None:
        if record is None:
            return
        record.info.pop(_NOTED, None)
        committed = record.info.pop(_COMMITTED, None)
        if committed:
            sink(frozenset(committed))
