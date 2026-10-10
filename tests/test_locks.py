"""Lock helpers (architecture §5.2 'Lock order'). Real connections, real commits."""

import threading
import time
from collections.abc import Callable

import psycopg
import pytest
from sqlalchemy import Engine, text

from app.utils.db import locks
from app.utils.db.engine import make_engine


def _try_lock_timeout(engine: Engine, fn: Callable) -> bool:
    """True if `fn(conn)` got its lock within 300 ms on a separate connection."""
    with engine.connect() as conn:
        conn.execute(text("SET lock_timeout = '300ms'"))
        try:
            fn(conn)
            return True
        except Exception as exc:  # noqa: BLE001
            if "lock timeout" in str(exc) or "LockNotAvailable" in repr(exc):
                return False
            raise
        finally:
            conn.rollback()


def test_shared_settle_locks_do_not_block_each_other(isolated_engine: Engine):
    with isolated_engine.connect() as a:
        locks.lock_settle_shared(a)
        assert _try_lock_timeout(isolated_engine, locks.lock_settle_shared)
        a.rollback()


def test_exclusive_settle_lock_waits_for_writers_and_blocks_new_ones(isolated_engine: Engine):
    with isolated_engine.connect() as writer:
        locks.lock_settle_shared(writer)
        assert not _try_lock_timeout(isolated_engine, locks.lock_settle_exclusive)
        writer.rollback()
    with isolated_engine.connect() as settler:
        locks.lock_settle_exclusive(settler)
        assert not _try_lock_timeout(isolated_engine, locks.lock_settle_shared)
        assert not _try_lock_timeout(isolated_engine, locks.lock_settle_exclusive)
        settler.rollback()
    assert _try_lock_timeout(isolated_engine, locks.lock_settle_exclusive)


def test_locks_release_at_transaction_end(isolated_engine: Engine):
    with isolated_engine.connect() as a:
        locks.lock_settle_exclusive(a)
        locks.lock_accounts(a, [5])
        a.commit()
    assert _try_lock_timeout(isolated_engine, locks.lock_settle_exclusive)
    assert _try_lock_timeout(isolated_engine, lambda c: locks.lock_accounts(c, [5]))


def test_account_locks_are_per_account(isolated_engine: Engine):
    with isolated_engine.connect() as a:
        locks.lock_accounts(a, [1])
        assert not _try_lock_timeout(isolated_engine, lambda c: locks.lock_accounts(c, [1]))
        assert _try_lock_timeout(isolated_engine, lambda c: locks.lock_accounts(c, [2]))
        a.rollback()


def test_account_locks_do_not_collide_with_the_settle_lock(isolated_engine: Engine):
    with isolated_engine.connect() as a:
        locks.lock_settle_exclusive(a)
        assert _try_lock_timeout(isolated_engine, lambda c: locks.lock_accounts(c, [1, 2, 3]))
        a.rollback()


def test_lock_accounts_returns_ids_sorted_and_deduplicated(db_conn):
    assert locks.lock_accounts(db_conn, [3, 1, 2, 3]) == [1, 2, 3]
    assert locks.lock_accounts(db_conn, []) == []


def test_lock_accounts_rejects_non_positive_ids(db_conn):
    with pytest.raises(ValueError):
        locks.lock_accounts(db_conn, [0])


def test_account_locks_are_taken_in_ascending_id_order(isolated_engine: Engine):
    """B asks for [1, 2] while A holds 2: B must already hold 1 and be waiting on 2."""
    with isolated_engine.connect() as a:
        locks.lock_accounts(a, [2])
        result: list[object] = []

        def b() -> None:
            with isolated_engine.connect() as conn:
                locks.lock_accounts(conn, [2, 1])  # requested descending on purpose
                result.append("done")
                conn.rollback()

        t = threading.Thread(target=b)
        t.start()
        try:
            deadline = time.monotonic() + 5
            waiting = 0
            with isolated_engine.connect() as probe:
                while time.monotonic() < deadline and not waiting:
                    waiting = probe.execute(
                        text("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND NOT granted")
                    ).scalar_one()
                    time.sleep(0.02)
                granted = probe.execute(
                    text("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND granted")
                ).scalar_one()
            assert waiting == 1
            assert granted == 2  # A's lock on 2, B's lock on 1 (taken first), B waits on 2
            assert result == []
        finally:
            a.rollback()
            t.join(5)
        assert result == ["done"]


