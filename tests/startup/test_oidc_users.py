"""Start reconciliation with provider-owned and password-less users (architecture §5.7, D226)."""

from __future__ import annotations

import logging

from sqlalchemy import text

from app.startup import reconcile_users, start
from app.utils.auth import authenticate_password
from app.utils.config import Secret, UserConfig


def rows(conn):
    return {
        r.login: r
        for r in conn.execute(text("SELECT login, pw_hash, display_name, disabled, source FROM app_user"))
    }


def make_oidc_user(conn, login="zoe@home.test", name="Zoe"):
    conn.execute(
        text("INSERT INTO app_user (login, pw_hash, display_name, source) VALUES (:l, NULL, :n, 'oidc')"),
        {"l": login, "n": name},
    )


def test_a_provider_user_is_never_disabled_for_being_absent(isolated_engine):
    with isolated_engine.begin() as conn:
        make_oidc_user(conn)
        result = reconcile_users(conn, [UserConfig("anna", "Anna", Secret("pw-anna-1111"))])
        assert result.disabled == () and result.ignored == ()
        assert rows(conn)["zoe@home.test"].disabled is False


def test_a_configured_login_naming_a_provider_user_is_ignored_and_logged(isolated_engine, caplog):
    with isolated_engine.begin() as conn:
        make_oidc_user(conn, "anna", "Anna Provider")
        cfg = UserConfig("anna", "Anna Config", Secret("pw-anna-1111"))
        with caplog.at_level(logging.INFO):
            result = reconcile_users(conn, [cfg])
        assert result.ignored == ("anna",)
        r = rows(conn)["anna"]
        assert (r.source, r.pw_hash, r.display_name) == ("oidc", None, "Anna Provider")
    assert "anna-1111" not in caplog.text


def test_a_passwordless_configured_user_has_no_hash(isolated_engine):
    with isolated_engine.begin() as conn:
        result = reconcile_users(conn, [UserConfig("anna", "Anna", None)])
        assert result.created == ("anna",)
        assert rows(conn)["anna"].pw_hash is None
        assert authenticate_password(conn, "anna", "") is None
        assert authenticate_password(conn, "anna", "anything") is None


def test_enforcing_drops_a_configured_password_and_its_sessions(isolated_engine):
    with isolated_engine.begin() as conn:
        reconcile_users(conn, [UserConfig("anna", "Anna", Secret("pw-anna-1111"))])
        uid = conn.execute(text("SELECT id FROM app_user WHERE login = 'anna'")).scalar_one()
        conn.execute(
            text(
                "INSERT INTO session (id, user_id, method, created_at, expires_at) "
                "VALUES ('s1', :u, 'password', now(), now() + interval '1 day')"
            ),
            {"u": uid},
        )
        result = reconcile_users(conn, [UserConfig("anna", "Anna", None)])
        assert result.rehashed == ("anna",)
        assert rows(conn)["anna"].pw_hash is None
        assert conn.execute(text("SELECT count(*) FROM session")).scalar_one() == 0
        # and a password configured again is set again
        reconcile_users(conn, [UserConfig("anna", "Anna", Secret("pw-anna-2222"))])
        assert authenticate_password(conn, "anna", "pw-anna-2222") is not None


def test_a_configured_user_not_configured_any_more_is_still_disabled(isolated_engine):
    with isolated_engine.begin() as conn:
        reconcile_users(conn, [UserConfig("anna", "Anna", Secret("pw-anna-1111"))])
        make_oidc_user(conn)
        result = reconcile_users(conn, [])
        assert result.disabled == ("anna",)
        assert rows(conn)["zoe@home.test"].disabled is False


def test_the_schema_refuses_a_provider_user_with_a_password(isolated_engine):
    import pytest
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError, match="ck_app_user_oidc_no_password"), isolated_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO app_user (login, pw_hash, display_name, source) VALUES ('x', 'h', 'X', 'oidc')")
        )


def test_start_logs_an_ignored_login_by_name_only(isolated_db, caplog):
    from dataclasses import replace

    from app.utils.db.engine import make_engine

    engine = make_engine(isolated_db)
    try:
        with engine.begin() as conn:
            make_oidc_user(conn, "anna", "Anna Provider")
        cfg = replace(isolated_db, users=(UserConfig("anna", "Anna", Secret("pw-anna-1111")),))
        with caplog.at_level(logging.INFO, logger="ledgehog.startup"):
            started = start(cfg, engine)
        assert started.reconciled.ignored == ("anna",)
        assert "anna" in caplog.text and "pw-anna-1111" not in caplog.text
    finally:
        engine.dispose()
