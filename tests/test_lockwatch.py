"""The lock probes see only the current database's advisory locks (pg_locks is cluster-wide)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.utils.config import Config
from app.utils.db import admin
from app.utils.db.engine import make_engine
from tests import lockwatch

KEY = 7_000_000_001


@pytest.fixture
def other_engine(admin_cfg: Config):
    name = f"test_{uuid.uuid4().hex}"
    admin.create_database(admin_cfg, name)
    engine = make_engine(admin_cfg.with_database(name))
    try:
        yield engine
    finally:
        engine.dispose()
        admin.drop_database(admin_cfg, name)


def test_locks_in_another_database_are_invisible(isolated_engine: Engine, other_engine: Engine) -> None:
    base = lockwatch.advisory_held(isolated_engine)
    with other_engine.connect() as foreign, isolated_engine.connect() as holder:
        foreign.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": KEY})
        assert lockwatch.advisory_held(isolated_engine) == base  # foreign lock not seen
        assert lockwatch.advisory_held(other_engine) == 1  # but visible from its own database
        holder.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": KEY})  # same key, own database
        assert lockwatch.advisory_held(isolated_engine) == base + 1
        assert lockwatch.advisory_held(isolated_engine, exclude_pid=_pid(holder)) == base
        assert lockwatch.advisory_waiters(isolated_engine) == 0


def test_a_waiter_in_another_database_is_not_a_waiter_here(
    isolated_engine: Engine, other_engine: Engine
) -> None:
    import threading

    with other_engine.connect() as first, other_engine.connect() as second:
        first.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": KEY})
        t = threading.Thread(
            target=lambda: (
                second.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": KEY}),
                second.rollback(),
            )
        )
        t.start()
        try:
            lockwatch.wait_until_waiting(other_engine, "foreign waiter", timeout=5)
            assert lockwatch.advisory_waiters(other_engine) == 1
            assert lockwatch.advisory_waiters(isolated_engine) == 0
        finally:
            first.rollback()
            t.join(5)


def _pid(conn) -> int:
    return int(conn.execute(text("SELECT pg_backend_pid()")).scalar_one())
