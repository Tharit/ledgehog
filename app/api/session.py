"""Session cookie transport and the authentication dependency (architecture §4.5, §5.6)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request, Response
from sqlalchemy import Engine

from app.api.errors import ApiError
from app.utils.auth import SESSION_LIFETIME, AuthUser, session_user, touch_session

COOKIE_NAME = "ledgehog_session"
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def is_localhost(request: Request) -> bool:
    """Decided per request from the host it was addressed to (not from a setting)."""
    return (request.url.hostname or "").lower() in _LOCAL_HOSTS


def set_session_cookie(response: Response, request: Request, session_id: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        session_id,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        path="/",
        httponly=True,
        samesite="lax",
        secure=not is_localhost(request),
    )


def clear_session_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        COOKIE_NAME, path="/", httponly=True, samesite="lax", secure=not is_localhost(request)
    )


def get_engine(request: Request) -> Engine:
    engine: Engine = request.app.state.engine
    return engine


EngineDep = Annotated[Engine, Depends(get_engine)]


def current_user(request: Request, response: Response, engine: EngineDep) -> AuthUser:
    """The signed-in user, or a 401 in the error envelope. Slides the session on use."""
    session_id = request.cookies.get(COOKIE_NAME)
    if not session_id:
        raise ApiError(401, "unauthenticated", "Not signed in.")
    now = request.app.state.now()
    with engine.begin() as conn:
        user = session_user(conn, session_id, now=now)
        touched = touch_session(conn, session_id, now=now) if user else None
    if user is None:
        raise ApiError(401, "unauthenticated", "Not signed in.")
    if touched is not None:
        set_session_cookie(response, request, session_id)  # keep the browser's cookie in step
    return user


CurrentUser = Annotated[AuthUser, Depends(current_user)]