def test_opposite_request_orders_never_deadlock(isolated_engine: Engine):
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def worker(ids: list[int]) -> None:
        try:
            barrier.wait()
            for _ in range(40):
                with isolated_engine.connect() as conn:
                    locks.lock_accounts(conn, ids)
                    conn.rollback()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(ids,)) for ids in ([1, 2, 3], [3, 2, 1])]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert errors == []


def test_lock_rows_locks_in_ascending_id_order_and_returns_them(db_conn, make_account):
    ids = [make_account(db_conn, name=f"a{i}", external_ref=f"x{i}") for i in range(3)]
    assert locks.lock_rows(db_conn, "account", [ids[2], ids[0], ids[1], ids[0]]) == sorted(ids)


def test_lock_rows_refuses_unknown_tables(db_conn):
    with pytest.raises(ValueError):
        locks.lock_rows(db_conn, "account; DROP TABLE account", [1])
    with pytest.raises(ValueError):
        locks.lock_rows(db_conn, "pg_class", [1])


# -- deadlock retry ----------------------------------------------------------


def _deadlock() -> Exception:
    return psycopg.errors.DeadlockDetected("deadlock detected")


def test_retry_returns_the_result_without_retrying_on_success():
    calls = []
    assert locks.retry_on_deadlock(lambda: calls.append(1) or "ok") == "ok"
    assert calls == [1]


def test_retry_runs_once_more_after_a_deadlock():
    calls = []

    def fn():
        calls.append(1)
        if len(calls) == 1:
            raise _deadlock()
        return "second"

    assert locks.retry_on_deadlock(fn) == "second"
    assert len(calls) == 2


def test_second_deadlock_becomes_a_named_conflict_error():
    calls = []

    def fn():
        calls.append(1)
        raise _deadlock()

    with pytest.raises(locks.WriteConflict) as e:
        locks.retry_on_deadlock(fn)
    assert len(calls) == 2
    assert "try again" in str(e.value).lower()


def test_deadlock_wrapped_by_sqlalchemy_is_recognised():
    from sqlalchemy.exc import OperationalError

    calls = []

    def fn():
        calls.append(1)
        raise OperationalError("stmt", {}, _deadlock())

    with pytest.raises(locks.WriteConflict):
        locks.retry_on_deadlock(fn)
    assert len(calls) == 2


def test_other_errors_propagate_unretried():
    calls = []

    def fn():
        calls.append(1)
        raise KeyError("boom")

    with pytest.raises(KeyError):
        locks.retry_on_deadlock(fn)
    assert calls == [1]


def test_a_real_deadlock_is_retried_to_success(isolated_engine: Engine):
    """Two writers take two raw advisory locks in opposite order: PostgreSQL aborts one; the
    retry then succeeds."""
    first_try_gate = threading.Barrier(2)
    attempts = {"A": 0, "B": 0}
    results: dict[str, object] = {}

    def make(name: str, first: int, second: int) -> Callable[[], str]:
        def attempt() -> str:
            attempts[name] += 1
            with isolated_engine.connect() as conn:
                try:
                    conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": first})
                    if attempts[name] == 1:
                        first_try_gate.wait(5)
                    conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": second})
                    conn.commit()
                    return name
                except BaseException:
                    conn.rollback()
                    raise

        return attempt

    def run(name: str, first: int, second: int) -> None:
        try:
            results[name] = locks.retry_on_deadlock(make(name, first, second))
        except BaseException as exc:  # noqa: BLE001
            results[name] = exc

    threads = [
        threading.Thread(target=run, args=("A", 9001, 9002)),
        threading.Thread(target=run, args=("B", 9002, 9001)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert results == {"A": "A", "B": "B"}
    assert sorted(attempts.values()) == [1, 2]  # exactly one was the victim
