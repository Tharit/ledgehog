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


@dataclass(frozen=True)
class Backfill:
    engine: Engine
    summary: BackfillSummary
    build_seconds: float


@pytest.fixture(scope="session")
def backfill(admin_cfg: Config, template_db: str) -> Iterator[Backfill]:
    from app.utils.db.engine import make_engine

    name = _new_database(admin_cfg, template_db)
    engine = make_engine(admin_cfg.with_database(name))
    try:
        started = time.perf_counter()
        summary = build_backfill(engine)
        yield Backfill(engine, summary, time.perf_counter() - started)
    finally:
        engine.dispose()
        _drop(admin_cfg, name)
