"""Account operations (spec §3.3, architecture §4.1): create, update, delete, close, reopen, list."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from sqlalchemy import text

from app.core import accounts
from app.core.accounts import (
    AccountMissing,
    AccountNotEmpty,
    DuplicateExternalRef,
    UnknownCurrency,
    close_account,
    create_account,
    delete_account,
    list_accounts,
    reopen_account,
    update_account,
)
from app.core.settle.settle import SettleResult
from app.utils.db.locks import lock_accounts, lock_settle_exclusive
from tests import lockwatch
from tests.core.accounts.conftest import Db
from tests.invariants.helpers import make_entry, make_run, make_source

# ---- create ---------------------------------------------------------------------------------


def test_create_makes_one_account_and_nothing_else(db: Db) -> None:
    aid = create_account(db.engine, name="Giro", kind="checking", currency="EUR", sort_order=3, note="n")
    row = db.one("SELECT * FROM account WHERE id = :i", i=aid)
    assert (row.name, row.kind, row.currency, row.sort_order, row.note) == ("Giro", "checking", "EUR", 3, "n")
    assert row.external_ref is None and row.closed_on is None
    for table in ("ledger_entry", "source_transaction", "import_run", "balance_record", "account_source"):
        assert db.one(f"SELECT count(*) FROM {table}")[0] == 0  # noqa: S608
    db.assert_checks_clean()


def test_create_canonicalises_the_external_ref(db: Db) -> None:
    aid = create_account(db.engine, name="Giro", kind="checking", currency="EUR", external_ref="DE00 1234")
    assert db.one("SELECT external_ref FROM account WHERE id = :i", i=aid)[0] == "de001234"


def test_create_refuses_a_duplicate_external_ref_after_canonicalisation(db: Db) -> None:
    create_account(db.engine, name="A", kind="checking", currency="EUR", external_ref="DE00 1234")
    with pytest.raises(DuplicateExternalRef):
        create_account(db.engine, name="B", kind="savings", currency="EUR", external_ref="de001234")
    assert db.one("SELECT count(*) FROM account")[0] == 1


def test_create_refuses_an_unknown_currency(db: Db) -> None:
    with pytest.raises(UnknownCurrency):
        create_account(db.engine, name="A", kind="checking", currency="XXQ")
    assert db.one("SELECT count(*) FROM account")[0] == 0


def test_a_blank_external_ref_is_none(db: Db) -> None:
    a = create_account(db.engine, name="A", kind="checking", currency="EUR", external_ref=" - ")
    b = create_account(db.engine, name="B", kind="checking", currency="EUR", external_ref="")
    assert db.q("SELECT external_ref FROM account WHERE id IN (:a, :b)", a=a, b=b) == [(None,), (None,)]


def test_create_settles_only_when_it_sets_an_external_ref(db: Db, settle_spy: Any) -> None:
    calls = settle_spy(accounts)
    create_account(db.engine, name="A", kind="checking", currency="EUR")
    assert calls == []
    create_account(db.engine, name="B", kind="checking", currency="EUR", external_ref="X1")
    assert calls == [1]


# ---- update ---------------------------------------------------------------------------------


def _acct(db: Db, **kw: Any) -> int:
    kw.setdefault("name", "Giro")
    kw.setdefault("kind", "checking")
    kw.setdefault("currency", "EUR")
    return create_account(db.engine, **kw)


def test_update_changes_only_what_is_given(db: Db, settle_spy: Any) -> None:
    calls = settle_spy(accounts)
    aid = _acct(db, note="keep")
    update_account(db.engine, aid, name="Girokonto", sort_order=7)
    row = db.one("SELECT * FROM account WHERE id = :i", i=aid)
    assert (row.name, row.sort_order, row.note, row.kind) == ("Girokonto", 7, "keep", "checking")
    assert calls == []  # nothing pass 0 reads changed


def test_update_external_ref_canonicalises_clears_and_settles(db: Db, settle_spy: Any) -> None:
    calls = settle_spy(accounts)
    aid = _acct(db)
    update_account(db.engine, aid, external_ref="DE 99")
    assert db.one("SELECT external_ref FROM account WHERE id = :i", i=aid)[0] == "de99"
    update_account(db.engine, aid, external_ref=None)
    assert db.one("SELECT external_ref FROM account WHERE id = :i", i=aid)[0] is None
    assert calls == [1, 1]


def test_update_external_ref_collision_is_refused(db: Db) -> None:
    _acct(db, name="A", external_ref="DE00 1234")
    b = _acct(db, name="B")
    with pytest.raises(DuplicateExternalRef):
        update_account(db.engine, b, external_ref="de001234")
    assert db.one("SELECT external_ref FROM account WHERE id = :i", i=b)[0] is None


def test_update_returns_the_settle_result(db: Db, monkeypatch: pytest.MonkeyPatch) -> None:
    aid = _acct(db)
    result = SettleResult(touched_entry_ids=(4,))
    monkeypatch.setattr(accounts, "settle", lambda e: result)
    assert update_account(db.engine, aid, external_ref="Q") is result


def test_currency_cannot_change(db: Db) -> None:
    aid = _acct(db)
    with pytest.raises(TypeError):
        update_account(db.engine, aid, currency="USD")  # type: ignore[call-arg]
    with pytest.raises(Exception, match="currency is fixed"):  # the trigger, for any other writer
        db.run("UPDATE account SET currency = 'USD' WHERE id = :i", i=aid)


def test_kind_cannot_change(db: Db) -> None:
    aid = _acct(db, kind="checking")
    with pytest.raises(TypeError):
        update_account(db.engine, aid, kind="savings")  # type: ignore[call-arg]


def test_update_missing_account(db: Db) -> None:
    with pytest.raises(AccountMissing):
        update_account(db.engine, 999, name="x")


# ---- delete ---------------------------------------------------------------------------------


def test_delete_an_empty_account(db: Db, settle_spy: Any) -> None:
    calls = settle_spy(accounts)
    aid = _acct(db)
    delete_account(db.engine, aid)
    assert db.one("SELECT count(*) FROM account")[0] == 0
    assert calls == [1]
    db.assert_checks_clean()


def test_delete_missing_account(db: Db) -> None:
    with pytest.raises(AccountMissing):
        delete_account(db.engine, 999)


def _with_entry(db: Db, aid: int) -> None:
    with db.engine.begin() as c:
        make_entry(c, make_source(c, aid, importer=None))


def _with_run(db: Db, aid: int) -> None:
    with db.engine.begin() as c:
        make_run(c, aid)


def _with_record(db: Db, aid: int) -> None:
    db.run(
        "INSERT INTO balance_record (account_id, balance, currency, balance_on)"
        " VALUES (:a, 100, 'EUR', '2026-03-01')",
        a=aid,
    )


def _with_link(db: Db, aid: int) -> None:
    db.run("INSERT INTO importer_instance (importer, label, access) VALUES ('csv', 'x', 'shared')")
    db.run(
        "INSERT INTO account_source (account_id, importer_instance_id, external_ref)"
        " SELECT :a, id, 'r' FROM importer_instance",
        a=aid,
    )


@pytest.mark.parametrize(
    "dependent", [_with_entry, _with_run, _with_record, _with_link], ids=["entry", "run", "record", "link"]
)
def test_delete_is_refused_while_the_account_holds_anything(
    db: Db, dependent: Callable[[Db, int], None], settle_spy: Any
) -> None:
    calls = settle_spy(accounts)
    aid = _acct(db)
    dependent(db, aid)
    with pytest.raises(AccountNotEmpty, match="clos"):
        delete_account(db.engine, aid)
    assert db.one("SELECT count(*) FROM account WHERE id = :i", i=aid)[0] == 1
    assert calls == []


def test_delete_refused_names_a_duplicate_only_source_row(db: Db) -> None:
    """A duplicate source row has no entry; it is still a source row the account holds."""
    aid = _acct(db)
    with db.engine.begin() as c:
        run = make_run(c, aid)
        original = make_source(c, aid, run_id=run)
        make_entry(c, original)
        dup = make_source(c, aid, run_id=run)
        c.execute(
            text("UPDATE source_transaction SET duplicate_of = :o WHERE id = :d"), {"o": original, "d": dup}
        )
    with pytest.raises(AccountNotEmpty):
        delete_account(db.engine, aid)


# ---- close / reopen -------------------------------------------------------------------------


def _linked(db: Db, aid: int) -> None:
    _with_link(db, aid)


def test_close_makes_it_unsynced_at_once_and_reopen_restores(db: Db, settle_spy: Any) -> None:
    calls = settle_spy(accounts)
    aid = _acct(db)
    _linked(db, aid)
    synced = "SELECT synced FROM v_account_synced WHERE account_id = :i"
    assert db.one(synced, i=aid)[0] is True
    close_account(db.engine, aid, date(2026, 3, 1))
    assert db.one("SELECT closed_on FROM account WHERE id = :i", i=aid)[0] == date(2026, 3, 1)
    assert db.one(synced, i=aid)[0] is False
    assert db.one("SELECT count(*) FROM account_source")[0] == 1  # links stay
    assert calls == [1]
    reopen_account(db.engine, aid)
    assert db.one("SELECT closed_on FROM account WHERE id = :i", i=aid)[0] is None
    assert db.one(synced, i=aid)[0] is True
    assert calls == [1, 1]
    db.assert_checks_clean()


def test_close_and_reopen_missing_account(db: Db) -> None:
    with pytest.raises(AccountMissing):
        close_account(db.engine, 999, date(2026, 3, 1))
    with pytest.raises(AccountMissing):
        reopen_account(db.engine, 999)


def test_a_settle_error_does_not_undo_a_close(db: Db, monkeypatch: pytest.MonkeyPatch) -> None:
    aid = _acct(db)
    monkeypatch.setattr(accounts, "settle", lambda e: SettleResult(error="RuntimeError: down"))
    result = close_account(db.engine, aid, date(2026, 3, 1))
    assert result.error is not None
    assert db.one("SELECT closed_on FROM account WHERE id = :i", i=aid)[0] == date(2026, 3, 1)


# ---- list -----------------------------------------------------------------------------------


def test_list_accounts_reports_the_facts(db: Db) -> None:
    open_ = _acct(db, name="Giro", external_ref="DE1", sort_order=1)
    closed = _acct(db, name="Old", sort_order=0)
    close_account(db.engine, closed, date(2026, 1, 1))
    with db.engine.begin() as c:
        run = make_run(c, open_, covered_through=date(2026, 3, 5))
        make_entry(c, make_source(c, open_, run_id=run))
    _with_link(db, open_)
    with db.engine.connect() as conn:
        views = {v.id: v for v in list_accounts(conn)}
        order = [v.id for v in list_accounts(conn)]
    assert order == [open_, closed]  # open first, closed after
    v = views[open_]
    assert (v.name, v.kind, v.currency, v.external_ref, v.closed_on) == (
        "Giro",
        "checking",
        "EUR",
        "de1",
        None,
    )
    assert v.synced is True and v.synced_through == date(2026, 3, 5) and v.last_data_on == date(2026, 3, 5)
    assert v.unexplained_difference is None
    assert v.anchored is False  # entries, but no counting balance record
    c_ = views[closed]
    assert c_.synced is False and c_.closed_on == date(2026, 1, 1) and c_.synced_through is None
    assert c_.last_data_on is None and c_.anchored is True  # nothing to anchor


def test_list_accounts_anchored_and_data_age_of_an_unsynced_account(db: Db) -> None:
    aid = _acct(db)
    with db.engine.begin() as c:
        make_entry(c, make_source(c, aid, importer=None))
    _with_record(db, aid)
    with db.engine.connect() as conn:
        (v,) = list_accounts(conn)
    assert v.anchored is True and v.synced is False and v.last_data_on == date(2026, 3, 1)


def _as_of(db: Db, aid: int) -> date | None:
    with db.engine.connect() as conn:
        (v,) = [v for v in list_accounts(conn) if v.id == aid]
    return v.balance_as_of


def _record_on(db: Db, aid: int, on: str) -> None:
    db.run(
        "INSERT INTO balance_record (account_id, balance, currency, balance_on)"
        " VALUES (:a, 100, 'EUR', :d)",
        a=aid,
        d=on,
    )


def test_balance_as_of_of_a_synced_account_is_its_synced_through(db: Db) -> None:
    aid = _acct(db)
    with db.engine.begin() as c:
        run = make_run(c, aid, covered_through=date(2026, 3, 5))
        make_entry(c, make_source(c, aid, run_id=run, booked_on=date(2026, 3, 1)))
    _with_link(db, aid)
    _record_on(db, aid, "2026-03-20")  # a later record does not move it
    assert _as_of(db, aid) == date(2026, 3, 5)


def test_balance_as_of_of_an_unsynced_account_is_the_later_of_movement_and_record(db: Db) -> None:
    movement_last = _acct(db, name="A")
    record_last = _acct(db, name="B")
    neither = _acct(db, name="C")
    with db.engine.begin() as c:
        make_entry(c, make_source(c, movement_last, importer=None, booked_on=date(2026, 3, 10)))
        make_entry(c, make_source(c, record_last, importer=None, booked_on=date(2026, 2, 1)))
    _record_on(db, movement_last, "2026-03-01")
    _record_on(db, record_last, "2026-03-01")
    assert _as_of(db, movement_last) == date(2026, 3, 10)
    assert _as_of(db, record_last) == date(2026, 3, 1)
    assert _as_of(db, neither) is None


def test_list_accounts_unexplained_difference(db: Db) -> None:
    aid = _acct(db)
    with db.engine.begin() as c:
        # two reported records one reconciliation off: the view is the source of truth here
        r1 = make_run(c, aid)
        r2 = make_run(c, aid)
        for run, on, bal in ((r1, "2026-03-01", 100), (r2, "2026-03-02", 150)):
            rec = c.execute(
                text(
                    "INSERT INTO balance_record"
                    " (account_id, import_run_id, balance, currency, balance_on)"
                    " VALUES (:a, :r, :b, 'EUR', :o) RETURNING id"
                ),
                {"a": aid, "r": run, "b": bal, "o": on},
            ).scalar_one()
            c.execute(
                text(
                    "INSERT INTO ledger_entry"
                    " (account_id, currency, booked_on, amount, type, balance_record_id)"
                    " VALUES (:a, 'EUR', :o, :amt, 'reconciliation', :rec)"
                ),
                {"a": aid, "o": on, "amt": 20 if bal == 100 else 30, "rec": rec},
            )
    with db.engine.connect() as conn:
        (v,) = list_accounts(conn)
    assert v.unexplained_difference == 50


# ---- lock order and settle ------------------------------------------------------------------

_SETTLE_CLASS = 1 << 24
_ACCOUNT_CLASS = 2 << 24


def _waiters(db: Db) -> int:
    return lockwatch.advisory_waiters(db.engine)


def _held_by_others(db: Db, pid: int, klass: int, mode: str) -> int:
    return lockwatch.advisory_held(db.engine, exclude_pid=pid, classid=klass, mode=mode)


def _until(cond: Callable[[], bool], what: str, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            pytest.fail(f"timed out waiting for {what}")
        time.sleep(0.02)


def _hold_and_run(
    db: Db, take: Callable[[Any], None], act: Callable[[], Any], then: Callable[[int], None]
) -> None:
    done: list[Any] = []
    with db.engine.connect() as holder:
        with holder.begin():
            pid = int(holder.execute(text("SELECT pg_backend_pid()")).scalar_one())
            take(holder)
            thread = threading.Thread(target=lambda: done.append(act()))
            thread.start()
            _until(lambda: _waiters(db) >= 1, "the write to wait")
            then(pid)
    thread.join(timeout=15)
    assert not thread.is_alive() and len(done) == 1


@pytest.mark.parametrize("op", ["close", "reopen", "update_ref", "delete"])
def test_lock_order_settle_shared_then_account(db: Db, op: str) -> None:
    aid = _acct(db)
    acts: dict[str, Callable[[], Any]] = {
        "close": lambda: close_account(db.engine, aid, date(2026, 3, 1)),
        "reopen": lambda: reopen_account(db.engine, aid),
        "update_ref": lambda: update_account(db.engine, aid, external_ref="Z"),
        "delete": lambda: delete_account(db.engine, aid),
    }
    # 1. the ACCOUNT lock is held: the writer already holds settle shared and waits for the account
    _hold_and_run(
        db,
        lambda h: lock_accounts(h, [aid]),
        acts[op],
        lambda pid: _assert_eq(_held_by_others(db, pid, _SETTLE_CLASS, "ShareLock"), 1),
    )
    # 2. settle EXCLUSIVE is held: the writer waits for it before taking any account lock
    if op == "delete":
        aid = _acct(db, name="again")
        acts["delete"] = lambda: delete_account(db.engine, aid)
    _hold_and_run(
        db,
        lock_settle_exclusive,
        acts[op],
        lambda pid: _assert_eq(_held_by_others(db, pid, _ACCOUNT_CLASS, "ExclusiveLock"), 0),
    )


def _assert_eq(a: Any, b: Any) -> None:
    assert a == b


def test_create_waits_for_settle_exclusive(db: Db) -> None:
    _hold_and_run(
        db,
        lock_settle_exclusive,
        lambda: create_account(db.engine, name="A", kind="checking", currency="EUR"),
        lambda pid: _assert_eq(db.one("SELECT count(*) FROM account")[0], 0),
    )
    assert db.one("SELECT count(*) FROM account")[0] == 1
