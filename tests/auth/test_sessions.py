from datetime import timedelta

import pytest
from sqlalchemy import text

from app.utils.auth import (
    SESSION_LIFETIME,
    authenticate_password,
    establish_session,
    hash_password,
    new_session_id,
    revoke_session,
    revoke_sessions,
    session_user,
    touch_session,
)


@pytest.fixture
def user_id(db_conn):
    return db_conn.execute(
        text("INSERT INTO app_user (login, pw_hash, display_name) VALUES ('anna', :h, 'Anna') RETURNING id"),
        {"h": hash_password("pw-anna")},
    ).scalar_one()


def _expiry(conn, sid):
    return conn.execute(text("SELECT expires_at FROM session WHERE id = :i"), {"i": sid}).scalar_one()


def test_session_ids_are_opaque_and_unique():
    a, b = new_session_id(), new_session_id()
    assert a != b and len(a) >= 43


def test_establish_writes_row_with_method_and_30_day_expiry(db_conn, user_id, clock):
    sid = establish_session(db_conn, user_id, "password")
    row = db_conn.execute(
        text("SELECT method, created_at, expires_at FROM session WHERE id = :i"), {"i": sid}
    ).one()
    assert row.method == "password"
    assert row.created_at == clock.now()
    assert row.expires_at == clock.now() + SESSION_LIFETIME


def test_session_user_resolves_active_session(db_conn, user_id, clock):
    sid = establish_session(db_conn, user_id, "password")
    u = session_user(db_conn, sid)
    assert u is not None and (u.id, u.login, u.display_name) == (user_id, "anna", "Anna")


def test_unknown_session_id_is_none(db_conn, user_id):
    assert session_user(db_conn, "no-such-session") is None


def test_expired_session_is_none(db_conn, user_id, clock):
    sid = establish_session(db_conn, user_id, "password")
    clock.advance(SESSION_LIFETIME + timedelta(seconds=1))
    assert session_user(db_conn, sid) is None


def test_disabled_user_session_is_invalid(db_conn, user_id, clock):
    sid = establish_session(db_conn, user_id, "password")
    db_conn.execute(text("UPDATE app_user SET disabled = true WHERE id = :i"), {"i": user_id})
    assert session_user(db_conn, sid) is None


def test_touch_slides_expiry_after_a_meaningful_gap(db_conn, user_id, clock):
    sid = establish_session(db_conn, user_id, "password")
    clock.advance(timedelta(days=2))
    new = touch_session(db_conn, sid)
    assert new == clock.now() + SESSION_LIFETIME
    assert _expiry(db_conn, sid) == new


def test_touch_does_not_write_for_small_moves(db_conn, user_id, clock):
    sid = establish_session(db_conn, user_id, "password")
    before = _expiry(db_conn, sid)
    clock.advance(timedelta(minutes=30))
    assert touch_session(db_conn, sid) is None
    assert _expiry(db_conn, sid) == before


def test_touch_does_not_revive_an_expired_session(db_conn, user_id, clock):
    sid = establish_session(db_conn, user_id, "password")
    clock.advance(SESSION_LIFETIME + timedelta(days=1))
    assert touch_session(db_conn, sid) is None
    assert session_user(db_conn, sid) is None


def test_revoke_session_and_revoke_sessions(db_conn, user_id, clock):
    a, b = establish_session(db_conn, user_id, "password"), establish_session(db_conn, user_id, "oidc")
    revoke_session(db_conn, a)
    assert session_user(db_conn, a) is None and session_user(db_conn, b) is not None
    revoke_sessions(db_conn, user_id)
    assert session_user(db_conn, b) is None


def test_establish_purges_the_users_lapsed_sessions(db_conn, user_id, clock):
    old = establish_session(db_conn, user_id, "password")
    clock.advance(SESSION_LIFETIME + timedelta(days=1))
    establish_session(db_conn, user_id, "password")
    assert db_conn.execute(text("SELECT count(*) FROM session WHERE id = :i"), {"i": old}).scalar_one() == 0


def test_authenticate_password(db_conn, user_id):
    assert authenticate_password(db_conn, "anna", "pw-anna") == user_id
    assert authenticate_password(db_conn, "anna", "nope") is None
    assert authenticate_password(db_conn, "ghost", "pw-anna") is None
    db_conn.execute(text("UPDATE app_user SET disabled = true WHERE id = :i"), {"i": user_id})
    assert authenticate_password(db_conn, "anna", "pw-anna") is None


def test_authenticate_upgrades_an_outdated_hash(db_conn, user_id):
    from argon2 import PasswordHasher
    from argon2.low_level import Type

    weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1, type=Type.ID).hash("pw-anna")
    db_conn.execute(text("UPDATE app_user SET pw_hash = :h WHERE id = :i"), {"h": weak, "i": user_id})
    assert authenticate_password(db_conn, "anna", "pw-anna") == user_id
    new = db_conn.execute(text("SELECT pw_hash FROM app_user WHERE id = :i"), {"i": user_id}).scalar_one()
    assert new != weak
