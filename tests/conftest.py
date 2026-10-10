"""Test harness (architecture §8, §9).

Real PostgreSQL only. The connection settings come from the POSTGRES_*
environment (`. ./settings.env`); the database name never does: every run makes
its own `test_<uuid>` database, cloned from a template built once from the
migration chain, and drops it in a finalizer that also runs on failure.

Fixtures
  admin_cfg      Config pointing at the maintenance database (CREATE/DROP DATABASE)
  template_db    name of the template database for the current migration chain
  session_db     a `test_<uuid>` database shared by the session (rollback-isolated tests)
  db_conn        a Connection in an outer transaction that is rolled back after the test
  isolated_db    a fresh per-test `test_<uuid>` clone, for tests that must commit
  clock          the clock frozen at CLOCK_START
  make_account   insert an account, returns its id
"""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Connection, Engine, text

from app.utils import clock as clock_module
from app.utils.config import Config
from app.utils.db import admin

ROOT = Path(__file__).resolve().parent.parent
CLOCK_START = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
_created: set[str] = set()


def _test_config(database: str) -> Config:
    env = dict(os.environ)
    env.setdefault("BASE_CURRENCY", "EUR")
    env.setdefault("TIMEZONE", "UTC")
    env["POSTGRES_DB"] = database
    for needed in ("POSTGRES_USER", "POSTGRES_PASSWORD"):
        if needed not in env and f"{needed}_FILE" not in env:
            pytest.fail(
                f"{needed} is not set: run the DB tests with the settings sourced "
                "(`. ./settings.env && uv run pytest`)",
                pytrace=False,
            )
    return Config.from_env(env)


@pytest.fixture(scope="session")
def admin_cfg() -> Config:
    return _test_config(os.environ.get("POSTGRES_ADMIN_DB", "postgres"))


def _new_database(cfg: Config, template: str) -> str:
    name = f"test_{uuid.uuid4().hex}"
    _created.add(name)  # registered first: a crash mid-create is still cleaned up
    admin.create_database(cfg, name, template=template)
    return name


def _drop(cfg: Config, name: str) -> None:
    admin.drop_database(cfg, name)
    _created.discard(name)


def _migration_hash() -> str:
    """Identifies the migration chain, so the template is rebuilt only when it changes."""
    digest = hashlib.sha256()
    for path in sorted((ROOT / "migrations").rglob("*.py")):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


@pytest.fixture(scope="session")
def template_db(admin_cfg: Config) -> str:
    """The template database for this migration chain; built once, reused across runs.

    Built under a temporary name and renamed into place, so a crashed build is never
    mistaken for a usable template; an advisory lock serialises concurrent sessions.
    Named `tpl_<hash>`, not `test_<uuid>`: it is meant to outlive a run (the sweeper
    removes stale ones).
    """
    name = f"tpl_{_migration_hash()}"
    with admin.connect(admin_cfg) as lock_conn:
        lock_conn.execute("SELECT pg_advisory_lock(hashtext('ledgehog-template'))")
        if not admin.database_exists(admin_cfg, name):
            building = f"tpl_build_{uuid.uuid4().hex}"
            _created.add(building)
            try:
                admin.create_database(admin_cfg, building)
                from app.utils.db import migrate

                migrate.upgrade(admin_cfg.with_database(building))
                admin.rename_database(admin_cfg, building, name)
            finally:
                admin.drop_database(admin_cfg, building)
                _created.discard(building)
    return name


@pytest.fixture(scope="session")
def session_db(admin_cfg: Config, template_db: str) -> Iterator[Config]:
    name = _new_database(admin_cfg, template_db)
    try:
        yield admin_cfg.with_database(name)
    finally:
        _drop(admin_cfg, name)


@pytest.fixture(scope="session")
def session_engine(session_db: Config) -> Iterator[Engine]:
    from app.utils.db.engine import make_engine

    engine = make_engine(session_db)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_conn(session_engine: Engine) -> Iterator[Connection]:
    """A connection inside one outer transaction, rolled back after the test.

    Code under test must not commit or roll back the connection itself; use
    `begin_nested()` for savepoints and `SET CONSTRAINTS ALL IMMEDIATE` to fire
    deferred triggers inside the test. Tests that need a real commit (locks,
    deferred triggers at commit, threads) use `isolated_db`.
    """
    with session_engine.connect() as conn:
        outer = conn.begin()
        try:
            yield conn
        finally:
            outer.rollback()


@pytest.fixture
def isolated_db(admin_cfg: Config, template_db: str) -> Iterator[Config]:
    name = _new_database(admin_cfg, template_db)
    try:
        yield admin_cfg.with_database(name)
    finally:
        _drop(admin_cfg, name)


@pytest.fixture
def isolated_engine(isolated_db: Config) -> Iterator[Engine]:
    from app.utils.db.engine import make_engine

    engine = make_engine(isolated_db)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def clock() -> Iterator[clock_module.FrozenClock]:
    with clock_module.frozen(CLOCK_START) as c:
        yield c


@pytest.fixture
def make_account() -> Callable[..., int]:
    def make(
        conn: Connection,
        *,
        name: str = "Checking",
        kind: str = "checking",
        currency: str = "EUR",
        external_ref: str | None = None,
    ) -> int:
        return conn.execute(
            text(
                "INSERT INTO account (name, kind, currency, external_ref) "
                "VALUES (:name, :kind, :currency, :external_ref) RETURNING id"
            ),
            {"name": name, "kind": kind, "currency": currency, "external_ref": external_ref},
        ).scalar_one()

    return make


def pytest_unconfigure(config: pytest.Config) -> None:
    """Backstop: drop anything this process created that a finalizer missed."""
    if not _created:
        return
    cfg = _test_config(os.environ.get("POSTGRES_ADMIN_DB", "postgres"))
    for name in sorted(_created):
        admin.drop_database(cfg, name)
    _created.clear()
