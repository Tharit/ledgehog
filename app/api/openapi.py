"""The OpenAPI document: stable operation ids and the real error envelope (architecture §4.4).

FastAPI documents a 422 as `HTTPValidationError`, but this API answers every non-2xx with
`{"error": {"code", "message", "details"}}` (`app.api.errors`). `install_openapi` replaces the
generated document by one that says so: the validation schemas are dropped, and each operation
lists the envelope for the codes it can produce (401 when it needs a session, 422 when it
validates input, 404 below a path parameter, 409 when it writes).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts
from pydantic import BaseModel

from app.api.session import current_user

_HTTP_METHODS = ("get", "post", "put", "patch", "delete")
_REF = "#/components/schemas/{model}"
_DESCRIPTIONS = {
    "401": "Not signed in (or wrong login or password).",
    "404": "Not found.",
    "409": "Conflicts with the current state.",
    "422": "The request is not valid.",
}


class ErrorBody(BaseModel):
    """The `error` object: the frontend routes on `code`, never on `message`."""

    code: str
    message: str
    details: Any


class ErrorEnvelope(BaseModel):
    """Every non-2xx response body (architecture §4.4)."""

    error: ErrorBody


def api_routes(app: FastAPI) -> list[RouteContext]:
    """Every API route of the app, routers included (FastAPI resolves an included router lazily)."""
    return [
        ctx
        for ctx in iter_route_contexts(app.routes)
        if isinstance(ctx.original_route, APIRoute) and ctx.include_in_schema
    ]


def operation_id(route: APIRoute | RouteContext) -> str:
    """The handler's function name: stable, readable in generated clients (unique across routers)."""
    return str(route.name)


def envelope_response(description: str) -> dict[str, Any]:
    return {
        "description": description,
        "content": {"application/json": {"schema": {"$ref": _REF.format(model="ErrorEnvelope")}}},
    }


def _needs_session(dependant: Dependant) -> bool:
    return any(d.call is current_user or _needs_session(d) for d in dependant.dependencies)


_EXTRA_SCHEMAS: list[type[BaseModel]] = []


def register_schema(*models: type[BaseModel]) -> None:
    """Publish models no route returns as a body (a stream's event payloads, which `responses` can only
    describe as text) among the document's component schemas."""
    for model in models:
        if model not in _EXTRA_SCHEMAS:
            _EXTRA_SCHEMAS.append(model)


def _components() -> dict[str, Any]:
    out: dict[str, Any] = {}
    models: list[type[BaseModel]] = [ErrorEnvelope, *_EXTRA_SCHEMAS]
    for model in models:
        schema = model.model_json_schema(ref_template=_REF)
        out.update(schema.pop("$defs", {}))
        out[model.__name__] = schema
    return out


def _post_process(app: FastAPI, schema: dict[str, Any]) -> dict[str, Any]:
    routes = {
        (route.path_format, method.lower()): route
        for route in api_routes(app)
        for method in route.methods or ()
    }
    for path, item in schema.get("paths", {}).items():
        for method in _HTTP_METHODS:
            op = item.get(method)
            route = routes.get((path, method))
            if op is None or route is None:
                continue
            codes: list[str] = []
            authenticated = _needs_session(route.dependant)
            if authenticated or route.name == "login":
                codes += ["401", "422"]
            if "{" in path:
                codes.append("404")
            if authenticated and method != "get":
                codes.append("409")
            for code in codes:
                op["responses"][code] = envelope_response(_DESCRIPTIONS[code])
            for code, resp in op["responses"].items():
                if code[0] in "45" and "content" not in resp:
                    op["responses"][code] = envelope_response(resp.get("description", "Error."))
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    components.pop("HTTPValidationError", None)
    components.pop("ValidationError", None)
    components.update(_components())
    return schema


def install_openapi(app: FastAPI) -> None:
    """Make `app.openapi()` return the post-processed document (cached, as FastAPI does)."""
    generated = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            app.openapi_schema = _post_process(app, generated())
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]


def build_openapi(app: FastAPI) -> dict[str, Any]:
    """The document, with no server and no database involved."""
    return app.openapi()
