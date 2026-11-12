"""The OpenAPI document: served in development only, with stable names and the real error envelope."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.api.openapi import api_routes, build_openapi
from app.utils.config import Config
from app.utils.db.engine import make_engine
from app.utils.version import app_version

ENV = {
    "POSTGRES_HOST": "127.0.0.1",
    "POSTGRES_PORT": "1",
    "POSTGRES_DB": "nodb",
    "POSTGRES_USER": "nobody",
    "POSTGRES_PASSWORD": "unused-pw",
    "BASE_CURRENCY": "EUR",
    "TIMEZONE": "UTC",
}
METHODS = ("get", "post", "put", "patch", "delete")


@pytest.fixture
def config() -> Config:
    return Config.from_env(ENV)


@pytest.fixture
def app(config):  # no database is ever contacted: the engine is lazy
    return create_app(replace(config, expose_openapi=True), make_engine(config))


@pytest.fixture
def schema(app) -> dict:
    return build_openapi(app)


def operations(schema: dict):
    for path, item in schema["paths"].items():
        for method in METHODS:
            if method in item:
                yield path, method, item[method]


def test_off_by_default_answers_the_404_envelope(config):
    client = TestClient(create_app(config, make_engine(config)))
    r = client.get("/api/openapi.json")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_on_serves_the_schema(app):
    r = TestClient(app).get("/api/openapi.json")
    assert r.status_code == 200
    body = r.json()
    assert body["openapi"].startswith("3.")
    assert "/api/session" in body["paths"]


@pytest.mark.parametrize("flag", [False, True])
@pytest.mark.parametrize("path", ["/docs", "/redoc", "/api/docs", "/api/redoc"])
def test_docs_pages_never_exist(config, flag, path):
    app = create_app(replace(config, expose_openapi=flag), make_engine(config))
    assert TestClient(app).get(path).status_code == 404


def test_operation_ids_are_the_unique_handler_names(app, schema):
    routes = {(r.path_format, m.lower()): r for r in api_routes(app) for m in r.methods or ()}
    ids = []
    for path, method, op in operations(schema):
        assert op["operationId"] == routes[(path, method)].endpoint.__name__
        ids.append(op["operationId"])
    assert ids and len(ids) == len(set(ids))
    assert "list_ledger_accounts" in ids


def test_hidden_aliases_stay_out(schema):
    for path in ("/api/login", "/api/logout", "/api/me"):
        assert path not in schema["paths"]


def test_the_envelope_replaces_the_validation_schemas(schema):
    text = json.dumps(schema)
    assert "HTTPValidationError" not in text
    assert "ValidationError" not in text
    env = schema["components"]["schemas"]["ErrorEnvelope"]
    assert set(env["properties"]) == {"error"}
    body = schema["components"]["schemas"]["ErrorBody"]
    assert set(body["properties"]) == {"code", "message", "details"}
    assert set(body["required"]) == {"code", "message", "details"}


def envelope_ref(response: dict) -> str:
    return response["content"]["application/json"]["schema"]["$ref"]


def test_every_operation_lists_the_envelope_for_its_4xx(schema):
    for path, method, op in operations(schema):
        for status, resp in op["responses"].items():
            if status.startswith(("4", "5")):
                assert envelope_ref(resp) == "#/components/schemas/ErrorEnvelope", (path, method, status)
        # authenticated routes: 401 and 422 at minimum (the config is read before there is a session)
        if (path, method) not in {
            ("/api/session", "post"),
            ("/api/session", "delete"),
            ("/api/config", "get"),
        }:
            assert "401" in op["responses"], (path, method)
            assert "422" in op["responses"], (path, method)
    login = schema["paths"]["/api/session"]["post"]["responses"]
    assert {"401", "422"} <= set(login)
    assert "401" not in schema["paths"]["/api/session"]["delete"]["responses"]


def test_path_parameters_document_404(schema):
    for path, method, op in operations(schema):
        if "{" in path:
            assert "404" in op["responses"], (path, method)


def test_upload_route_is_documented_as_multipart(schema):
    op = schema["paths"]["/api/importers/instances/{instance_id}/upload"]["post"]
    body = op["requestBody"]
    assert body["required"] is True
    form = body["content"]["multipart/form-data"]["schema"]
    assert form["properties"]["file"] == {"type": "string", "format": "binary"}
    assert form["properties"]["account_id"]["type"] == "integer"
    assert form["properties"]["dry_run"] == {"type": "boolean", "default": False}
    assert set(form["required"]) == {"file", "account_id"}
    assert {"200", "401", "404", "409", "413", "422", "502"} <= set(op["responses"])
    assert op["responses"]["200"]["content"]["application/json"]["schema"]["type"] == "object"
    assert "{instance_id}" in "/api/importers/instances/{instance_id}/upload"
    assert any(p["name"] == "instance_id" for p in op["parameters"])


def test_build_openapi_is_cached_and_identical_to_the_served_document(app):
    assert build_openapi(app) is build_openapi(app)
    assert TestClient(app).get("/api/openapi.json").json() == json.loads(json.dumps(build_openapi(app)))


def test_the_schema_states_the_package_version(schema):
    assert schema["info"]["version"] == app_version()
