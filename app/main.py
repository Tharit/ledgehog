"""Composition root: builds Config from the environment, runs the start sequence, serves the API.

    uvicorn app.main:app            # exactly ONE worker, never --workers N

One worker is load-bearing: the settle lock, the start sequence (which fails
interrupted runs) and the task registry assume a single process (architecture
§5.2, §5.7).

Importing this module touches neither the environment nor the database. The
start sequence runs when the server delivers the ASGI lifespan startup, so the
app binds only after it succeeded; a failed start (bad variable, base currency
mismatch) ends the server with the reason in its output.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, MutableMapping
from pathlib import Path
from typing import Any

from anyio import to_thread
from fastapi import FastAPI

from app.core.importers.providers import register_document_importers
from app.core.plugins.fetch import FetchImporter
from app.core.plugins.importer import FileImporter
from app.core.resolution.registry import configure_classifiers, configure_rule_tools
from app.plugins.classifiers import default_classifiers, default_rule_tools
from app.plugins.importers.camt import CamtImporter
from app.plugins.importers.csv import CsvImporter
from app.plugins.importers.email.factory import email_importer
from app.plugins.importers.fints import FintsImporter
from app.plugins.importers.testing import TestDocumentImporter, TestFetchImporter
from app.startup import start
from app.utils.config import Config
from app.utils.version import app_version

log = logging.getLogger("ledgehog")

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "build"  # architecture §6.7


def configure_logging() -> None:
    """Show the application's INFO lines (`ledgehog.*`) on stderr, in uvicorn's console style.

    Idempotent. Touches neither the root logger nor uvicorn's loggers."""
    if any(getattr(h, "_ledgehog", False) for h in log.handlers):
        return
    handler = logging.StreamHandler()  # stderr
    handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s: %(message)s"))
    handler._ledgehog = True  # type: ignore[attr-defined]
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False


Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]


def register_importers(config: Config) -> dict[str, FileImporter | FetchImporter]:
    """The importers this deployment offers (name -> implementation); also installs the document
    providers of those that deliver documents, the one source of the providers a payee can name.
    The deterministic test importers (`testdocs`, and the scripted `testfetch`) are registered only
    behind `ENABLE_TEST_IMPORTERS`."""
    importers: dict[str, FileImporter | FetchImporter] = {
        "csv": CsvImporter(),
        "camt": CamtImporter(),
        # always registered, so the catalog and the setup form exist; without the DK product
        # registration id `open` raises `NotRegistered` before it asks for anything (spec §7.1)
        "fints": FintsImporter(config.fints_product_id, app_version()),
    }
    if config.model is not None:  # it reads documents with the model (spec/plugins/importers/email.md §1)
        importers["email"] = email_importer(config.model, config.vision_model)
    if config.enable_test_importers:
        importers["testdocs"] = TestDocumentImporter()
        importers["testfetch"] = TestFetchImporter()
    register_document_importers(importers)
    return importers


def build() -> FastAPI:
    """Read the configuration, run the start sequence and return the API.

    This is where concrete plugins are registered: core and the API only see the protocols.
    """
    configure_logging()
    configure_classifiers(default_classifiers)  # before start: the start sequence settles
    configure_rule_tools(default_rule_tools())
    config = Config.from_env()
    importers = register_importers(config)  # before start: it settles
    return start(config, importers=importers, frontend=FRONTEND).app


class LazyApp:
    """An ASGI app that builds the real one at lifespan startup."""

    def __init__(self, factory: Callable[[], FastAPI]) -> None:
        self._factory = factory
        self._inner: FastAPI | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._inner is None:
            if scope["type"] != "lifespan":
                raise RuntimeError("the application has not started (lifespan startup did not run)")
            try:
                self._inner = await to_thread.run_sync(self._factory)
            except Exception as exc:
                log.error("start refused: %s: %s", type(exc).__name__, exc)
                await receive()  # lifespan.startup
                await send({"type": "lifespan.startup.failed", "message": f"{type(exc).__name__}: {exc}"})
                return
        await self._inner(scope, receive, send)


app = LazyApp(build)
