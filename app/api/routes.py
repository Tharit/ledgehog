"""Session and configuration endpoints (architecture §4.1).

The architecture names `POST/DELETE/GET /api/session`. `/api/login`,
`/api/logout` and `/api/me` are the same handlers under friendlier names.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from app.api.errors import ApiError
from app.api.session import (
    COOKIE_NAME,
    CurrentUser,
    EngineDep,
    clear_session_cookie,
    set_session_cookie,
)
from app.utils.auth import AuthUser, authenticate_password, establish_session, revoke_session
from app.utils.config import Config

router = APIRouter(prefix="/api")


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login: str
    password: str


def _user_json(user: AuthUser) -> dict[str, Any]:
    return {"id": user.id, "login": user.login, "display_name": user.display_name}


@router.post("/session")
@router.post("/login", include_in_schema=False)
def login(body: LoginBody, request: Request, response: Response, engine: EngineDep) -> dict[str, Any]:
    with engine.begin() as conn:
        user_id = authenticate_password(conn, body.login, body.password)
        if user_id is None:
            # one shape for an unknown login, a wrong password and a disabled user
            raise ApiError(401, "invalid_credentials", "Wrong login or password.")
        session_id = establish_session(conn, user_id, "password", now=request.app.state.now())
        row = conn.execute(
            text("SELECT id, login, display_name FROM app_user WHERE id = :id"), {"id": user_id}
        ).one()
    set_session_cookie(response, request, session_id)
    return {"id": row.id, "login": row.login, "display_name": row.display_name}


@router.delete("/session", status_code=204)
@router.post("/logout", status_code=204, include_in_schema=False)
def logout(request: Request, engine: EngineDep) -> Response:
    session_id = request.cookies.get(COOKIE_NAME)
    if session_id:
        with engine.begin() as conn:
            revoke_session(conn, session_id)
    out = Response(status_code=204)
    clear_session_cookie(out, request)
    return out


@router.get("/session")
@router.get("/me", include_in_schema=False)
def me(user: CurrentUser) -> dict[str, Any]:
    return _user_json(user)


@router.get("/config")
def config_view(request: Request, _: CurrentUser) -> dict[str, Any]:
    """Read-only configuration for the client; never a secret (architecture §5.7)."""
    cfg: Config = request.app.state.config
    return {
        "base_currency": cfg.base_currency,
        "timezone": cfg.timezone.key,
        "locale": cfg.locale,
        "max_rate_age_days": cfg.max_rate_age_days,
        "matching_window_days": cfg.matching_window_days,
        "document_window_days": cfg.document_window_days,
    }
