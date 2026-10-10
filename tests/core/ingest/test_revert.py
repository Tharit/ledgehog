"""Reverting a run (spec §5.6, I30; architecture §5.2, §4.1)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import Engine, text

from app.core.ingest.revert import NotLatestRun, NotRevertible, RunMissing, revert_run
from tests.core.ingest.revert_helpers import BASE, World, day


@pytest.fixture
def world(isolated_engine: Engine, make_account: Callable[..., int]) -> World:
    with isolated_engine.begin() as conn:
        checking = make_account(conn, name="Checking")
        savings = make_account(conn, name="Savings", kind="savings")
    return World(isolated_engine, checking, savings)


# ---- refusals ------------------------------------------------------------------------------


def test_a_missing_run_is_refused(world: World) -> None:
    with pytest.raises(RunMissing):
        revert_run(world.engine, 987654, user_id=None)


@pytest.mark.parametrize("status", ["running", "failed", "reverted"])
def test_only_an_ok_run_is_reverted(world: World, status: str) -> None:
    run = world.run([(-100, day(10))], status=status)
    before = world.state()
    with pytest.raises(NotRevertible, match=status):
        revert_run(world.engine, run.id, user_id=None)
    assert world.state() == before


@pytest.mark.parametrize("emits", ["documents", "rates"])
def test_document_and_rate_runs_are_never_reverted(world: World, emits: str) -> None:
    run_id = world.tx(
        lambda c: c.execute(
            text(
                "INSERT INTO import_run (importer, emits, status, finished_at, covered_through)"
                " VALUES ('test', :e, 'ok', now(), CURRENT_DATE) RETURNING id"
            ),
            {"e": emits},
        ).scalar_one()
    )
    with pytest.raises(NotRevertible, match=emits):
        revert_run(world.engine, int(run_id), user_id=None)


def test_an_older_run_is_refused_naming_the_newer_one(world: World) -> None:
    r1 = world.run([(-100, day(10))])
    r2 = world.run([(-200, day(11))])
    before = world.state()
    with pytest.raises(NotLatestRun) as exc:
        revert_run(world.engine, r1.id, user_id=None)
    assert exc.value.newer_run_id == r2.id and str(r2.id) in str(exc.value)
    assert world.state() == before


def test_runs_with_equal_finish_times_are_ordered_by_id(world: World) -> None:
    r1 = world.run([(-100, day(10))], finished_at=BASE)
    r2 = world.run([(-200, day(11))], finished_at=BASE)
    with pytest.raises(NotLatestRun) as exc:
        revert_run(world.engine, r1.id, user_id=None)
    assert exc.value.newer_run_id == r2.id


def test_failed_and_reverted_runs_do_not_count_as_newer(world: World) -> None:
    r1 = world.run([(-100, day(10))])
    world.run([(-200, day(11))], status="failed")
    world.run([(-300, day(12))], status="reverted")
    result = revert_run(world.engine, r1.id, user_id=None)
    assert result.removed_entry_ids == tuple(r1.entries)
