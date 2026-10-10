"""Reverting a run (spec §5.6, I30; architecture §5.2, §4.1)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import Engine, text

from app.core.balance.derived import recompute_derived
from app.core.ingest.revert import (
    DerivedChange,
    DerivedEntry,
    NotLatestRun,
    NotRevertible,
    RunMissing,
    revert_run,
)
from tests.core.ingest.revert_helpers import BASE, World, add_duplicate, day, transfer_to_savings
from tests.invariants.helpers import make_balance_record, make_movement


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


# ---- what a revert removes -----------------------------------------------------------------


def test_revert_deletes_the_runs_rows_and_entries_and_nothing_else(world: World) -> None:
    r1 = world.run([(-100, day(10))])
    r2 = world.run([(-200, day(11)), (-300, day(12))])
    own_src, own = world.tx(lambda c: make_movement(c, world.checking, importer=None, amount=-50))
    result = revert_run(world.engine, r2.id, user_id=None)
    assert result.removed_entry_ids == tuple(r2.entries) and result.partner_entry_ids == ()
    assert world.q("SELECT id FROM source_transaction WHERE import_run_id = :r", r=r2.id) == []
    assert world.q("SELECT id FROM ledger_entry WHERE id = ANY(:ids)", ids=r2.entries) == []
    # the older run and the user-authored transaction are untouched
    assert [
        r.id for r in world.q("SELECT id FROM source_transaction WHERE import_run_id = :r", r=r1.id)
    ] == r1.sources
    assert [
        r.id for r in world.q("SELECT id FROM ledger_entry WHERE id = ANY(:i)", i=[*r1.entries, own])
    ] == [
        *r1.entries,
        own,
    ]
    assert world.q("SELECT id FROM source_transaction WHERE id = :i", i=own_src)
    # the run is kept, marked reverted, by whom and when
    run = world.one("SELECT status, reverted_at, reverted_by FROM import_run WHERE id = :i", i=r2.id)
    assert run.status == "reverted" and run.reverted_at is not None and run.reverted_by is None
    world.assert_checks_clean()


def test_the_revert_records_who_reverted(world: World) -> None:
    user = world.tx(
        lambda c: c.execute(
            text(
                "INSERT INTO app_user (login, pw_hash, display_name) VALUES ('anna', 'x', 'Anna') RETURNING id"
            )
        ).scalar_one()
    )
    run = world.run([(-100, day(10))])
    revert_run(world.engine, run.id, user_id=int(user))
    assert world.one("SELECT reverted_by FROM import_run WHERE id = :i", i=run.id).reverted_by == user


def test_runs_revert_as_a_stack_newest_first(world: World) -> None:
    r1 = world.run([(-100, day(10))])
    r2 = world.run([(-200, day(11))])
    with pytest.raises(NotLatestRun):
        revert_run(world.engine, r1.id, user_id=None)
    revert_run(world.engine, r2.id, user_id=None)
    revert_run(world.engine, r1.id, user_id=None)
    assert world.status(r1.id) == world.status(r2.id) == "reverted"
    assert world.count("ledger_entry") == 0 and world.count("source_transaction") == 0
    with pytest.raises(NotRevertible, match="reverted"):
        revert_run(world.engine, r1.id, user_id=None)
    world.assert_checks_clean()


def test_a_run_without_rows_reverts(world: World) -> None:
    run = world.run([], balance=(day(12), 5000))
    assert world.derived() == [("opening", day(11), 5000)]  # the day before the record
    result = revert_run(world.engine, run.id, user_id=None)
    assert result.removed_entry_ids == ()
    assert world.derived() == [] and world.status(run.id) == "reverted"
    world.assert_checks_clean()


# ---- balance records, derived entries, coverage --------------------------------------------


def test_the_reverted_runs_record_stops_counting_and_derived_entries_follow(world: World) -> None:
    r1 = world.run([(-1000, day(10)), (-500, day(11))], balance=(day(12), 8000))
    r2 = world.run([(-300, day(13))], balance=(day(14), 7000))
    # opening = 8000 - (-1500) = 9500, the day before the first movement; reconciliation of r2 =
    # (7000 - 8000) - (-300) = -700
    assert world.derived() == [("opening", day(9), 9500), ("reconciliation", day(14), -700)]
    result = revert_run(world.engine, r2.id, user_id=None)
    assert world.derived() == [("opening", day(9), 9500)]
    assert world.one("SELECT count(*) AS n FROM v_balance_record WHERE id = :i", i=r2.record).n == 0
    assert world.one("SELECT count(*) AS n FROM balance_record WHERE id = :i", i=r2.record).n == 1  # kept
    assert result.derived_changes == (
        DerivedChange(
            world.checking,
            (DerivedEntry("opening", day(9), 9500), DerivedEntry("reconciliation", day(14), -700)),
            (DerivedEntry("opening", day(9), 9500),),
        ),
    )
    world.assert_checks_clean()


def test_the_anchor_moves_to_the_earlier_record(world: World) -> None:
    r1 = world.run([(-1000, day(10)), (-500, day(11))], balance=(day(12), 8000))
    r2 = world.run([(-200, day(3))], balance=(day(4), 9800))
    # r2's record is the earliest, so it is the anchor: opening = 9800 - (-200) = 10000 the day
    # before day 3; r1's record is then a reconciliation: (8000 - 9800) - (-1500) = -300
    assert world.derived() == [("opening", day(2), 10000), ("reconciliation", day(12), -300)]
    revert_run(world.engine, r2.id, user_id=None)
    # r1's record is the anchor again: opening = 8000 - (-1500) = 9500
    assert world.derived() == [("opening", day(9), 9500)]
    assert r1.record is not None
    world.assert_checks_clean()


def test_the_two_run_rule_a_reverted_second_run_leaves_the_state_before_it(world: World) -> None:
    # the same first run on another account is the reference for "only run 1 ever happened"
    fresh = world.tx(
        lambda c: c.execute(
            text(
                "INSERT INTO account (name, kind, currency) VALUES ('Fresh', 'checking', 'EUR') RETURNING id"
            )
        ).scalar_one()
    )
    world.run([(-1000, day(10)), (-500, day(11))], account=int(fresh), balance=(day(12), 8000))
    world.run([(-1000, day(10)), (-500, day(11))], balance=(day(12), 8000))
    r2 = world.run([(-300, day(13))], balance=(day(14), 7700))
    # run 2 explains its movement exactly: (7700 - 8000) - (-300) = 0, so there is no reconciliation
    assert world.derived() == [("opening", day(9), 9500)]
    revert_run(world.engine, r2.id, user_id=None)
    assert world.derived() == world.derived(int(fresh)) == [("opening", day(9), 9500)]
    assert world.one("SELECT count(*) AS n FROM ledger_entry WHERE account_id = :a", a=world.checking).n == 3
    world.assert_checks_clean()


def test_coverage_rolls_back_to_the_earlier_runs(world: World) -> None:
    world.run([(-100, day(10))], through=day(14))
    r2 = world.run([(-200, day(11))], through=day(20))
    cov = "SELECT synced_through FROM v_account_coverage WHERE account_id = :a"
    assert world.one(cov, a=world.checking).synced_through == day(20)
    revert_run(world.engine, r2.id, user_id=None)
    assert world.one(cov, a=world.checking).synced_through == day(14)


# ---- transfer partners, documents ----------------------------------------------------------


def _savings_with_stale_opening(world: World) -> None:
    """Savings holds a manual record and a derived opening that is wrong, so the recompute shows."""
    world.tx(lambda c: make_balance_record(c, world.savings, balance_on=day(12), balance=1000))
    world.tx(lambda c: recompute_derived(c, world.savings))
    world.tx(
        lambda c: c.execute(
            text(
                "UPDATE ledger_entry SET amount = 1 WHERE account_id = :a AND balance_record_id IS NOT NULL"
            ),
            {"a": world.savings},
        )
    )


def test_a_partner_on_another_account_is_unpaired_and_its_account_recomputed(world: World) -> None:
    run = world.run([(-500, day(10))])
    b = transfer_to_savings(world, run.sources[0], run.entries[0])
    _savings_with_stale_opening(world)
    result = revert_run(world.engine, run.id, user_id=None)
    assert result.partner_entry_ids == (b,)
    partner = world.one("SELECT * FROM ledger_entry WHERE id = :i", i=b)
    assert partner.counterpart_entry_id is None and partner.counter_account_id is None
    assert "counter_account" not in partner.derivation
    assert (partner.type, partner.description, partner.note) == (
        "transfer",
        "in",
        "keep b",
    )  # system leg stays
    # savings: opening = 1000 - (+500 dated day 10) = 500, recomputed from what remains
    assert world.derived(world.savings) == [("opening", day(9), 500)]
    assert [c.account_id for c in result.derived_changes] == [world.savings]
    world.assert_checks_clean()


def test_a_document_carried_by_a_removed_entry_is_freed(world: World) -> None:
    run = world.run([(-900, day(10))])
    doc = world.tx(
        lambda c: c.execute(
            text(
                "INSERT INTO external_document (provider, external_id, occurred_on, total, currency, raw)"
                " VALUES ('shop', 'o1', :d, -900, 'EUR', '{}') RETURNING id"
            ),
            {"d": day(10)},
        ).scalar_one()
    )
    world.tx(
        lambda c: c.execute(
            text("UPDATE ledger_entry SET document_id = :d WHERE id = :e"), {"d": doc, "e": run.entries[0]}
        )
    )
    result = revert_run(world.engine, run.id, user_id=None)
    assert result.freed_document_ids == (doc,)
    assert world.q("SELECT * FROM v_document_link WHERE document_id = :d", d=doc)[0].ledger_entry_id is None
    world.assert_checks_clean()


# ---- rows of other runs that duplicate a deleted row ---------------------------------------


def test_the_lowest_id_duplicate_becomes_the_original_and_the_rest_follow(world: World) -> None:
    r1 = world.run([(-100, day(9))])
    r2 = world.run([(-500, day(10)), (-70, day(11))])
    x, other = r2.sources
    d1 = add_duplicate(world, r1, x, amount=-500, booked_on=day(10))
    d2 = add_duplicate(world, r1, x, amount=-500, booked_on=day(10))
    d3 = add_duplicate(world, r2, x, amount=-500, booked_on=day(10))  # the run's own: goes with it
    assert d1 < d2 < d3
    result = revert_run(world.engine, r2.id, user_id=None)
    assert result.cleared_duplicate_ids == (d1,)
    assert result.repointed_source_ids == ((d2, d1),)
    dups = {r.id: r.duplicate_of for r in world.q("SELECT id, duplicate_of FROM source_transaction")}
    assert dups == {r1.sources[0]: None, d1: None, d2: d1}
    # d1 now has its one entry, as ingest would create it; d2 none
    entry = world.one(
        "SELECT amount, account_id, booked_on FROM ledger_entry WHERE source_transaction_id = :s", s=d1
    )
    assert (entry.amount, entry.account_id, entry.booked_on) == (-500, world.checking, day(10))
    assert world.q("SELECT 1 FROM ledger_entry WHERE source_transaction_id = :s", s=d2) == []
    assert other not in dups
    world.assert_checks_clean()


def test_each_deleted_row_with_duplicates_gets_its_own_original(world: World) -> None:
    r1 = world.run([])
    r2 = world.run([(-500, day(10)), (-70, day(11))])
    x, y = r2.sources
    a1 = add_duplicate(world, r1, x, amount=-500, booked_on=day(10))
    b1 = add_duplicate(world, r1, y, amount=-70, booked_on=day(11))
    b2 = add_duplicate(world, r1, y, amount=-70, booked_on=day(11))
    result = revert_run(world.engine, r2.id, user_id=None)
    assert result.cleared_duplicate_ids == (a1, b1) and result.repointed_source_ids == ((b2, b1),)
    world.assert_checks_clean()
