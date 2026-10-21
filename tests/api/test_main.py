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


def test_the_test_importer_registers_only_behind_the_flag_and_fills_the_provider_registry():
    from dataclasses import replace

    from app.core.importers.providers import (
        document_providers,
        registered_providers,
        reset_document_providers,
    )
    from app.main import register_importers
    from app.plugins.importers.testdocs import TestDocumentImporter
    from app.utils.config import Config

    base = Config.from_env(
        {
            "POSTGRES_DB": "x",
            "POSTGRES_USER": "u",
            "POSTGRES_PASSWORD": "p",
            "BASE_CURRENCY": "EUR",
            "TIMEZONE": "Europe/Berlin",
        }
    )
    reset_document_providers()
    try:
        assert set(register_importers(base)) == {"csv", "fints"}
        assert document_providers() == {} and registered_providers() == []
        on = register_importers(replace(base, enable_test_importers=True))
        assert set(on) == {"csv", "fints", "testdocs", "testfetch"}
        assert isinstance(on["testdocs"], TestDocumentImporter)
        assert dict(document_providers()) == {
            "testdocs": TestDocumentImporter.providers,
            "testfetch": TestDocumentImporter.providers,  # it emits documents too
        }
        assert registered_providers() == ["amazon", "paypal"]
        register_importers(base)  # a later process configuration replaces it
        assert registered_providers() == []
    finally:
        reset_document_providers()


def test_configure_logging_shows_info_once():
    import io
    import logging

    from app import main

    ledger = logging.getLogger("ledgehog")
    saved = (list(ledger.handlers), ledger.level, ledger.propagate)
    ledger.handlers.clear()
    try:
        main.configure_logging()
        main.configure_logging()
        assert len(ledger.handlers) == 1
        assert ledger.propagate is False
        assert logging.getLogger("ledgehog.startup").isEnabledFor(logging.INFO)
        buf = io.StringIO()
        ledger.handlers[0].setStream(buf)  # type: ignore[attr-defined]
        logging.getLogger("ledgehog.startup").info("hello")
        assert buf.getvalue() == "INFO:     ledgehog.startup: hello\n"
    finally:
        ledger.handlers[:] = saved[0]
        ledger.setLevel(saved[1])
        ledger.propagate = saved[2]
