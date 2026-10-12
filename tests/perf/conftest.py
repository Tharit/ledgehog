"""Session-scoped backfill database for the perf tests (one build per session)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine

from app.utils.config import Config
from tests.conftest import _drop, _new_database
from tests.fixtures.backfill import BackfillSummary, build_backfill


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "perf: timing-budget tests on the backfill fixture")


@pytest.fixture(scope="session", autouse=True)
def _session_classifiers() -> Iterator[None]:
    """The session-scoped fixtures below settle, before the per-test autouse fixture has run."""
    from app.core.resolution.registry import (
        configure_classifiers,
        configure_rule_tools,
        unconfigure_classifiers,
        unconfigure_rule_tools,
    )
    from app.plugins.classifiers import default_classifiers, default_rule_tools

    configure_classifiers(default_classifiers)
    configure_rule_tools(default_rule_tools())
    yield
    unconfigure_classifiers()
    unconfigure_rule_tools()


@dataclass(frozen=True)
class Backfill:
    engine: Engine
    summary: BackfillSummary
    build_seconds: float


def _backfill(admin_cfg: Config, template_db: str, **kwargs: float) -> Iterator[Backfill]:
    from app.utils.db.engine import make_engine

    name = _new_database(admin_cfg, template_db)
    engine = make_engine(admin_cfg.with_database(name))
    try:
        started = time.perf_counter()
        summary = build_backfill(engine, **kwargs)  # type: ignore[arg-type]
        yield Backfill(engine, summary, time.perf_counter() - started)
    finally:
        engine.dispose()
        _drop(admin_cfg, name)


@pytest.fixture(scope="session")
def backfill(admin_cfg: Config, template_db: str) -> Iterator[Backfill]:
    """8,000 unconfirmed entries, nothing classified: no voters for history, no rules."""
    yield from _backfill(admin_cfg, template_db)


@pytest.fixture(scope="session")
def backfill_settled(admin_cfg: Config, template_db: str) -> Iterator[Backfill]:
    """The same ledger with ~70% confirmed entries (history voters) and rules for a few merchants."""
    yield from _backfill(admin_cfg, template_db, confirmed_share=0.7)
