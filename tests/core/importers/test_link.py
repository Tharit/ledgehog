"""Linking an account to an instance, with the preview (spec §5.4: link before importing)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core import accounts
from app.core.accounts import AccountMissing, close_account
from app.core.importers import instances
from app.core.importers.instances import (
    AccountClosed,
    AlreadyLinked,
    ExternalRefTaken,
    InstanceDisabled,
    InstanceMissing,
    InvalidInstance,
    LinkMissing,
    NotAnAccountSource,
    link_account,
    unlink_account,
    update_instance,
)
from app.core.settle.settle import SettleResult
from app.utils.db.locks import lock_accounts, lock_settle_exclusive
from tests.core.importers.conftest import Db, make_acct, make_instance
from tests.invariants.helpers import make_entry, make_run, make_source, pair

D1, D2, D3 = date(2026, 1, 5), date(2026, 2, 9), date(2026, 3, 1)


def _user_row(db: Db, account: int, booked_on: date) -> int:
    with db.engine.begin() as c:
        return make_entry(c, make_source(c, account, importer=None, booked_on=booked_on))


def _links(db: Db) -> list[Any]:
    return db.q("SELECT account_id, importer_instance_id, external_ref FROM account_source")


# ---- the preview ----------------------------------------------------------------------------


def test_preview_of_an_account_holding_nothing(db: Db) -> None:
    iid, acct = make_instance(db), make_acct(db)
    r = link_account(db.engine, iid, acct, "r1", dry_run=True)
    assert r.user_authored_count == 0 and r.first_booked_on is None and r.last_booked_on is None
    assert r.account_becomes_synced is True and r.dry_run is True
    assert not any("not deduplicated" in w for w in r.warnings)
    assert any("synced" in n and "refused" in n for n in r.changes)


def test_preview_lists_user_authored_rows_and_counter_legs(db: Db) -> None:
    iid = make_instance(db)
    acct, other = make_acct(db, "Cash", kind="cash"), make_acct(db, "Other")
    _user_row(db, acct, D2)
    _user_row(db, acct, D1)
    with db.engine.begin() as c:  # a counter-leg a commit created, on `acct`
        run = make_run(c, other)
        a_src = make_source(c, other, run_id=run, amount=-500, booked_on=D3)
        a = make_entry(c, a_src, type="transfer", counter_account_id=acct)
        b_src = make_source(c, acct, importer=None, amount=500, booked_on=D3)
        b = make_entry(c, b_src, type="transfer", counter_account_id=other)
        pair(c, a, b)
        make_entry(c, make_source(c, acct, booked_on=D1))  # imported (own run): not counted
    r = link_account(db.engine, iid, acct, "r1", dry_run=True)
    assert (r.user_authored_count, r.first_booked_on, r.last_booked_on) == (3, D1, D3)
    assert any("not deduplicated" in w for w in r.warnings)


# ---- dry run --------------------------------------------------------------------------------


def test_dry_run_writes_nothing_does_not_settle_and_has_the_real_shape(db: Db, settle_spy: Any) -> None:
    iid, acct = make_instance(db), make_acct(db)
    _user_row(db, acct, D1)
    calls = settle_spy(instances)
    preview = link_account(db.engine, iid, acct, "r1", dry_run=True)
    assert _links(db) == [] and calls == []
    real = link_account(db.engine, iid, acct, "r1")
    assert calls == [1]
    assert type(preview) is type(real)
    from dataclasses import replace

    assert replace(real, dry_run=True, settle=None) == replace(preview, settle=None)
    assert preview.settle is None


def test_dry_run_reports_the_refusals_the_real_run_would(db: Db) -> None:
    iid, acct = make_instance(db), make_acct(db)
    link_account(db.engine, iid, acct, "r1")
    with pytest.raises(AlreadyLinked):
        link_account(db.engine, iid, acct, "r2", dry_run=True)


# ---- the real link --------------------------------------------------------------------------


def test_link_inserts_the_row_and_makes_the_account_synced(db: Db) -> None:
    iid, acct = make_instance(db), make_acct(db)
    r = link_account(db.engine, iid, acct, "DE00 1234")
    assert _links(db) == [(acct, iid, "DE00 1234")]  # the source's own id, stored as given
    assert db.one("SELECT synced FROM v_account_synced WHERE account_id = :a", a=acct)[0] is True
    assert r.dry_run is False and r.account_becomes_synced is True and r.settle is not None
    db.assert_checks_clean()


def test_second_link_of_an_already_synced_account_changes_nothing_about_sync(db: Db) -> None:
    a, b, acct = make_instance(db, label="a"), make_instance(db, label="b"), make_acct(db)
    link_account(db.engine, a, acct, "x")
    r = link_account(db.engine, b, acct, "y", dry_run=True)
    assert r.account_becomes_synced is False


def test_link_settles_once_after_commit_and_an_error_does_not_undo_it(
    db: Db, monkeypatch: pytest.MonkeyPatch
) -> None:
    iid, acct = make_instance(db), make_acct(db)
    seen: list[Any] = []

    def spy(engine: Any) -> SettleResult:
        seen.append(_links(db))  # a separate connection: committed state only
        return SettleResult(error="RuntimeError: settle down")

    monkeypatch.setattr(instances, "settle", spy)
    r = link_account(db.engine, iid, acct, "r1")
    assert seen == [[(acct, iid, "r1")]]
    assert r.settle is not None and r.settle.error is not None and "settle down" in r.settle.error
    assert _links(db) == [(acct, iid, "r1")]


@pytest.mark.parametrize("dry_run", [False, True])
def test_link_refusals(db: Db, dry_run: bool, settle_spy: Any) -> None:
    calls = settle_spy(instances)
    iid, acct = make_instance(db), make_acct(db)
    docs = make_instance(db, label="rates", emits=["rates"])
    off = make_instance(db, label="off")
    update_instance(db.engine, off, disabled=True)
    closed = make_acct(db, "Closed")
    close_account(db.engine, closed, date(2026, 1, 1))
    calls.clear()

    def go(i: int, a: int, ref: str = "r") -> Any:
        return link_account(db.engine, i, a, ref, dry_run=dry_run)

    with pytest.raises(InstanceMissing):
        go(999, acct)
    with pytest.raises(AccountMissing):
        go(iid, 999)
    with pytest.raises(AccountClosed):
        go(iid, closed)
    with pytest.raises(InstanceDisabled):
        go(off, acct)
    with pytest.raises(NotAnAccountSource):
        go(docs, acct)
    with pytest.raises(InvalidInstance):
        go(iid, acct, " ")
    assert _links(db) == [] and calls == []


def test_link_refuses_a_duplicate_external_ref_per_instance_and_a_second_link(
    db: Db, settle_spy: Any
) -> None:
    iid, other = make_instance(db), make_instance(db, label="2")
    a, b = make_acct(db, "A"), make_acct(db, "B")
    link_account(db.engine, iid, a, "r1")
    calls = settle_spy(instances)
    with pytest.raises(ExternalRefTaken):
        link_account(db.engine, iid, b, "r1")
    with pytest.raises(AlreadyLinked):
        link_account(db.engine, iid, a, "r9")
    link_account(db.engine, other, b, "r1")  # the same ref under another instance is fine
    assert len(_links(db)) == 2 and calls == [1]


def test_a_linked_account_refuses_new_user_rows_but_keeps_the_old_ones(db: Db) -> None:
    iid, acct = make_instance(db), make_acct(db)
    _user_row(db, acct, D1)
    link_account(db.engine, iid, acct, "r1")
    assert db.one("SELECT count(*) FROM source_transaction WHERE account_id = :a", a=acct)[0] == 1
    with pytest.raises(DBAPIError, match="is synced"):
        _user_row(db, acct, D2)
    assert db.one("SELECT count(*) FROM source_transaction WHERE account_id = :a", a=acct)[0] == 1
    unlink_account(db.engine, iid, acct)
    _user_row(db, acct, D2)  # unsynced again
    db.assert_checks_clean()


# ---- unlink ---------------------------------------------------------------------------------


def test_unlink_keeps_past_coverage_and_settles(db: Db, settle_spy: Any) -> None:
    iid, acct = make_instance(db), make_acct(db)
    link_account(db.engine, iid, acct, "r1")
    with db.engine.begin() as c:
        make_run(c, acct, instance_id=iid, covered_through=D2)
    calls = settle_spy(instances)
    unlink_account(db.engine, iid, acct)
    assert _links(db) == [] and calls == [1]
    assert db.one("SELECT synced FROM v_account_synced WHERE account_id = :a", a=acct)[0] is False
    assert db.one("SELECT synced_through FROM v_account_coverage WHERE account_id = :a", a=acct)[0] == D2
    db.assert_checks_clean()


def test_unlink_of_a_missing_link(db: Db, settle_spy: Any) -> None:
    calls = settle_spy(instances)
    iid, acct = make_instance(db), make_acct(db)
    with pytest.raises(LinkMissing):
        unlink_account(db.engine, iid, acct)
    assert calls == []


# ---- lock order -----------------------------------------------------------------------------

_SETTLE_CLASS = 1 << 24
_ACCOUNT_CLASS = 2 << 24
# pg_locks spans the cluster: other databases' locks (concurrent test runs) must not count
_HERE = "database = (SELECT oid FROM pg_database WHERE datname = current_database())"


def _waiters(db: Db) -> int:
    return int(
        db.one(f"SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted AND {_HERE}")[0]
    )


def _held_by_others(db: Db, pid: int, klass: int, mode: str) -> int:
    return int(
        db.one(
            f"SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND granted AND pid <> :p AND {_HERE}"
            " AND classid = :c AND mode = :m",
            p=pid,
            c=klass,
            m=mode,
        )[0]
    )


def _until(cond: Callable[[], bool], what: str, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            pytest.fail(f"timed out waiting for {what}")
        time.sleep(0.02)


def _hold_and_run(
    db: Db, take: Callable[[Any], None], act: Callable[[], Any], check: Callable[[int], None]
) -> None:
    done: list[Any] = []
    with db.engine.connect() as holder:
        with holder.begin():
            pid = int(holder.execute(text("SELECT pg_backend_pid()")).scalar_one())
            take(holder)
            thread = threading.Thread(target=lambda: done.append(act()))
            thread.start()
            _until(lambda: _waiters(db) >= 1, "the write to wait")
            check(pid)
    thread.join(timeout=15)
    assert not thread.is_alive() and len(done) == 1


@pytest.mark.parametrize("op", ["link", "unlink"])
def test_lock_order_settle_shared_then_account(db: Db, op: str) -> None:
    iid, acct = make_instance(db), make_acct(db)
    if op == "unlink":
        link_account(db.engine, iid, acct, "r1")
    act: dict[str, Callable[[], Any]] = {
        "link": lambda: link_account(db.engine, iid, acct, "r1"),
        "unlink": lambda: unlink_account(db.engine, iid, acct),
    }

    def reset() -> None:
        if op == "link":
            unlink_account(db.engine, iid, acct)
        else:
            link_account(db.engine, iid, acct, "r1")

    def shared_held(pid: int) -> None:
        assert _held_by_others(db, pid, _SETTLE_CLASS, "ShareLock") == 1

    def no_account_lock(pid: int) -> None:
        assert _held_by_others(db, pid, _ACCOUNT_CLASS, "ExclusiveLock") == 0

    _hold_and_run(db, lambda h: lock_accounts(h, [acct]), act[op], shared_held)
    reset()
    _hold_and_run(db, lock_settle_exclusive, act[op], no_account_lock)


def test_a_dry_run_also_waits_for_the_locks(db: Db) -> None:
    iid, acct = make_instance(db), make_acct(db)
    _hold_and_run(
        db,
        lambda h: lock_accounts(h, [acct]),
        lambda: link_account(db.engine, iid, acct, "r1", dry_run=True),
        lambda pid: None,
    )
    assert _links(db) == []


def test_accounts_module_is_untouched_by_instances_settle(db: Db, settle_spy: Any) -> None:
    """The account module's settle and the instance module's are separate seams."""
    iid, acct = make_instance(db), make_acct(db)
    acct_calls = settle_spy(accounts)
    inst_calls = settle_spy(instances)
    link_account(db.engine, iid, acct, "r1")
    assert acct_calls == [] and inst_calls == [1]
