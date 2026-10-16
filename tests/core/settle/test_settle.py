"""settle(engine): own transaction, exclusive lock, rounds until nothing newly confirms."""

from __future__ import annotations

import importlib
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import Connection, Engine, text

from app.core.settle import SettleResult, registered_steps, settle
from app.core.settle.settle import StepOutcome, register_step
from app.utils.db.locks import lock_settle_exclusive, lock_settle_shared
from tests import lockwatch
from tests.invariants.helpers import make_category, make_entry, make_movement, make_source

# the package re-exports the function `settle`, which shadows the module of that name
settle_module = importlib.import_module("app.core.settle.settle")

MakeAccount = Callable[..., int]
STEP_NAMES = ("resolve", "match_documents", "resolve_after_link", "pair_transfers", "review_flags")


@pytest.fixture(autouse=True)
def _restore_steps() -> Iterator[None]:
    saved = list(settle_module._STEPS)
    yield
    settle_module._STEPS[:] = saved


def _seed(engine: Engine, make_account: MakeAccount) -> dict[str, int]:
    """Committed: an unclassified entry and a clean one."""
    with engine.begin() as conn:
        acct = make_account(conn)
        _, dirty = make_movement(conn, acct)
        cat = make_category(conn, "Food")
        clean = make_entry(
            conn,
            make_source(conn, acct),
            category_id=cat,
            derivation='{"document": {"pass": "matcher_decision"}}',  # as settling leaves a confirmed unit
        )
    return {"dirty": dirty, "clean": clean}


def _row(engine: Engine, entry: int) -> tuple[list[str], int]:
    with engine.connect() as conn:
        r = conn.execute(
            text("SELECT review_flags, version FROM ledger_entry WHERE id = :i"), {"i": entry}
        ).one()
    return list(r.review_flags), r.version


def _wait_for_ungranted_advisory_lock(engine: Engine, timeout: float = 10.0) -> None:
    lockwatch.wait_until_waiting(engine, "a backend to wait on the settle lock", timeout=timeout)


def test_steps_are_declared_in_spec_order() -> None:
    assert registered_steps() == STEP_NAMES


def test_empty_database_settles_standalone(isolated_engine: Engine) -> None:
    assert settle(isolated_engine) == SettleResult()


def test_settle_writes_flags_and_reports_touched_ids(
    isolated_engine: Engine, make_account: MakeAccount
) -> None:
    ids = _seed(isolated_engine, make_account)
    result = settle(isolated_engine)
    assert result == SettleResult(touched_entry_ids=(ids["dirty"],), error=None)
    assert _row(isolated_engine, ids["dirty"])[0] == ["unclassified"]
    assert _row(isolated_engine, ids["clean"])[0] == []


def test_second_settle_touches_nothing_and_bumps_no_version(
    isolated_engine: Engine, make_account: MakeAccount
) -> None:
    ids = _seed(isolated_engine, make_account)
    settle(isolated_engine)
    before = _row(isolated_engine, ids["dirty"])
    assert settle(isolated_engine) == SettleResult()
    assert _row(isolated_engine, ids["dirty"]) == before


def test_flag_change_does_not_bump_version(isolated_engine: Engine, make_account: MakeAccount) -> None:
    ids = _seed(isolated_engine, make_account)
    version = _row(isolated_engine, ids["dirty"])[1]
    settle(isolated_engine)
    assert _row(isolated_engine, ids["dirty"])[1] == version


def test_stale_flags_are_rewritten(isolated_engine: Engine, make_account: MakeAccount) -> None:
    ids = _seed(isolated_engine, make_account)
    with isolated_engine.begin() as conn:
        conn.execute(
            text("UPDATE ledger_entry SET review_flags = ARRAY['waiting'] WHERE id = :i"),
            {"i": ids["clean"]},
        )
    assert settle(isolated_engine).touched_entry_ids == tuple(sorted(ids.values()))
    assert _row(isolated_engine, ids["clean"])[0] == []


def test_settling_guc_is_on_inside_and_gone_after(isolated_engine: Engine) -> None:
    seen: list[str | None] = []

    def spy(conn: Connection) -> StepOutcome:
        seen.append(conn.execute(text("SELECT current_setting('ledger.settling', true)")).scalar_one())
        return StepOutcome()

    register_step("resolve", spy)
    settle(isolated_engine)
    assert seen == ["on"]
    with isolated_engine.connect() as conn:
        assert conn.execute(text("SELECT current_setting('ledger.settling', true)")).scalar_one() != "on"


def test_settle_holds_the_exclusive_lock_and_no_account_lock(isolated_engine: Engine) -> None:
    held: list[tuple[str, bool]] = []

    def spy(conn: Connection) -> StepOutcome:
        held.extend((mode, ns == 1) for mode, ns in lockwatch.own_advisory_locks(conn))
        return StepOutcome()

    register_step("resolve", spy)
    settle(isolated_engine)
    assert held == [("ExclusiveLock", True)]


