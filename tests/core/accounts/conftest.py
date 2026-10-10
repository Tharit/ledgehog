"""Fixtures for the account operation tests: a committed clone DB per test."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import Engine, text

from app.core.settle.settle import SettleResult


@dataclass
class Db:
    engine: Engine

    def q(self, sql: str, **params: Any) -> list[Any]:
        with self.engine.connect() as conn:
            return list(conn.execute(text(sql), params).all())

    def one(self, sql: str, **params: Any) -> Any:
        return self.q(sql, **params)[0]

    def run(self, sql: str, **params: Any) -> None:
        with self.engine.begin() as conn:
            conn.execute(text(sql), params)

    def assert_checks_clean(self) -> None:
        views = [
            r[0]
            for r in self.q(
                "SELECT table_name FROM information_schema.views WHERE table_name LIKE 'v_check_%'"
            )
        ]
        assert views, "no integrity views found"
        for v in views:
            bad = self.q(f"SELECT * FROM {v}")  # noqa: S608
            assert not bad, f"{v} reports {bad}"


@pytest.fixture
def db(isolated_engine: Engine) -> Db:
    return Db(isolated_engine)


@pytest.fixture
def settle_spy(monkeypatch: pytest.MonkeyPatch) -> Callable[[Any], list[int]]:
    """Replace `module.settle` with a counter that returns an empty result."""

    def install(module: Any) -> list[int]:
        calls: list[int] = []
        monkeypatch.setattr(module, "settle", lambda engine: calls.append(1) or SettleResult())
        return calls

    return install
