"""The preview entry point: the real write path in a transaction that is rolled back."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from sqlalchemy import text

from app.core.domain.errors import ContractViolation
from app.core.ingest import run as run_module
from app.core.ingest.run import RunResult, ingest_delivery, preview_delivery, start_run
from app.core.settle.settle import SettleResult
from app.utils.db.locks import lock_accounts, lock_settle_exclusive
from tests import lockwatch
from tests.core.ingest.conftest import THROUGH, Env, row

_TABLES = ("import_run", "source_transaction", "ledger_entry", "balance_record")


def _counts(env: Env) -> dict[str, int]:
    return {t: env.count(t) for t in _TABLES}


def _preview(env: Env, rows: list[Any], **kw: Any) -> RunResult:
    kw.setdefault("covered_through", THROUGH)
    return preview_delivery(
        env.engine, account_id=env.account, instance_id=None, importer="csv", rows=rows, **kw
    )


def _rows() -> list[Any]:
    return [row(-500, source_id="a"), row(-700, source_id="b")]


def test_preview_persists_nothing_and_does_not_settle(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(run_module, "settle", lambda engine: calls.append(1) or SettleResult())
    before = _counts(env)
    result = _preview(env, _rows(), reported_balance=-1200, reported_balance_on=date(2026, 3, 12))
    assert _counts(env) == before
    assert calls == []
    assert result.inserted == 2 and result.skipped_by_identity == 0
    assert result.settle is None
    assert result.balance_record_id is not None
    assert result.stats["balance"] == {"balance_on": "2026-03-12", "balance": -1200}


def test_preview_equals_the_real_run(env: Env) -> None:
    kw: dict[str, Any] = {
        "reported_balance": -1200,
        "reported_balance_on": date(2026, 3, 12),
        "importer_stats": {"filtered": 3},
    }
    first = _preview(env, _rows(), **kw)
    real = env.deliver(_rows(), **kw)
    assert first.stats == real.stats
    assert (first.inserted, first.skipped_by_identity, first.importer_stats) == (
        real.inserted,
        real.skipped_by_identity,
        real.importer_stats,
    )
    # and again over the now-existing rows: everything is skipped by identity, as for real
    again = _preview(env, _rows(), **kw)
    assert again.inserted == 0 and again.skipped_by_identity == 2
    assert _counts(env)["import_run"] == 1


def test_preview_and_ingest_share_one_write_body(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    original = run_module._write_delivery

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append("call")
        return original(*args, **kwargs)

    monkeypatch.setattr(run_module, "_write_delivery", spy)
    _preview(env, _rows())
    env.deliver(_rows())
    assert seen == ["call", "call"]


def test_preview_keeps_the_contract_checks(env: Env) -> None:
    before = _counts(env)
    with pytest.raises(ContractViolation) as exc:
        _preview(env, [row(-5, currency="USD")])
    assert exc.value.rule == "currency_mismatch"
    with pytest.raises(ContractViolation) as exc2:
        _preview(env, _rows(), reported_balance=1, reported_balance_on=date(2026, 4, 1))
    assert exc2.value.rule == "balance_after_coverage"
    with pytest.raises(ContractViolation) as exc3:
        _preview(env, _rows(), covered_through=None)
    assert exc3.value.rule == "no_coverage"
    assert _counts(env) == before


def test_preview_with_an_unknown_account_raises_and_writes_nothing(env: Env) -> None:
    with pytest.raises(Exception):  # noqa: B017, PT011  # the FK refuses the temporary run row
        preview_delivery(
            env.engine, account_id=999_999, instance_id=None, importer="csv", rows=[], covered_through=THROUGH
        )
    assert _counts(env)["import_run"] == 0


def test_preview_rejects_bad_importer_stats(env: Env) -> None:
    with pytest.raises(ValueError, match="filtered"):
        _preview(env, _rows(), importer_stats={"filtered": -1})
    assert _counts(env)["import_run"] == 0


def test_preview_leaves_a_committed_run_alone(env: Env) -> None:
    run_id = start_run(env.engine, env.account, "transactions", importer="csv")
    _preview(env, _rows())
    assert env.run_row(run_id).status == "running"
    ingest_delivery(env.engine, run_id, _rows(), covered_through=THROUGH)
    assert env.run_row(run_id).status == "ok"


_SETTLE_CLASS = 1 << 24
_ACCOUNT_CLASS = 2 << 24


def _until(cond: Callable[[], bool], what: str, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            pytest.fail(f"timed out waiting for {what}")
        time.sleep(0.02)


def test_preview_lock_order_settle_shared_then_account(env: Env) -> None:
    done: list[Any] = []
    # someone holds the ACCOUNT lock: the preview waits there already holding settle shared
    with env.engine.connect() as holder:
        with holder.begin():
            pid = int(holder.execute(text("SELECT pg_backend_pid()")).scalar_one())
            lock_accounts(holder, [env.account])
            thread = threading.Thread(target=lambda: done.append(_preview(env, _rows())))
            thread.start()
            _until(lambda: lockwatch.advisory_waiters(env.engine) >= 1, "the preview to wait for the account")
            shared = lockwatch.advisory_held(
                env.engine, exclude_pid=pid, classid=_SETTLE_CLASS, mode="ShareLock"
            )
            assert shared == 1
    thread.join(timeout=15)
    assert not thread.is_alive() and len(done) == 1
    # someone holds settle EXCLUSIVE: the preview takes no account lock before it
    done.clear()
    with env.engine.connect() as holder:
        with holder.begin():
            pid = int(holder.execute(text("SELECT pg_backend_pid()")).scalar_one())
            lock_settle_exclusive(holder)
            thread = threading.Thread(target=lambda: done.append(_preview(env, _rows())))
            thread.start()
            _until(lambda: lockwatch.advisory_waiters(env.engine) >= 1, "the preview to wait for settle")
            held = lockwatch.advisory_held(
                env.engine, exclude_pid=pid, classid=_ACCOUNT_CLASS, mode="ExclusiveLock"
            )
            assert held == 0
    thread.join(timeout=15)
    assert not thread.is_alive() and len(done) == 1
