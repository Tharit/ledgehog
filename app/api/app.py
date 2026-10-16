"""The FastAPI app factory (architecture §3, §4).

Endpoints are plain `def` (run in FastAPI's threadpool) over synchronous
SQLAlchemy Core; each one that writes does so in one transaction.

Run with a single worker: the settle lock, the start sequence and the task
registry all assume one process (architecture §5.2, §5.7).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import Engine

from app.api.errors import install_error_handlers
from app.api.openapi import install_openapi, operation_id
from app.api.redaction import install_redaction
from app.api.routers import include_routers
from app.api.routes import router
from app.core.plugins.importer import DocumentImporter, FileImporter
from app.utils import clock
from app.utils.config import Config


def create_app(
    config: Config,
    engine: Engine,
    *,
    owns_engine: bool = False,
    importers: Mapping[str, FileImporter | DocumentImporter] | None = None,
) -> FastAPI:
    """Build the API. Time comes from `app.utils.clock` only (tests freeze it with `clock.frozen`).

    `importers` maps an importer name (`importer_instance.importer`) to its implementation;
    the composition root supplies it, because the API never imports a concrete plugin.
    """

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        install_redaction()
        try:
            yield
        finally:
            if owns_engine:
                engine.dispose()

    # the schema is served in development only (EXPOSE_OPENAPI); the docs pages load scripts from a
    # CDN, which architecture §6.7 forbids, so they never exist
    app = FastAPI(
        title="Ledgehog",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if config.expose_openapi else None,
        generate_unique_id_function=operation_id,
    )
    app.state.config = config
    app.state.engine = engine
    app.state.instant = clock.now
    app.state.importers = dict(importers or {})
    app.include_router(router)
    include_routers(app)  # registers each module's domain error mappings as it is imported...
    install_error_handlers(app)  # ...so the handlers are installed after
    install_openapi(app)
    return app
