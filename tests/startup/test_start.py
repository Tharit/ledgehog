from __future__ import annotations

import logging

import pytest
from sqlalchemy import text

import app.startup as startup
from app.core.settle import SettleResult
from app.startup import BaseCurrencyMismatch, start
from tests.startup.conftest import user


def test_start_runs_the_sequence_and_builds_the_app(isolated_engine, make_config, clock):
    cfg = make_config(user("anna"), user("ben"))
    with isolated_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO import_run (importer, emits, status) VALUES ('t', 'rates', 'running')")
        )
    started = start(cfg, isolated_engine)
    assert started.failed_runs == 1
    assert started.reconciled.created == ("anna", "ben")
    assert started.settle_result.error is None
    assert started.app.state.engine is isolated_engine
    with isolated_engine.connect() as conn:
        assert conn.execute(text("SELECT base_currency FROM ledger_setting")).scalar_one().strip() == "EUR"
        assert conn.execute(text("SELECT status FROM import_run")).scalar_one() == "failed"


def test_start_twice_is_idempotent(isolated_engine, make_config):
    cfg = make_config(user("anna"))
    start(cfg, isolated_engine)
    again = start(cfg, isolated_engine)
    assert again.reconciled == type(again.reconciled)() and again.failed_runs == 0


def test_start_refuses_on_base_currency_mismatch_and_does_not_reconcile(isolated_engine, make_config):
    start(make_config(user("anna")), isolated_engine)
    with pytest.raises(BaseCurrencyMismatch):
        start(make_config(user("anna"), user("ben"), base_currency="USD"), isolated_engine)
    with isolated_engine.connect() as conn:
        assert conn.execute(text("SELECT login FROM app_user")).scalars().all() == ["anna"]


def test_settle_is_called_exactly_once(isolated_engine, make_config, monkeypatch):
    calls = []

    def spy(engine):
        calls.append(engine)
        return SettleResult()

    monkeypatch.setattr(startup, "settle", spy)
    start(make_config(user("anna")), isolated_engine)
    assert calls == [isolated_engine]


def test_a_settle_error_is_logged_and_does_not_stop_start(isolated_engine, make_config, monkeypatch, caplog):
    monkeypatch.setattr(startup, "settle", lambda engine: SettleResult(error="boom in step 3"))
    with caplog.at_level(logging.ERROR, logger="ledgehog.startup"):
        started = start(make_config(user("anna")), isolated_engine)
    assert started.settle_result.error == "boom in step 3"
    assert "boom in step 3" in caplog.text


def test_start_logs_no_secret(isolated_engine, make_config, caplog):
    cfg = make_config(user("anna", password="s3cret-anna-pw"))
    with caplog.at_level(logging.DEBUG):
        start(cfg, isolated_engine)
    assert "s3cret-anna-pw" not in caplog.text
    assert cfg.db.password.reveal() not in caplog.text
    assert "anna" in caplog.text  # users are named by login
