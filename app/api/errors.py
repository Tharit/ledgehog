"""The error envelope (architecture §4.4).

Every non-2xx response is `{"error": {"code", "message", "details"}}`. The
frontend routes on `code`, never on message text. Validation details carry the
location and rule of each problem but never the offending input: a login body
holds a password.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.stale import StaleReference, stale_from_integrity

log = logging.getLogger("ledgehog.api")

_STATUS_CODES = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
}


class ApiError(Exception):
    """Raise from an endpoint to answer with a specific code."""

    def __init__(self, status: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


@dataclass(frozen=True)
class _Mapping:
    status: int
    code: str
    details: Callable[[Any], Any] | None


# domain exception class -> how it is answered. Filled by the router modules at import;
# a raised exception uses the nearest registered ancestor (Starlette resolves by MRO).
_DOMAIN_ERRORS: dict[type[Exception], _Mapping] = {}


def map_error(
    exc_type: type[Exception], status: int, code: str, *, details: Callable[[Any], Any] | None = None
) -> None:
    """Answer `exc_type` (and its subclasses) with `status` and the envelope `code`.

    The message is `str(exc)`: domain errors state the rule and never quote file content or
    secrets. `details` may add structured data (the entries that moved, say).
    """
    _DOMAIN_ERRORS[exc_type] = _Mapping(status, code, details)


def _stale_details(exc: StaleReference) -> dict[str, Any]:
    return {"field": exc.field, "entity": exc.entity, "id": exc.entity_id}


# a write naming a category, payee or account that no longer exists (architecture §4.1, D200)
map_error(StaleReference, 409, "stale_reference", details=_stale_details)


def envelope(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


def _respond(status: int, code: str, message: str, details: Any = None) -> JSONResponse:
    return JSONResponse(envelope(code, message, details), status_code=status)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _respond(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, "http_error")
        return _respond(exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {
                "location": [str(p) for p in e.get("loc", ())],
                "message": e.get("msg", ""),
                "type": e.get("type", ""),
            }
            for e in exc.errors()
        ]
        return _respond(422, "validation_error", "The request is not valid.", details)

    def _domain(mapping: _Mapping) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
        async def handler(_: Request, exc: Exception) -> JSONResponse:
            details = mapping.details(exc) if mapping.details else None
            return _respond(mapping.status, mapping.code, str(exc), details)

        return handler

    for exc_type, mapping in _DOMAIN_ERRORS.items():
        app.add_exception_handler(exc_type, _domain(mapping))

    @app.exception_handler(DBAPIError)
    async def _database_error(_: Request, exc: DBAPIError) -> JSONResponse:
        # the net under every write: a foreign key whose target a merge or delete removed
        stale = stale_from_integrity(exc)
        if stale is not None:
            return _respond(409, "stale_reference", str(stale), _stale_details(stale))
        raise exc  # anything else stays unexpected: the server-error handler below answers it

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        # the type only: a traceback or message could carry a secret (architecture §4.5)
        log.error("unhandled error: %s", type(exc).__name__)
        return _respond(500, "internal_error", "Something went wrong.")
