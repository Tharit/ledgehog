from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from app.startup import (
    BaseCurrencyMismatch,
    StartupError,
    assert_pool_settings,
    ensure_base_currency,
    fail_interrupted_runs,
    reconcile_users,
)
from app.utils.auth import establish_session, session_user, verify_password
from app.utils.db.engine import database_url
from tests.startup.conftest import user


def _insert_run(conn, status: str) -> int:
    finished = "NULL" if status == "running" else "now()"
    return conn.execute(
        text(
            "INSERT INTO import_run (importer, emits, status, finished_at) "
            f"VALUES ('test', 'rates', :s, {finished}) RETURNING id"
        ),
        {"s": status},
    ).scalar_one()


def test_running_runs_become_failed_with_finished_at(db_conn, clock):
    running, ok = _insert_run(db_conn, "running"), _insert_run(db_conn, "ok")
    assert fail_interrupted_runs(db_conn) == 1
    rows = {
        r.id: r
        for r in db_conn.execute(
            text("SELECT id, status, finished_at, error_text, retryable FROM import_run")
        )
    }
    assert rows[running].status == "failed"
    assert rows[running].finished_at == clock.now()
    assert rows[running].error_text
    assert rows[running].retryable is True  # interrupted by a restart: running it again can help
    assert rows[ok].status == "ok" and rows[ok].retryable is None


def test_base_currency_written_on_first_start_and_accepted_again(db_conn):
    ensure_base_currency(db_conn, "EUR")
    ensure_base_currency(db_conn, "EUR")
    assert db_conn.execute(text("SELECT base_currency FROM ledger_setting")).scalars().all() == ["EUR"]


def test_base_currency_mismatch_refuses_and_leaves_the_stored_value(db_conn):
    ensure_base_currency(db_conn, "EUR")
    with pytest.raises(BaseCurrencyMismatch) as err:
        ensure_base_currency(db_conn, "USD")
    assert "USD" in str(err.value) and "EUR" in str(err.value)
    assert db_conn.execute(text("SELECT base_currency FROM ledger_setting")).scalar_one().strip() == "EUR"


def _users(conn):
    return {
        r.login: r
        for r in conn.execute(text("SELECT id, login, display_name, pw_hash, disabled FROM app_user"))
    }


def test_reconcile_creates_missing_users(db_conn):
    result = reconcile_users(db_conn, [user("anna", "Anna"), user("ben", "Ben")])
    assert result.created == ("anna", "ben")
    rows = _users(db_conn)
    assert rows["anna"].display_name == "Anna" and not rows["anna"].disabled
    assert verify_password(rows["anna"].pw_hash, "pw-anna-0000")
    assert "pw-anna-0000" not in rows["anna"].pw_hash


def test_reconcile_updates_display_name_and_keeps_sessions(db_conn, clock):
    reconcile_users(db_conn, [user("anna", "Anna")])
    sid = establish_session(db_conn, _users(db_conn)["anna"].id, "password")
    result = reconcile_users(db_conn, [user("anna", "Anna K.")])
    assert result.renamed == ("anna",) and result.rehashed == ()
    assert _users(db_conn)["anna"].display_name == "Anna K."
    assert session_user(db_conn, sid) is not None


def test_unchanged_password_keeps_hash_and_sessions(db_conn, clock):
    reconcile_users(db_conn, [user("anna")])
    before = _users(db_conn)["anna"]
    sid = establish_session(db_conn, before.id, "password")
    result = reconcile_users(db_conn, [user("anna")])
    assert result == type(result)()  # nothing changed
    assert _users(db_conn)["anna"].pw_hash == before.pw_hash
    assert session_user(db_conn, sid) is not None


def test_changed_password_rehashes_and_deletes_that_users_sessions_only(db_conn, clock):
    reconcile_users(db_conn, [user("anna"), user("ben")])
    rows = _users(db_conn)
    anna_sid = establish_session(db_conn, rows["anna"].id, "password")
    ben_sid = establish_session(db_conn, rows["ben"].id, "password")
    result = reconcile_users(db_conn, [user("anna", password="a-new-password"), user("ben")])
    assert result.rehashed == ("anna",)
    assert verify_password(_users(db_conn)["anna"].pw_hash, "a-new-password")
    assert session_user(db_conn, anna_sid) is None
    assert session_user(db_conn, ben_sid) is not None


def test_removed_user_is_disabled_not_deleted_and_loses_sessions(db_conn, clock):
    reconcile_users(db_conn, [user("anna"), user("ben")])
    ben = _users(db_conn)["ben"]
    sid = establish_session(db_conn, ben.id, "password")
    result = reconcile_users(db_conn, [user("anna")])
    assert result.disabled == ("ben",)
    after = _users(db_conn)["ben"]
    assert after.id == ben.id and after.disabled
    assert session_user(db_conn, sid) is None
    assert (
        db_conn.execute(text("SELECT count(*) FROM session WHERE user_id = :u"), {"u": ben.id}).scalar_one()
        == 0
    )


def test_readded_user_is_reenabled_with_the_same_id(db_conn, clock):
    reconcile_users(db_conn, [user("anna"), user("ben")])
    ben_id = _users(db_conn)["ben"].id
    reconcile_users(db_conn, [user("anna")])
    result = reconcile_users(db_conn, [user("anna"), user("ben")])
    assert result.enabled == ("ben",)
    assert not _users(db_conn)["ben"].disabled and _users(db_conn)["ben"].id == ben_id


def test_reconcile_with_no_users_disables_everyone(db_conn):
    reconcile_users(db_conn, [user("anna")])
    reconcile_users(db_conn, [])
    assert _users(db_conn)["anna"].disabled


def test_pool_setting_is_asserted(isolated_engine, make_config):
    assert_pool_settings(isolated_engine, make_config())  # made by make_engine: passes


def test_pool_setting_missing_is_refused(isolated_db, make_config):
    plain = create_engine(database_url(isolated_db))  # not make_engine: no GUC set
    try:
        with pytest.raises(StartupError, match="max_rate_age"):
            assert_pool_settings(plain, make_config())
    finally:
        plain.dispose()


def test_pool_matching_window_mismatch_is_refused(isolated_engine, make_config):
    from dataclasses import replace

    with pytest.raises(StartupError, match="matching_window_days"):
        assert_pool_settings(isolated_engine, replace(make_config(), matching_window_days=9))
