"""Session and configuration endpoints (architecture §4.1).

The architecture names `POST/DELETE/GET /api/session`. `/api/login`,
`/api/logout` and `/api/me` are the same handlers under friendlier names.
"""

from __future__ import annotations

import hmac
import logging
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from app.api.errors import ApiError
from app.api.session import (
    COOKIE_NAME,
    CurrentUser,
    EngineDep,
    clear_session_cookie,
    is_localhost,
    set_session_cookie,
)
from app.utils.auth import (
    AuthUser,
    OidcError,
    OidcFlow,
    admit,
    authenticate_password,
    establish_session,
    revoke_session,
)
from app.utils.auth.oidc import FAILED, PENDING_TTL
from app.utils.config import Config

log = logging.getLogger("ledgehog.api")

router = APIRouter(prefix="/api")

OIDC_STATE_COOKIE = "ledgehog_oidc_state"
OIDC_STATE_PATH = "/api/session/oidc"


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login: str
    password: str


def _user_json(user: AuthUser) -> dict[str, Any]:
    return {"id": user.id, "login": user.login, "display_name": user.display_name}


@router.post("/session")
@router.post("/login", include_in_schema=False)
def login(body: LoginBody, request: Request, response: Response, engine: EngineDep) -> dict[str, Any]:
    cfg: Config = request.app.state.config
    if cfg.oidc is not None and cfg.oidc.enforced:
        raise ApiError(403, "password_login_disabled", "Signing in with a password is turned off.")
    with engine.begin() as conn:
        user_id = authenticate_password(conn, body.login, body.password)
        if user_id is None:
            # one shape for an unknown login, a wrong password and a disabled user
            raise ApiError(401, "invalid_credentials", "Wrong login or password.")
        session_id = establish_session(conn, user_id, "password", now=request.app.state.instant())
        row = conn.execute(
            text("SELECT id, login, display_name FROM app_user WHERE id = :id"), {"id": user_id}
        ).one()
    set_session_cookie(response, request, session_id)
    return {"id": row.id, "login": row.login, "display_name": row.display_name}


def _oidc(request: Request) -> OidcFlow:
    flow: OidcFlow | None = request.app.state.oidc
    if flow is None:
        raise ApiError(404, "oidc_not_configured", "OIDC sign-in is not configured.")
    return flow


def _to_login(request: Request, error: str | None = None) -> RedirectResponse:
    """Back to the login page, with the reason when there is one; the state cookie is always spent."""
    out = RedirectResponse(f"/login?error={error}" if error else "/", status_code=303)
    out.delete_cookie(
        OIDC_STATE_COOKIE,
        path=OIDC_STATE_PATH,
        httponly=True,
        samesite="lax",
        secure=not is_localhost(request),
    )
    return out


@router.get("/session/oidc", include_in_schema=False)
def oidc_start(request: Request) -> RedirectResponse:
    """Send the browser to the provider; the state it returns with is bound to this browser by a cookie."""
    flow = _oidc(request)
    try:
        url, state = flow.start(request.app.state.instant())
    except OidcError as exc:
        log.warning("oidc: could not begin a sign-in: %s", exc)
        return _to_login(request, exc.code)
    out = RedirectResponse(url, status_code=303)
    out.set_cookie(
        OIDC_STATE_COOKIE,
        state,
        max_age=int(PENDING_TTL.total_seconds()),
        path=OIDC_STATE_PATH,
        httponly=True,
        samesite="lax",  # the provider's return is a top-level GET, which Lax still carries
        secure=not is_localhost(request),
    )
    return out


@router.get("/session/oidc/callback", include_in_schema=False)
def oidc_callback(
    request: Request,
    engine: EngineDep,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """The provider's return: sign in and go to the app, or go back to the login page with the reason."""
    flow = _oidc(request)
    bound = request.cookies.get(OIDC_STATE_COOKIE)
    if not state or not bound or not hmac.compare_digest(state.encode(), bound.encode()):
        log.warning("oidc: a return without the state this browser began")
        return _to_login(request, FAILED)
    if error or not code:
        log.warning("oidc: the provider returned without a code (error=%s)", (error or "none")[:40])
        return _to_login(request, FAILED)
    now = request.app.state.instant()
    try:
        identity = flow.finish(state, code, now)
        with engine.begin() as conn:  # the rules and the session are one transaction
            user_id = admit(conn, flow.cfg, identity)
            session_id = establish_session(conn, user_id, "oidc", now=now)
    except OidcError as exc:
        log.warning("oidc: sign-in refused: %s", exc)
        return _to_login(request, exc.code)
    except Exception as exc:
        log.warning("oidc: sign-in failed unexpectedly (%s)", type(exc).__name__)
        return _to_login(request, FAILED)
    out = _to_login(request)
    set_session_cookie(out, request, session_id)
    return out


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
def config_view(request: Request) -> dict[str, Any]:
    """Read-only configuration for the client; never a secret (architecture §5.7).

    Needs no session: the login page asks it whether OIDC sign-in is offered or enforced.
    """
    cfg: Config = request.app.state.config
    return {
        "oidc_offered": cfg.oidc is not None,
        "oidc_enforced": cfg.oidc is not None and cfg.oidc.enforced,
        "base_currency": cfg.base_currency,
        "timezone": cfg.timezone.key,
        "locale": cfg.locale,
        "max_rate_age_days": cfg.max_rate_age_days,
        "matching_window_days": cfg.matching_window_days,
        "document_window_back_days": cfg.document_window_back_days,
        "document_window_ahead_days": cfg.document_window_ahead_days,
    }
