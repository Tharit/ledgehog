"""The change register and noting at the locks (architecture §4.2, §5.2): values move when the transaction
that noted them commits, never on a rollback or a dry run."""

from __future__ import annotations

import importlib
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine

from app.core.ledger.dimensions import previewable
from app.core.tasks.changes import ChangeRegister
from app.utils.db import locks
from app.utils.db.changes import install_change_hooks, note_change

settle_module = importlib.import_module("app.core.settle.settle")  # the package re-exports the function


@pytest.fixture
def seen(isolated_engine: Engine) -> Iterator[list[frozenset[str]]]:
    reported: list[frozenset[str]] = []
    install_change_hooks(isolated_engine, reported.append)
    yield reported


# ---- the lock helpers note, the commit reports ------------------------------------------------------


def test_the_shared_settle_lock_moves_the_ledger_only(isolated_engine: Engine, seen: list) -> None:
    with isolated_engine.begin() as conn:
        locks.lock_settle_shared(conn)
    assert seen == [frozenset({"ledger"})]


def test_account_locks_move_those_accounts_only(isolated_engine: Engine, seen: list) -> None:
    with isolated_engine.begin() as conn:
        locks.lock_accounts(conn, [7, 3])
    assert seen == [frozenset({"account:3", "account:7"})]


def test_a_document_lock_moves_the_documents_only(isolated_engine: Engine, seen: list) -> None:
    with isolated_engine.begin() as conn:
        locks.lock_rows(conn, "external_document", [1])
    assert seen == [frozenset({"documents"})]


def test_another_table_lock_moves_nothing(isolated_engine: Engine, seen: list) -> None:
    with isolated_engine.begin() as conn:
        locks.lock_rows(conn, "ledger_entry", [1])
    assert seen == []


def test_a_write_moves_the_keys_of_all_its_locks_once(isolated_engine: Engine, seen: list) -> None:
    with isolated_engine.begin() as conn:
        locks.lock_settle_shared(conn)
        locks.lock_accounts(conn, [2])
        locks.lock_rows(conn, "external_document", [1])
    assert seen == [frozenset({"ledger", "account:2", "documents"})]


def test_a_rollback_moves_nothing(isolated_engine: Engine, seen: list) -> None:
    with isolated_engine.connect() as conn:
        locks.lock_settle_shared(conn)
        locks.lock_accounts(conn, [2])
        conn.rollback()
    with isolated_engine.connect() as conn:  # a write that fails
        with pytest.raises(RuntimeError):
            with conn.begin():
                locks.lock_settle_shared(conn)
                raise RuntimeError("the write failed")
    with isolated_engine.connect() as conn:  # closed without a commit
        locks.lock_settle_shared(conn)
    assert seen == []


def test_a_rollback_after_a_commit_reports_only_the_commit(isolated_engine: Engine, seen: list) -> None:
    with isolated_engine.connect() as conn:
        locks.lock_settle_shared(conn)
        conn.commit()
        locks.lock_accounts(conn, [4])
        conn.rollback()
    assert seen == [frozenset({"ledger"})]


def test_a_dry_run_moves_nothing_and_a_real_run_moves_the_ledger(isolated_engine: Engine, seen: list) -> None:
    previewable(isolated_engine, True, lambda conn: None)
    assert seen == []
    previewable(isolated_engine, False, lambda conn: None)
    assert seen == [frozenset({"ledger"})]


def test_notes_do_not_leak_to_the_next_user_of_a_pooled_connection(
    isolated_engine: Engine, seen: list
) -> None:
    with isolated_engine.connect() as conn:
        note_change(conn, "ledger")  # noted, never committed
    with isolated_engine.begin() as conn:
        locks.lock_accounts(conn, [9])
    assert seen == [frozenset({"account:9"})]


# ---- settling ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("touched", "moved"),
    [
        (set(), []),
        ({5}, [frozenset({"ledger"})]),
    ],
)
def test_settling_moves_the_ledger_for_a_touched_entry(
    isolated_engine: Engine,
    seen: list,
    monkeypatch: pytest.MonkeyPatch,
    touched: set[int],
    moved: list,
) -> None:
    monkeypatch.setattr(settle_module, "_run_rounds", lambda conn: touched)
    result = settle_module.settle(isolated_engine)
    assert result.error is None and seen == moved  # the exclusive lock itself notes nothing


def test_a_failed_settle_moves_nothing(
    isolated_engine: Engine, seen: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(conn: object) -> tuple[set[int], bool]:
        note_change(conn, "ledger")  # type: ignore[arg-type]
        raise RuntimeError("step failed")

    monkeypatch.setattr(settle_module, "_run_rounds", boom)
    assert settle_module.settle(isolated_engine).error is not None
    assert seen == []


# ---- the register -----------------------------------------------------------------------------------


def test_every_bump_gives_a_new_value_and_an_untouched_key_keeps_the_start_value() -> None:
    register = ChangeRegister()
    start = register.start_value
    assert register.value("ledger") == start and register.accounts([1, 2]) == {1: start, 2: start}
    register.bump(["ledger"])
    first = register.value("ledger")
    register.bump(["ledger", "account:1"])
    assert register.value("ledger") != first != start
    assert register.accounts([1, 2]) == {1: register.value("ledger"), 2: start}
    assert register.value("documents") == start


def test_a_restart_gives_values_unlike_any_earlier_one() -> None:
    old, new = ChangeRegister(), ChangeRegister()
    seen_before = {old.start_value}
    for _ in range(3):
        old.bump(["ledger"])
        seen_before.add(old.value("ledger"))
    new.bump(["ledger"])
    assert {new.start_value, new.value("ledger")}.isdisjoint(seen_before)
