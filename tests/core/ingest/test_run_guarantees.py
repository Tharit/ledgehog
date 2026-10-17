"""Atomicity, serialisation per account (I39) and the settle-after-commit contract."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import text

from app.core.domain.errors import ContractViolation, IngestError
from app.core.ingest import run as run_module
from app.core.ingest.run import ingest_delivery, start_run
from app.core.settle.settle import SettleResult
from app.utils.db.locks import lock_accounts
from tests import lockwatch
from tests.core.ingest.conftest import THROUGH, Env, row


def test_late_row_failure_leaves_nothing_and_run_failed(env: Env) -> None:
    rows = [
        row(-1, source_id="a"),
        row(-2, source_id="b"),
        # instructed currency unknown to the schema: this row alone cannot be written
        row(-3, source_id="c", instructed_amount_minor=-4, instructed_currency="ZZZ"),
    ]
    run_id = start_run(env.engine, env.account, "transactions", importer="csv")
    with pytest.raises(Exception, match="ZZZ"):
        ingest_delivery(env.engine, run_id, rows, covered_through=THROUGH)
    assert env.count("source_transaction") == 0 and env.count("ledger_entry") == 0
    r = env.run_row(run_id)
    assert r.status == "failed" and r.covered_through is None and r.finished_at is not None
    # a database error's message quotes the failing value: only its type is stored
    assert r.error_text == "IntegrityError: unexpected error"
    assert r.retryable is False  # any other unexpected exception


def test_duplicate_source_id_in_one_delivery_fails_the_run(env: Env) -> None:
    run_id = start_run(env.engine, env.account, "transactions", importer="csv")
    with pytest.raises(ContractViolation):
        ingest_delivery(
            env.engine, run_id, [row(-1, source_id="a"), row(-2, source_id="a")], covered_through=THROUGH
        )
    assert env.count("source_transaction") == 0
    assert env.run_row(run_id).status == "failed"


def _advisory_waiters(env: Env) -> int:
    return lockwatch.advisory_waiters(env.engine)


def _until(cond: Callable[[], bool], what: str, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            pytest.fail(f"timed out waiting for {what}")
        time.sleep(0.02)


def test_concurrent_sync_of_the_same_account_waits_for_the_account_lock(env: Env) -> None:
    done: dict[str, Any] = {}

    def sync() -> None:
        done["result"] = env.deliver([row(-500, source_id="a")])

    with env.engine.connect() as holder:
        with holder.begin():
            lock_accounts(holder, [env.account])
            thread = threading.Thread(target=sync)
            thread.start()
            _until(lambda: _advisory_waiters(env) >= 1, "the sync to block on the account lock")
            assert thread.is_alive() and "result" not in done
            assert env.count("source_transaction") == 0
        # the holder's commit released the lock
    thread.join(timeout=15)
    assert not thread.is_alive() and done["result"].inserted == 1


def test_concurrent_syncs_of_one_account_serialise_dedup(env: Env) -> None:
    """Two credentials fetch the same bookings at once: serialised, one inserts, the other pairs."""
    n = 6
    barrier = threading.Barrier(2)
    results: list[Any] = []
    errors: list[BaseException] = []

    def sync(importer: str) -> None:
        try:
            rows = [row(-100 - i, source_id=f"{importer}-{i}") for i in range(n)]
            run_id = start_run(env.engine, env.account, "transactions", importer=importer)
            barrier.wait(timeout=10)
            results.append(ingest_delivery(env.engine, run_id, rows, covered_through=THROUGH))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=sync, args=(name,)) for name in ("anna", "ben")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, errors
    assert sorted((r.inserted, len(r.duplicates)) for r in results) == [(0, n), (n, 0)]
    assert env.count("ledger_entry") == n


def test_settle_runs_once_after_commit_and_a_failure_keeps_the_write(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def spy(engine: Any) -> SettleResult:
        with engine.connect() as conn:  # a separate connection sees only committed state
            calls.append(
                conn.execute(text("SELECT count(*) FROM ledger_entry")).scalar_one()
                + 100 * conn.execute(text("SELECT count(*) FROM import_run WHERE status = 'ok'")).scalar_one()
            )
        return SettleResult(touched_entry_ids=(7,))

    monkeypatch.setattr(run_module, "settle", spy)
    res = env.deliver([row(-1, source_id="a"), row(-2, source_id="b")])
    assert calls == [102]  # exactly once; two entries and the ok run already visible
    assert res.settle.touched_entry_ids == (7,)

    def boom(engine: Any) -> SettleResult:
        return SettleResult(error="RuntimeError: settle exploded")

    monkeypatch.setattr(run_module, "settle", boom)
    res = env.deliver([row(-3, source_id="c")])
    assert res.settle.error is not None and "settle exploded" in res.settle.error
    assert res.inserted == 1 and env.count("ledger_entry") == 3
    assert env.run_row(res.run_id).status == "ok"


def test_settle_error_result_is_passed_through(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_module, "settle", lambda engine: SettleResult(error="late failure"))
    res = env.deliver([row(-1, source_id="a")])
    assert res.settle.error == "late failure" and env.count("ledger_entry") == 1


def test_failed_delivery_does_not_settle(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[int] = []
    monkeypatch.setattr(run_module, "settle", lambda engine: called.append(1) or SettleResult())
    run_id = start_run(env.engine, env.account, "transactions", importer="csv")
    with pytest.raises(ContractViolation):
        ingest_delivery(env.engine, run_id, [row(source_id="a"), row(source_id="a")], covered_through=THROUGH)
    assert called == []


def test_two_concurrent_deliveries_for_one_run_let_exactly_one_win(env: Env) -> None:
    """Both pass the (unlocked) look at the run while the account lock is held elsewhere; the
    loser must see the winner's `ok` once it gets the lock, not its own stale `running`."""
    run_id = start_run(env.engine, env.account, "transactions", importer="csv")
    outcomes: list[Any] = []

    def deliver(tag: str) -> None:
        try:
            outcomes.append(
                ingest_delivery(
                    env.engine,
                    run_id,
                    [row(-100, source_id=tag)],
                    covered_through=THROUGH,
                    importer_stats={"filtered": len(tag)},
                )
            )
        except BaseException as exc:  # noqa: BLE001
            outcomes.append(exc)

    threads = [threading.Thread(target=deliver, args=(tag,)) for tag in ("a", "bb")]
    with env.engine.connect() as holder:
        with holder.begin():
            lock_accounts(holder, [env.account])
            for t in threads:
                t.start()
            _until(lambda: _advisory_waiters(env) >= 2, "both deliveries to wait for the account lock")
    for t in threads:
        t.join(timeout=30)
    wins = [o for o in outcomes if not isinstance(o, BaseException)]
    losses = [o for o in outcomes if isinstance(o, BaseException)]
    assert len(wins) == 1 and len(losses) == 1, outcomes
    assert isinstance(losses[0], IngestError) and "not running" in str(losses[0])
    stored = env.run_row(run_id)
    assert stored.status == "ok" and stored.covered_through == THROUGH and stored.error_text is None
    assert stored.stats["importer"] == dict(wins[0].importer_stats) and stored.stats["inserted"] == 1
    assert env.count("source_transaction") == 1