def test_rounds_repeat_until_nothing_new_and_hooks_run_in_order(isolated_engine: Engine) -> None:
    calls: list[tuple[int, str]] = []
    rounds = {"n": 0}

    def spy(name: str) -> Callable[[Connection], StepOutcome]:
        def step(conn: Connection) -> StepOutcome:
            if name == "resolve":
                rounds["n"] += 1
            calls.append((rounds["n"], name))
            confirmed = 1 if (name == "pair_transfers" and rounds["n"] < 3) else 0
            return StepOutcome(newly_confirmed=confirmed)

        return step

    for name in STEP_NAMES[:4]:
        register_step(name, spy(name))
    settle(isolated_engine)
    assert [n for r, n in calls if r == 1] == list(STEP_NAMES[:4])
    assert sorted({r for r, _ in calls}) == [1, 2, 3]  # rounds 1 and 2 confirmed, 3 did not


def test_hook_touched_ids_are_part_of_the_result(isolated_engine: Engine) -> None:
    register_step("pair_transfers", lambda conn: StepOutcome(touched=(9, 3)))
    assert settle(isolated_engine).touched_entry_ids == (3, 9)


def test_runaway_rounds_are_reported_not_looped(isolated_engine: Engine) -> None:
    register_step("pair_transfers", lambda conn: StepOutcome(newly_confirmed=1))
    result = settle(isolated_engine)
    assert result.error is not None and "round" in result.error


def test_failure_is_reported_and_nothing_is_partially_written(
    isolated_engine: Engine, make_account: MakeAccount
) -> None:
    ids = _seed(isolated_engine, make_account)

    def bad(conn: Connection) -> StepOutcome:
        conn.execute(text("UPDATE ledger_entry SET review_flags = ARRAY['waiting']"))
        raise RuntimeError("boom")

    register_step("pair_transfers", bad)
    result = settle(isolated_engine)
    assert result.touched_entry_ids == ()
    assert result.error is not None and "boom" in result.error
    assert _row(isolated_engine, ids["dirty"])[0] == []  # committed data intact, flags untouched
    # the lock was released with the rollback: a later settle proceeds
    register_step("pair_transfers", lambda conn: StepOutcome())
    assert settle(isolated_engine).touched_entry_ids == (ids["dirty"],)


def test_database_errors_are_reported_without_raising(isolated_engine: Engine) -> None:
    def bad(conn: Connection) -> StepOutcome:
        conn.execute(text("SELECT * FROM no_such_table"))
        return StepOutcome()

    register_step("resolve", bad)
    assert settle(isolated_engine).error is not None


def test_interrupts_are_not_swallowed(isolated_engine: Engine) -> None:
    def bad(conn: Connection) -> StepOutcome:
        raise KeyboardInterrupt

    register_step("resolve", bad)
    with pytest.raises(KeyboardInterrupt):
        settle(isolated_engine)


def test_settle_waits_for_a_writer_holding_the_shared_lock(
    isolated_engine: Engine, make_account: MakeAccount
) -> None:
    ids = _seed(isolated_engine, make_account)
    with ThreadPoolExecutor(1) as pool, isolated_engine.connect() as writer:
        lock_settle_shared(writer)
        future = pool.submit(settle, isolated_engine)
        _wait_for_ungranted_advisory_lock(isolated_engine)
        assert not future.done()
        writer.commit()
        assert future.result(timeout=10).touched_entry_ids == (ids["dirty"],)


def test_a_writer_waits_for_settle_to_finish(isolated_engine: Engine) -> None:
    inside, release = threading.Event(), threading.Event()

    def hold(conn: Connection) -> StepOutcome:
        inside.set()
        assert release.wait(10)
        return StepOutcome()

    register_step("resolve", hold)
    order: list[str] = []

    def writer() -> None:
        with isolated_engine.connect() as conn:
            lock_settle_shared(conn)
            order.append("writer")

    with ThreadPoolExecutor(2) as pool:
        settling = pool.submit(settle, isolated_engine)
        assert inside.wait(10)
        writing = pool.submit(writer)
        _wait_for_ungranted_advisory_lock(isolated_engine)
        assert order == []
        order.append("settle done")
        release.set()
        settling.result(timeout=10)
        writing.result(timeout=10)
    assert order == ["settle done", "writer"]


def test_two_concurrent_settles_serialise(isolated_engine: Engine, make_account: MakeAccount) -> None:
    ids = _seed(isolated_engine, make_account)
    with ThreadPoolExecutor(2) as pool:
        results = [f.result(timeout=20) for f in [pool.submit(settle, isolated_engine) for _ in range(2)]]
    assert sorted(r.touched_entry_ids for r in results) == [(), (ids["dirty"],)]
    assert all(r.error is None for r in results)


def test_settle_exclusive_blocks_a_second_exclusive(isolated_engine: Engine) -> None:
    with ThreadPoolExecutor(1) as pool, isolated_engine.connect() as holder:
        lock_settle_exclusive(holder)
        future = pool.submit(settle, isolated_engine)
        _wait_for_ungranted_advisory_lock(isolated_engine)
        assert not future.done()
        holder.rollback()
        assert future.result(timeout=10) == SettleResult()
