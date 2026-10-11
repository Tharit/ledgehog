"""The shared API scaffolding: router discovery, domain error mapping, the importer registry."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routers as routers_pkg
from app.api import create_app
from app.api.errors import _DOMAIN_ERRORS, map_error


class _Boom(Exception):
    pass


class _SubBoom(_Boom):
    pass


@pytest.fixture(autouse=True)
def _clean_registry():
    before = dict(_DOMAIN_ERRORS)
    yield
    _DOMAIN_ERRORS.clear()
    _DOMAIN_ERRORS.update(before)


def test_a_router_module_in_the_package_is_included(tmp_path: Path, monkeypatch, api_config, api_engine):
    (tmp_path / "dummy_probe.py").write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter(prefix='/api/probe')\n"
        "@router.get('')\n"
        "def probe():\n"
        "    return {'ok': True}\n"
    )
    monkeypatch.setattr(routers_pkg, "__path__", [*routers_pkg.__path__, str(tmp_path)])
    monkeypatch.delitem(sys.modules, "app.api.routers.dummy_probe", raising=False)
    client = TestClient(create_app(api_config, api_engine))
    assert client.get("/api/probe").json() == {"ok": True}


def test_a_registered_domain_error_answers_with_its_status_and_code(api_config, api_engine):
    map_error(_Boom, 409, "boom_conflict")
    app = create_app(api_config, api_engine)

    @app.get("/api/_boom")
    def boom() -> None:
        raise _Boom("it went boom")

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/api/_boom")
    assert r.status_code == 409
    assert r.json() == {"error": {"code": "boom_conflict", "message": "it went boom", "details": None}}


def test_a_subclass_uses_the_nearest_registered_ancestor(api_config, api_engine):
    map_error(_Boom, 409, "boom_conflict")
    map_error(_SubBoom, 422, "sub_boom", details=lambda e: {"kind": type(e).__name__})
    app = create_app(api_config, api_engine)

    @app.get("/api/_sub")
    def sub() -> None:
        raise _SubBoom("narrow")

    r = TestClient(app, raise_server_exceptions=False).get("/api/_sub")
    assert r.status_code == 422
    assert r.json()["error"] == {"code": "sub_boom", "message": "narrow", "details": {"kind": "_SubBoom"}}


def test_an_unregistered_error_is_still_a_500_that_leaks_nothing(api_config, api_engine):
    app = create_app(api_config, api_engine)

    @app.get("/api/_unknown")
    def unknown() -> None:
        raise _Boom("secret-ish text")

    r = TestClient(app, raise_server_exceptions=False).get("/api/_unknown")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_error"
    assert "secret-ish" not in r.text


def test_the_importer_registry_is_available_to_routers(api_config, api_engine):
    sentinel = object()
    app = create_app(api_config, api_engine, importers={"csv": sentinel})  # type: ignore[dict-item]
    assert app.state.importers == {"csv": sentinel}
    assert create_app(api_config, api_engine).state.importers == {}