def test_a_failing_fail_run_does_not_mask_the_original_error(
    env: Env, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(engine: Any, run_id: int, error: str, *, retryable: bool = False) -> None:
        raise RuntimeError("cannot record the failure")

    monkeypatch.setattr(run_module, "fail_run", broken)
    run_id = start_run(env.engine, env.account, "transactions", importer="csv")
    with pytest.raises(ContractViolation):
        ingest_delivery(env.engine, run_id, [row(source_id="a"), row(source_id="a")], covered_through=THROUGH)
    assert "RuntimeError" in caplog.text and "cannot record the failure" not in caplog.text
    assert env.count("source_transaction") == 0


def test_an_interrupt_during_the_write_rolls_back_marks_the_run_failed_and_propagates(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupted(conn: Any, source_ids: Any) -> list[int]:
        raise KeyboardInterrupt

    monkeypatch.setattr(run_module, "insert_entries", interrupted)
    run_id = start_run(env.engine, env.account, "transactions", importer="csv")
    with pytest.raises(KeyboardInterrupt):
        ingest_delivery(env.engine, run_id, [row(-1, source_id="a")], covered_through=THROUGH)
    assert env.count("source_transaction") == 0
    r = env.run_row(run_id)
    assert r.status == "failed" and r.finished_at is not None and "KeyboardInterrupt" in r.error_text
