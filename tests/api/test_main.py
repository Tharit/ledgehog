from __future__ import annotations

import asyncio
import importlib
import sys

from fastapi import FastAPI

from app.main import LazyApp


def _lifespan(app: LazyApp):
    sent: list[dict] = []
    queue = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]

    async def receive():
        return queue.pop(0)

    async def send(message):
        sent.append(message)

    asyncio.run(app({"type": "lifespan"}, receive, send))
    return sent


def test_importing_main_needs_no_environment_or_database(monkeypatch):
    for var in list(__import__("os").environ):
        if var.startswith(("POSTGRES_", "USER_", "BASE_CURRENCY", "TIMEZONE")):
            monkeypatch.delenv(var)
    saved = sys.modules.pop("app.main")
    try:
        module = importlib.import_module("app.main")
        assert type(module.app).__name__ == "LazyApp"
    finally:
        sys.modules["app.main"] = saved


def test_failed_start_reports_startup_failed_without_building_the_app():
    def refuse() -> FastAPI:
        raise RuntimeError("BASE_CURRENCY mismatch")

    sent = _lifespan(LazyApp(refuse))
    assert sent == [{"type": "lifespan.startup.failed", "message": "RuntimeError: BASE_CURRENCY mismatch"}]


def test_successful_start_builds_once_and_delegates_lifespan():
    built = []

    def build() -> FastAPI:
        built.append(1)
        return FastAPI()

    sent = _lifespan(LazyApp(build))
    assert built == [1]
    assert [m["type"] for m in sent] == ["lifespan.startup.complete", "lifespan.shutdown.complete"]


def test_http_before_startup_is_refused():
    async def go():
        await LazyApp(FastAPI)({"type": "http"}, None, None)

    try:
        asyncio.run(go())
    except RuntimeError as exc:
        assert "not started" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
