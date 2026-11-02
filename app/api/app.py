"""The FastAPI app factory (architecture §3, §4).

Endpoints are plain `def` (run in FastAPI's threadpool) over synchronous
SQLAlchemy Core; each one that writes does so in one transaction.

Run with a single worker: the settle lock, the start sequence and the task
registry all assume one process (architecture §5.2, §5.7).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import Engine

from app.api.errors import install_error_handlers
from app.api.frontend import Frontend, SecurityHeaders
from app.api.openapi import install_openapi, operation_id
from app.api.redaction import install_redaction
from app.api.routers import include_routers
from app.api.routers.changes import HEADER as CHANGES_HEADER
from app.api.routers.changes import values_of
from app.api.routes import router
from app.core.plugins.fetch import FetchImporter
from app.core.plugins.importer import FileImporter
from app.core.tasks import TaskRegistry
from app.core.tasks.changes import ChangeRegister
from app.utils import clock
from app.utils.auth import OidcFlow
from app.utils.config import Config
from app.utils.db.changes import install_change_hooks

log = logging.getLogger(__name__)

_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def create_app(
    config: Config,
    engine: Engine,
    *,
    owns_engine: bool = False,
    importers: Mapping[str, FileImporter | FetchImporter] | None = None,
    tasks: TaskRegistry | None = None,
    changes: ChangeRegister | None = None,
    oidc_transport: httpx2.BaseTransport | None = None,
    frontend: Path | None = None,
) -> FastAPI:
    """Build the API. Time comes from `app.utils.clock` only (tests freeze it with `clock.frozen`).

    `importers` maps an importer name (`importer_instance.importer`) to its implementation;
    the composition root supplies it, because the API never imports a concrete plugin. `tasks` is
    the one task registry of the process (architecture §5.3), created by the composition root.
    `frontend` is the built SPA directory; without an `index.html` in it only the API is served, and
    an `index.html` that cannot be served under the policy refuses the start (architecture §6.7).
    """

    served = Frontend.load(frontend)  # reads index.html once; may refuse the start

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.loop = asyncio.get_running_loop()  # what a start from the threadpool launches its task on
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
    # the provider is contacted lazily, at the first sign-in: the app starts with it down
    app.state.oidc = OidcFlow(config.oidc, oidc_transport) if config.oidc is not None else None
    app.state.importers = dict(importers or {})
    app.state.tasks = tasks if tasks is not None else TaskRegistry()
    app.state.loop = None  # set when the lifespan starts
    app.state.changes = changes if changes is not None else ChangeRegister()
    # the locks note what a transaction touches; the register moves when it commits (architecture §5.2)
    install_change_hooks(engine, app.state.changes.bump)

    @app.middleware("http")
    async def changes_header(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Every write's response carries the change values after it (architecture §4.2), read once the
        handler, and with it the settle, has finished. Reads do not carry them."""
        response = await call_next(request)
        if request.method not in _READ_METHODS:
            try:
                values = await run_in_threadpool(values_of, app.state.changes, engine)
                response.headers[CHANGES_HEADER] = values.model_dump_json()
            except Exception:
                log.exception("could not read the change values for a response header")
        return response

    app.include_router(router)
    include_routers(app)  # registers each module's domain error mappings as it is imported...
    install_error_handlers(app)  # ...so the handlers are installed after
    install_openapi(app)
    served.mount(app)
    app.add_middleware(SecurityHeaders, policy=served.policy)
    return app
