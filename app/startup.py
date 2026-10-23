"""The start sequence of architecture §5.7, one function per step.

Reads Config, so it lives beside the composition root rather than in `core`.
`start()` runs the steps in order and builds the app last: the app binds only
after every step succeeded. Nothing here logs a secret; users are named by login.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from fastapi import FastAPI
from sqlalchemy import Connection, Engine, text

from app.core.model.queue import ModelQueue, configure_model_queue
from app.core.model.worker import ModelWorker
from app.core.plugins.fetch import FetchImporter
from app.core.plugins.importer import FileImporter
from app.core.settle import SettleResult, settle
from app.core.tasks import TaskRegistry
from app.plugins.classifiers.llm import OpenAIModelClient
from app.utils import clock
from app.utils.auth import hash_password, revoke_sessions, verify_password
from app.utils.config import Config, UserConfig
from app.utils.db import migrate
from app.utils.db.engine import (
    document_window_ahead_setting,
    document_window_back_setting,
    make_engine,
    matching_window_setting,
    max_rate_age_setting,
)

log = logging.getLogger("ledgehog.startup")


class StartupError(Exception):
    """Start refused; the message says why and never contains a secret."""


class BaseCurrencyMismatch(StartupError):
    def __init__(self, configured: str, stored: str) -> None:
        super().__init__(
            f"BASE_CURRENCY is {configured} but the ledger was started with {stored}: "
            "rates are stored against the base currency, so it cannot change"
        )
        self.configured = configured
        self.stored = stored


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    """Logins touched by user reconcile (never passwords)."""

    created: tuple[str, ...] = ()
    renamed: tuple[str, ...] = ()
    rehashed: tuple[str, ...] = ()
    enabled: tuple[str, ...] = ()
    disabled: tuple[str, ...] = ()
    ignored: tuple[str, ...] = ()  # configured logins that name a provider's user


@dataclass(slots=True)
class StartedApp:
    config: Config
    engine: Engine
    app: FastAPI
    settle_result: SettleResult
    reconciled: ReconcileResult = field(default_factory=ReconcileResult)
    failed_runs: int = 0


def fail_interrupted_runs(conn: Connection) -> int:
    """Step 3: with one worker, a run still `running` was interrupted by a crash and wrote nothing."""
    return conn.execute(
        text(
            "UPDATE import_run SET status = 'failed', finished_at = :now, "
            "error_text = 'interrupted: the application stopped before the run finished', "
            "retryable = true "
            "WHERE status = 'running'"
        ),
        {"now": clock.now()},
    ).rowcount


def ensure_base_currency(conn: Connection, configured: str) -> None:
    """Step 4: write it on first start; afterwards it must match or start is refused."""
    conn.execute(
        text("INSERT INTO ledger_setting (base_currency) VALUES (:c) ON CONFLICT DO NOTHING"),
        {"c": configured},
    )
    stored = conn.execute(text("SELECT base_currency FROM ledger_setting")).scalar_one()
    if stored.strip() != configured:
        raise BaseCurrencyMismatch(configured, stored.strip())


def reconcile_users(conn: Connection, users: Sequence[UserConfig]) -> ReconcileResult:
    """Step 5: make `app_user` match the configured users, by login.

    Missing -> created. Display name changed -> updated. Configured password no
    longer verifies -> new hash and the user's sessions deleted. A user no longer
    configured is disabled, never deleted (runs and importer instances reference
    them), and loses their sessions. A disabled user whose login is configured
    again is re-enabled with the same id (so history stays theirs); the sessions
    were already deleted when they were disabled.

    Only the configuration's users (`source = 'config'`) are managed. A user the OIDC provider
    owns is left alone, never disabled for being absent from the environment; a configured login
    that names one is ignored and reported. A configured user without a password (OIDC enforced)
    has no hash: password sign-in cannot succeed for them.
    """
    created: list[str] = []
    renamed: list[str] = []
    rehashed: list[str] = []
    enabled: list[str] = []
    disabled: list[str] = []
    ignored: list[str] = []
    existing = {
        r.login: r
        for r in conn.execute(text("SELECT id, login, pw_hash, display_name, disabled, source FROM app_user"))
    }
    for cfg in users:
        row = existing.get(cfg.login)
        password = cfg.password.reveal() if cfg.password is not None else None
        if row is None:
            conn.execute(
                text("INSERT INTO app_user (login, pw_hash, display_name) VALUES (:l, :h, :n)"),
                {
                    "l": cfg.login,
                    "h": hash_password(password) if password is not None else None,
                    "n": cfg.name,
                },
            )
            created.append(cfg.login)
            continue
        if row.source != "config":
            ignored.append(cfg.login)
            continue
        if row.display_name != cfg.name:
            conn.execute(
                text("UPDATE app_user SET display_name = :n WHERE id = :i"), {"n": cfg.name, "i": row.id}
            )
            renamed.append(cfg.login)
        if password is None:
            if row.pw_hash is not None:  # a password the configuration no longer holds stops working
                conn.execute(text("UPDATE app_user SET pw_hash = NULL WHERE id = :i"), {"i": row.id})
                revoke_sessions(conn, row.id)
                rehashed.append(cfg.login)
        elif row.pw_hash is None or not verify_password(row.pw_hash, password):
            conn.execute(
                text("UPDATE app_user SET pw_hash = :h WHERE id = :i"),
                {"h": hash_password(password), "i": row.id},
            )
            revoke_sessions(conn, row.id)
            rehashed.append(cfg.login)
        if row.disabled:
            conn.execute(text("UPDATE app_user SET disabled = false WHERE id = :i"), {"i": row.id})
            enabled.append(cfg.login)
    configured = {u.login for u in users}
    for login, row in existing.items():
        if row.source == "config" and login not in configured and not row.disabled:
            conn.execute(text("UPDATE app_user SET disabled = true WHERE id = :i"), {"i": row.id})
            revoke_sessions(conn, row.id)
            disabled.append(login)
    return ReconcileResult(
        tuple(created), tuple(renamed), tuple(rehashed), tuple(enabled), tuple(disabled), tuple(ignored)
    )


def assert_pool_settings(engine: Engine, config: Config) -> None:
    """Step 6: `make_engine` sets `ledger.max_rate_age`, `ledger.matching_window_days` and
    `ledger.document_window_back_days` and `ledger.document_window_ahead_days` on every connection;
    check that it did."""
    expected = {
        "ledger.max_rate_age": max_rate_age_setting(config),
        "ledger.matching_window_days": matching_window_setting(config),
        "ledger.document_window_back_days": document_window_back_setting(config),
        "ledger.document_window_ahead_days": document_window_ahead_setting(config),
    }
    with engine.connect() as conn:
        for name, want in expected.items():
            actual = conn.execute(text("SELECT current_setting(:n, true)"), {"n": name}).scalar_one()
            if actual != want:
                raise StartupError(
                    f"{name} is {actual!r} on a pooled connection, expected {want!r}: "
                    "the engine was not built by make_engine for this configuration"
                )


def run_settle(engine: Engine) -> SettleResult:
    """Step 7: settle once; a failure is reported, never a reason to refuse to start."""
    result = settle(engine)
    if result.error is not None:
        log.error("settling failed at start (the app starts anyway): %s", result.error)
    else:
        log.info("settled at start: %d entries touched", len(result.touched_entry_ids))
    return result


def configure_model(config: Config, engine: Engine) -> ModelWorker | None:
    """Pass 3 (architecture §5.4): with `MODEL_ENDPOINT` and `MODEL_NAME` configured, the model's list for
    settling to fill and the worker that asks (started with the app). Without them nothing is listed and
    nothing runs; the pass-3 classifier is registered either way (`default_classifiers`): it asks nothing."""
    if config.model is None:
        configure_model_queue(None)
        return None
    key = config.model.api_key
    client = OpenAIModelClient(
        config.model.endpoint,
        config.model.name,
        key.reveal() if key else None,
        reasoning_effort=config.model.reasoning_effort,
    )
    queue = ModelQueue(client.fingerprint)
    configure_model_queue(queue)
    log.info("the model answers for categories in the background: %s", config.model.name)
    return ModelWorker(queue, client, engine)


def attach_model(app: FastAPI, worker: ModelWorker | None) -> None:
    """Keep the list on the app (`app.state.model`, read by the queue and the change poll) and run the
    worker for the app's lifespan."""
    app.state.model = worker.queue if worker is not None else None
    if worker is None:
        return
    inner = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(a: FastAPI) -> AsyncIterator[None]:
        async with inner(a):
            worker.start()
            try:
                yield
            finally:
                await worker.stop()

    app.router.lifespan_context = lifespan


