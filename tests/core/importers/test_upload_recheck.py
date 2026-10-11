"""An upload re-checks its instance, account and link INSIDE the write transaction (S8).

The pre-checks run before any lock, so a concurrent unlink, close or disable can win the race.
The shared write body repeats the refusals after the account lock (and reads the instance row
FOR SHARE, which the disable UPDATE then waits on). Real runs fail with a named error and write
nothing; a dry run, which shares the body, returns the same refusal as a `failure`."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from sqlalchemy import text

from app.core.domain.errors import RunRefused
from app.core.importers.instances import InstanceDisabled, update_instance
from app.core.importers.upload import AccountClosed, AccountNotLinked
from app.core.ingest import run as run_module
from app.utils.db.locks import lock_accounts
from tests import lockwatch
from tests.core.importers.conftest import Db
from tests.core.importers.conftest import db as db  # noqa: F401  (fixture)
from tests.core.importers.test_upload import Stub, World, irow, parsed, world

TODAY = date(2026, 8, 10)


def _stub() -> Stub:
    return Stub(parsed([irow(-100, 5)]))


def _in_thread(fn: Callable[[], Any]) -> tuple[threading.Thread, dict[str, Any]]:
    out: dict[str, Any] = {}

    def target() -> None:
        try:
            out["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - handed to the test thread
            out["error"] = exc

    thread = threading.Thread(target=target)
    thread.start()
    return thread, out


def _race(w: World, holder_sql: str, *, dry_run: bool, row_lock: bool = False) -> dict[str, Any]:
    """Start an upload; while it waits for what the holder's open transaction holds (the account
    lock, or the instance row), commit the holder's change. Returns the upload's outcome."""
    with w.db.engine.connect() as holder:
        with holder.begin():
            lock_accounts(holder, [w.account])
            holder.execute(text(holder_sql), {"i": w.instance, "a": w.account})
            thread, out = _in_thread(lambda: w.up(b"x", importer=_stub(), today=TODAY, dry_run=dry_run))
            if row_lock:
                lockwatch.wait_until_row_waiting(w.db.engine, "the upload to wait for the instance row")
            else:
                lockwatch.wait_until_waiting(w.db.engine, "the upload to wait for the account lock")
        # committed here
    thread.join(timeout=15)
    assert not thread.is_alive()
    return out


UNLINK = "DELETE FROM account_source WHERE importer_instance_id = :i AND account_id = :a"
CLOSE = "UPDATE account SET closed_on = DATE '2026-08-01' WHERE id = :a"


@pytest.mark.parametrize(
    ("sql", "error", "kind"),
    [(UNLINK, AccountNotLinked, "account_not_linked"), (CLOSE, AccountClosed, "account_closed")],
)
def test_a_real_upload_refuses_what_changed_while_it_waited_for_the_account_lock(
    db: Db, sql: str, error: type[Exception], kind: str
) -> None:
    w = world(db)
    out = _race(w, sql, dry_run=False)
    assert isinstance(out.get("error"), error), out
    assert w.counts() == {"import_run": 1, "source_transaction": 0, "ledger_entry": 0, "balance_record": 0}
    run = db.one("SELECT status, error_text FROM import_run")
    assert run.status == "failed" and run.error_text
    db.assert_checks_clean()


@pytest.mark.parametrize(("sql", "kind"), [(UNLINK, "account_not_linked"), (CLOSE, "account_closed")])
def test_a_dry_run_returns_the_same_refusal_as_a_failure(db: Db, sql: str, kind: str) -> None:
    w = world(db)
    out = _race(w, sql, dry_run=True)
    result = out["value"]
    assert result.dry_run and result.failure is not None and result.failure.kind == kind
    assert w.counts() == {"import_run": 0, "source_transaction": 0, "ledger_entry": 0, "balance_record": 0}


@pytest.mark.parametrize("dry_run", [False, True])
def test_a_disable_committed_while_the_upload_waits_for_the_instance_row_refuses_it(
    db: Db, dry_run: bool
) -> None:
    w = world(db)
    with db.engine.connect() as holder:
        with holder.begin():
            holder.execute(
                text("UPDATE importer_instance SET disabled = true WHERE id = :i"), {"i": w.instance}
            )
            thread, out = _in_thread(lambda: w.up(b"x", importer=_stub(), today=TODAY, dry_run=dry_run))
            lockwatch.wait_until_row_waiting(db.engine, "the upload to wait for the instance row")
            assert lockwatch.advisory_waiters(db.engine) == 0  # it holds the account lock: the row is next
    thread.join(timeout=15)
    assert not thread.is_alive()
    if dry_run:
        assert out["value"].failure is not None and out["value"].failure.kind == "instance_disabled"
        assert w.counts()["import_run"] == 0
    else:
        assert isinstance(out["error"], InstanceDisabled)
        assert w.counts() == {
            "import_run": 1,
            "source_transaction": 0,
            "ledger_entry": 0,
            "balance_record": 0,
        }
        assert db.one("SELECT status FROM import_run").status == "failed"


def test_a_disable_waits_for_an_upload_that_has_passed_the_recheck(
    db: Db, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = world(db)
    paused, resume = threading.Event(), threading.Event()
    real = run_module._check_contract

    def pause_after_the_recheck(*args: Any, **kw: Any) -> Any:
        paused.set()
        assert resume.wait(timeout=15)
        return real(*args, **kw)

    monkeypatch.setattr(run_module, "_check_contract", pause_after_the_recheck)
    up, up_out = _in_thread(lambda: w.up(b"x", importer=_stub(), today=TODAY))
    assert paused.wait(timeout=15)
    disable, disable_out = _in_thread(lambda: update_instance(db.engine, w.instance, disabled=True))
    lockwatch.wait_until_row_waiting(db.engine, "the disable to wait for the upload's row lock")
    assert disable.is_alive()
    assert db.one("SELECT disabled FROM importer_instance").disabled is False
    resume.set()
    up.join(timeout=15)
    disable.join(timeout=15)
    assert not up.is_alive() and not disable.is_alive()
    assert "error" not in up_out and up_out["value"].summary["inserted"] == 1
    assert "error" not in disable_out
    assert db.one("SELECT disabled FROM importer_instance").disabled is True


def test_a_delivery_without_an_instance_still_refuses_a_closed_account(db: Db) -> None:
    w = world(db)
    run_id = run_module.start_run(db.engine, w.account, "transactions", importer="manual")
    with db.engine.begin() as conn:
        conn.execute(text(CLOSE), {"a": w.account})
    with pytest.raises(RunRefused) as caught:
        run_module.ingest_delivery(
            db.engine, run_id, [irow(-100, 5)], covered_through=TODAY, covered_from=date(2026, 8, 1)
        )
    assert caught.value.reason == "account_closed"
    assert db.one("SELECT status FROM import_run").status == "failed"
    assert int(db.one("SELECT count(*) FROM source_transaction")[0]) == 0


def test_a_delivery_without_an_instance_skips_the_instance_and_link_checks(db: Db) -> None:
    w = world(db)
    run_id = run_module.start_run(db.engine, w.account, "transactions", importer="manual")
    with db.engine.begin() as conn:
        conn.execute(text(UNLINK), {"i": w.instance, "a": w.account})
    done = run_module.ingest_delivery(
        db.engine, run_id, [irow(-100, 5)], covered_through=TODAY, covered_from=date(2026, 8, 1)
    )
    assert done.inserted == 1
