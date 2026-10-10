"""Writing balance records: reported (by ingest) and manual (set, edit, delete) (spec §3.10, §5.10)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from app.core.balance import records
from app.core.balance.derived import recompute_derived
from app.core.balance.records import (
    AccountNotFound,
    RecordDateTaken,
    RecordNotFound,
    ReportedRecordNotEditable,
    delete_record,
    insert_reported_record,
    set_manual_record,
    update_manual_record,
)
from app.core.settle.settle import SettleResult
from app.utils.db.locks import lock_accounts, lock_settle_exclusive
from tests import lockwatch
from tests.core.balance.scene import assert_checks_clean, day
from tests.invariants.helpers import (
    link_account,
    make_entry,
    make_instance,
    make_run,
    make_source,
)

Make = Callable[..., int]

USER = 1  # no row is written for it: records carry no author (spec §3.2)


@dataclass
class Env:
    engine: Engine
    account: int

    def q(self, sql: str, **params: Any) -> list[Any]:
        with self.engine.connect() as conn:
            return list(conn.execute(text(sql), params).all())

    def derived(self) -> list[tuple[str, date, int]]:
        return [
            (r.type, r.booked_on, r.amount)
            for r in self.q(
                "SELECT type, booked_on, amount FROM ledger_entry "
                "WHERE account_id = :a AND balance_record_id IS NOT NULL ORDER BY booked_on, id",
                a=self.account,
            )
        ]

    def move(self, on: date, amount: int) -> None:
        with self.engine.begin() as conn:
            make_entry(conn, make_source(conn, self.account, amount=amount, booked_on=on))

    def checks_clean(self) -> None:
        with self.engine.begin() as conn:
            assert_checks_clean(conn)


@pytest.fixture
def env(isolated_engine: Engine, make_account: Make) -> Env:
    with isolated_engine.begin() as conn:
        account = make_account(conn)
    return Env(isolated_engine, account)


# ---- reported records (ingest writes them, then recomputes) ---------------------------------


def test_insert_reported_record_writes_the_run_record_in_the_account_currency(
    env: Env,
) -> None:
    with env.engine.begin() as conn:
        run = make_run(conn, env.account, covered_through=day(3, 1))
        rid = insert_reported_record(
            conn, account_id=env.account, import_run_id=run, balance_on=day(3, 1), balance=1234
        )
    (row,) = env.q("SELECT * FROM balance_record WHERE id = :i", i=rid)
    assert (row.kind, row.import_run_id, row.balance, row.currency, row.balance_on) == (
        "reported",
        run,
        1234,
        "EUR",
        day(3, 1),
    )
    assert env.derived() == []  # the ingest transaction recomputes, not this function


def test_a_run_has_at_most_one_reported_record(env: Env) -> None:
    with env.engine.connect() as conn:
        run = make_run(conn, env.account, covered_through=day(3, 1))
        insert_reported_record(
            conn, account_id=env.account, import_run_id=run, balance_on=day(3, 1), balance=1
        )
        with pytest.raises(IntegrityError):
            insert_reported_record(
                conn, account_id=env.account, import_run_id=run, balance_on=day(3, 1), balance=2
            )
        conn.rollback()


# ---- set / edit / delete --------------------------------------------------------------------


def test_set_manual_record_creates_the_record_and_its_opening_then_settles(env: Env) -> None:
    result = set_manual_record(env.engine, env.account, day(1, 1), 10_000, user_id=USER)
    (row,) = env.q("SELECT * FROM balance_record WHERE id = :i", i=result.record_id)
    assert (row.kind, row.import_run_id, row.balance, row.balance_on, row.currency) == (
        "manual",
        None,
        10_000,
        day(1, 1),
        "EUR",
    )
    assert env.derived() == [("opening", date(2025, 12, 31), 10_000)]
    assert result.settle.error is None
    env.checks_clean()


def test_setting_a_balance_on_a_date_that_has_one_edits_it(env: Env) -> None:
    first = set_manual_record(env.engine, env.account, day(1, 1), 10_000, user_id=USER)
    second = set_manual_record(env.engine, env.account, day(1, 1), 7_000, user_id=USER)
    assert second.record_id == first.record_id
    assert env.q("SELECT balance FROM balance_record") == [(7_000,)]
    assert env.derived() == [("opening", date(2025, 12, 31), 7_000)]
    env.checks_clean()


def test_a_manual_record_on_a_later_date_reconciles(env: Env) -> None:
    env.move(day(1, 5), -2_000)
    set_manual_record(env.engine, env.account, day(1, 1), 10_000, user_id=USER)
    set_manual_record(env.engine, env.account, day(1, 31), 4_000, user_id=USER)
    assert env.derived() == [("opening", date(2025, 12, 31), 10_000), ("reconciliation", day(1, 31), -4_000)]
    env.checks_clean()


def test_set_manual_record_on_an_unknown_account_is_a_named_error(env: Env) -> None:
    with pytest.raises(AccountNotFound):
        set_manual_record(env.engine, env.account + 999, day(1, 1), 1, user_id=USER)


def test_update_manual_record_edits_the_balance_and_may_move_the_date(env: Env) -> None:
    set_manual_record(env.engine, env.account, day(1, 1), 10_000, user_id=USER)
    rid = set_manual_record(env.engine, env.account, day(2, 1), 9_000, user_id=USER).record_id
    update_manual_record(env.engine, rid, balance=8_000)
    assert env.derived()[-1] == ("reconciliation", day(2, 1), -2_000)
    update_manual_record(env.engine, rid, balance=8_000, balance_on=day(3, 1))
    assert env.derived()[-1] == ("reconciliation", day(3, 1), -2_000)
    env.checks_clean()


def test_moving_a_record_onto_a_date_with_a_manual_record_is_refused(env: Env) -> None:
    set_manual_record(env.engine, env.account, day(1, 1), 10_000, user_id=USER)
    rid = set_manual_record(env.engine, env.account, day(2, 1), 9_000, user_id=USER).record_id
    with pytest.raises(RecordDateTaken):
        update_manual_record(env.engine, rid, balance=1, balance_on=day(1, 1))
    assert env.q("SELECT balance_on FROM balance_record WHERE id = :i", i=rid) == [(day(2, 1),)]


def test_a_reported_record_is_not_editable(env: Env) -> None:
    with env.engine.begin() as conn:
        run = make_run(conn, env.account, covered_through=day(3, 1))
        rid = insert_reported_record(
            conn, account_id=env.account, import_run_id=run, balance_on=day(3, 1), balance=5
        )
    with pytest.raises(ReportedRecordNotEditable):
        update_manual_record(env.engine, rid, balance=6)
    assert env.q("SELECT balance FROM balance_record WHERE id = :i", i=rid) == [(5,)]


def test_updating_or_deleting_a_missing_record_is_a_named_error(env: Env) -> None:
    with pytest.raises(RecordNotFound):
        update_manual_record(env.engine, 424242, balance=1)
    with pytest.raises(RecordNotFound):
        delete_record(env.engine, 424242)


def test_deleting_the_anchor_hands_the_opening_to_the_next_record(env: Env) -> None:
    env.move(day(1, 15), -100)
    first = set_manual_record(env.engine, env.account, day(1, 1), 1_000, user_id=USER).record_id
    set_manual_record(env.engine, env.account, day(2, 1), 700, user_id=USER)
    result = delete_record(env.engine, first)
    assert result.record_id == first and result.settle.error is None
    assert env.derived() == [("opening", day(1, 14), 800)]
    env.checks_clean()


def test_deleting_a_reported_record_keeps_its_runs_coverage_and_drops_its_entry(
    env: Env,
) -> None:
    with env.engine.begin() as conn:
        run = make_run(conn, env.account, covered_through=day(3, 1))
        rid = insert_reported_record(
            conn, account_id=env.account, import_run_id=run, balance_on=day(2, 1), balance=900
        )
    set_manual_record(env.engine, env.account, day(1, 1), 1_000, user_id=USER)
    with env.engine.begin() as conn:
        recompute_derived(conn, env.account)
    assert len(env.derived()) == 2
    delete_record(env.engine, rid)
    assert env.derived() == [("opening", date(2025, 12, 31), 1_000)]
    assert env.q("SELECT synced_through FROM v_account_coverage WHERE account_id = :a", a=env.account) == [
        (day(3, 1),)
    ]
    env.checks_clean()


def test_a_manual_record_on_a_synced_account_does_not_reset_its_data_age(env: Env) -> None:
    with env.engine.begin() as conn:
        link_account(conn, env.account, make_instance(conn))
        make_run(conn, env.account, covered_through=day(3, 1))
    set_manual_record(env.engine, env.account, day(6, 1), 1, user_id=USER)
    assert env.q("SELECT last_data_on FROM v_account_data_age WHERE account_id = :a", a=env.account) == [
        (day(3, 1),)
    ]


# ---- settling -------------------------------------------------------------------------------


def test_settle_runs_once_after_the_write_has_committed(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[int] = []

    def fake(engine: Engine) -> SettleResult:
        seen.append(len(env.q("SELECT 1 FROM balance_record")))  # a fresh connection sees the commit
        return SettleResult()

    monkeypatch.setattr(records, "settle", fake)
    set_manual_record(env.engine, env.account, day(1, 1), 1, user_id=USER)
    assert seen == [1]


def test_a_settle_error_does_not_undo_the_write(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(records, "settle", lambda e: SettleResult(error="boom"))
    result = set_manual_record(env.engine, env.account, day(1, 1), 1_000, user_id=USER)
    assert result.settle.error == "boom"
    assert env.q("SELECT balance FROM balance_record") == [(1_000,)]
    assert env.derived() == [("opening", date(2025, 12, 31), 1_000)]


def test_a_refused_write_does_not_settle(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake(engine: Engine) -> SettleResult:
        calls.append(1)
        return SettleResult()

    monkeypatch.setattr(records, "settle", fake)
    with pytest.raises(RecordNotFound):
        delete_record(env.engine, 999)
    assert calls == []


# ---- lock order -----------------------------------------------------------------------------

_SETTLE_CLASS = 1 << 24
_ACCOUNT_CLASS = 2 << 24


def _waiters(env: Env) -> int:
    return lockwatch.advisory_waiters(env.engine)


def _held_by_others(env: Env, pid: int, klass: int, mode: str) -> int:
    return lockwatch.advisory_held(env.engine, exclude_pid=pid, classid=klass, mode=mode)


def _until(cond: Callable[[], bool], what: str, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            pytest.fail(f"timed out waiting for {what}")
        time.sleep(0.02)


@pytest.mark.parametrize("op", ["set", "update", "delete"])
def test_lock_order_settle_shared_then_account(env: Env, op: str) -> None:
    rid = set_manual_record(env.engine, env.account, day(1, 1), 10, user_id=USER).record_id
    acts: dict[str, Callable[[], Any]] = {
        "set": lambda: set_manual_record(env.engine, env.account, day(2, 1), 20, user_id=USER),
        "update": lambda: update_manual_record(env.engine, rid, balance=11),
        "delete": lambda: delete_record(env.engine, rid),
    }
    done: list[Any] = []

    # someone holds the ACCOUNT lock: the writer already holds settle shared and waits here
    with env.engine.connect() as holder, holder.begin():
        pid = int(holder.execute(text("SELECT pg_backend_pid()")).scalar_one())
        lock_accounts(holder, [env.account])
        thread = threading.Thread(target=lambda: done.append(acts[op]()))
        thread.start()
        _until(lambda: _waiters(env) >= 1, "the write to wait for the account lock")
        assert _held_by_others(env, pid, _SETTLE_CLASS, "ShareLock") == 1
    thread.join(timeout=15)
    assert not thread.is_alive() and len(done) == 1

    # someone holds settle EXCLUSIVE: the writer waits for it before taking the account lock
    done.clear()
    if op == "delete":
        rid = set_manual_record(env.engine, env.account, day(1, 1), 10, user_id=USER).record_id
        acts["delete"] = lambda: delete_record(env.engine, rid)
    with env.engine.connect() as holder, holder.begin():
        pid = int(holder.execute(text("SELECT pg_backend_pid()")).scalar_one())
        lock_settle_exclusive(holder)
        thread = threading.Thread(target=lambda: done.append(acts[op]()))
        thread.start()
        _until(lambda: _waiters(env) >= 1, "the write to wait for the settle lock")
        assert _held_by_others(env, pid, _ACCOUNT_CLASS, "ExclusiveLock") == 0
    thread.join(timeout=15)
    assert not thread.is_alive() and len(done) == 1