def start(
    config: Config,
    engine: Engine | None = None,
    *,
    importers: Mapping[str, FileImporter | FetchImporter] | None = None,
) -> StartedApp:
    """Run the start sequence (1: `config` is already validated) and build the app.

    With no `engine` one is made and owned by the app (disposed at shutdown). `importers`
    is the plugin registry the composition root supplies (name -> implementation).
    """
    from app.api import create_app  # step 8 builds the API; imported late to keep this module light

    log.info("starting: migrating the schema")
    migrate.upgrade(config)  # 2
    owns_engine = engine is None
    engine = engine or make_engine(config)
    try:
        with engine.begin() as conn:  # 3, 4, 5: one transaction, so a refusal leaves nothing half-done
            failed = fail_interrupted_runs(conn)
            ensure_base_currency(conn, config.base_currency)
            reconciled = reconcile_users(conn, config.users)
        if failed:
            log.warning("marked %d interrupted import run(s) failed", failed)
        for verb, logins in (
            ("created", reconciled.created),
            ("renamed", reconciled.renamed),
            ("password changed", reconciled.rehashed),
            ("re-enabled", reconciled.enabled),
            ("disabled", reconciled.disabled),
            ("ignored (the OIDC provider's, not the configuration's)", reconciled.ignored),
        ):
            if logins:
                log.info("users %s: %s", verb, ", ".join(logins))
        assert_pool_settings(engine, config)  # 6
        worker = configure_model(config, engine)  # before 7: the settle lists what the model is to look at
        result = run_settle(engine)  # 7
        # 8: the one task registry of the process (architecture §5.3) is created here, with the app
        app = create_app(config, engine, owns_engine=owns_engine, importers=importers, tasks=TaskRegistry())
        attach_model(app, worker)
    except BaseException:
        if owns_engine:
            engine.dispose()
        raise
    return StartedApp(config, engine, app, result, reconciled, failed)
