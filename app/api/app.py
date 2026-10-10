"""The FastAPI app factory (architecture §3, §4).

Endpoints are plain `def` (run in FastAPI's threadpool) over synchronous
SQLAlchemy Core; each one that writes does so in one transaction.

Run with a single worker: the settle lock, the start sequence and the task
registry all assume one process (architecture §5.2, §5.7).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import Engine

from app.api.errors import install_error_handlers
from app.api.redaction import install_redaction
from app.api.routes import router
from app.utils import clock
from app.utils.config import Config


def create_app(
    config: Config,
    engine: Engine,
    *,
    owns_engine: bool = False,
) -> FastAPI:
    """Build the API. Time comes from `app.utils.clock` only (tests freeze it with `clock.frozen`)."""

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        install_redaction()
        try:
            yield
        finally:
            if owns_engine:
                engine.dispose()

    app = FastAPI(title="Ledgehog", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.config = config
    app.state.engine = engine
    app.state.instant = clock.now
    install_error_handlers(app)
    app.include_router(router)
    return app
