"""Login sessions (architecture §4.5, §5.6).

A session row references a user and records the method that established it
(`password` or `oidc`). The cookie carries only the opaque id, so revocation
is deleting the row. `establish_session` is the single seam both methods end in.

Expiry slides: 30 days from last use. `touch_session` writes only when that
would move the expiry by more than `TOUCH_GRANULARITY`, so a burst of requests
is not a burst of writes.

Time is the injected clock (`app.utils.clock`), never the database's `now()`:
`created_at` is written explicitly so `ck_session_expiry` holds under a frozen
clock too.

Conscious omission (architecture §5.6): there is no login rate limiting - a
household, self-hosted.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import Connection, text

from app.utils import clock
from app.utils.auth.passwords import hash_password, needs_rehash, verify_dummy, verify_password

SESSION_LIFETIME = timedelta(days=30)
TOUCH_GRANULARITY = timedelta(hours=1)

Method = Literal["password", "oidc"]


@dataclass(frozen=True, slots=True)
class AuthUser:
    """The active, enabled user a session resolves to."""

    id: int
    login: str
    display_name: str
    session_id: str
    expires_at: datetime


def new_session_id() -> str:
    return secrets.token_urlsafe(32)


def establish_session(conn: Connection, user_id: int, method: Method, *, now: datetime | None = None) -> str:
    """Create a session for an already-verified user and return its opaque id."""
    moment = now or clock.now()
    # housekeeping: this user's lapsed sessions are dead weight
    conn.execute(
        text("DELETE FROM session WHERE user_id = :u AND expires_at <= :now"),
        {"u": user_id, "now": moment},
    )
    session_id = new_session_id()
    conn.execute(
        text(
            "INSERT INTO session (id, user_id, method, created_at, expires_at) "
            "VALUES (:id, :u, :m, :now, :exp)"
        ),
        {"id": session_id, "u": user_id, "m": method, "now": moment, "exp": moment + SESSION_LIFETIME},
    )
    return session_id


def session_user(conn: Connection, session_id: str, *, now: datetime | None = None) -> AuthUser | None:
    """The enabled user behind an unexpired session, else None (unknown, expired, disabled)."""
    moment = now or clock.now()
    row = conn.execute(
        text(
            "SELECT u.id, u.login, u.display_name, s.id AS session_id, s.expires_at "
            "FROM session s JOIN app_user u ON u.id = s.user_id "
            "WHERE s.id = :id AND s.expires_at > :now AND NOT u.disabled"
        ),
        {"id": session_id, "now": moment},
    ).one_or_none()
    if row is None:
        return None
    return AuthUser(row.id, row.login, row.display_name, row.session_id, row.expires_at)


def touch_session(conn: Connection, session_id: str, *, now: datetime | None = None) -> datetime | None:
    """Slide the expiry to 30 days from now; returns the new expiry, or None when no write was needed."""
    moment = now or clock.now()
    new_expiry = moment + SESSION_LIFETIME
    return conn.execute(
        text(
            "UPDATE session SET expires_at = :new "
            "WHERE id = :id AND expires_at > :now AND expires_at < :threshold "
            "RETURNING expires_at"
        ),
        {"id": session_id, "now": moment, "new": new_expiry, "threshold": new_expiry - TOUCH_GRANULARITY},
    ).scalar_one_or_none()


def revoke_session(conn: Connection, session_id: str) -> None:
    conn.execute(text("DELETE FROM session WHERE id = :id"), {"id": session_id})


def revoke_sessions(conn: Connection, user_id: int) -> None:
    conn.execute(text("DELETE FROM session WHERE user_id = :u"), {"u": user_id})


def authenticate_password(conn: Connection, login: str, password: str) -> int | None:
    """The user id when `login`/`password` are valid for an enabled user, else None.

    An unknown or disabled login is verified against a dummy hash so the failure
    costs the same as a wrong password. A hash made with outdated parameters is
    upgraded on the way through.
    """
    row = conn.execute(
        text("SELECT id, pw_hash, disabled FROM app_user WHERE login = :login"), {"login": login}
    ).one_or_none()
    if row is None or row.disabled or row.pw_hash is None:  # no password: fails like a wrong one
        verify_dummy(password)
        return None
    if not verify_password(row.pw_hash, password):
        return None
    if needs_rehash(row.pw_hash):
        conn.execute(
            text("UPDATE app_user SET pw_hash = :h WHERE id = :id"),
            {"h": hash_password(password), "id": row.id},
        )
    return int(row.id)
