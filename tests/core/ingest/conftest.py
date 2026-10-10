"""Fixtures and builders for the ingest run tests. Real commits, so a clone DB per test."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

import pytest
from sqlalchemy import Engine, text

from app.core.ingest.run import RunResult, ingest_delivery, start_run
from app.core.plugins.importer import IncomingRow
from tests.core.ingest.dup_helpers import Ledger
from tests.invariants.helpers import make_run

DAY = date(2026, 3, 10)
THROUGH = date(2026, 3, 14)


def row(amount: int = -500, day: date = DAY, **kw: Any) -> IncomingRow:
    base: dict[str, Any] = {
        "amount_minor": amount,
        "currency": "EUR",
        "booked_on": day,
        "source_format": "csv:test",
        "raw": {"n": 1},
    }
    base.update(kw)
    return IncomingRow(**base)


@dataclass
class Env:
    engine: Engine
    account: int

    def deliver(
        self,
        rows: list[IncomingRow],
        *,
        importer: str = "csv",
        account: int | None = None,
        covered_through: date | None = THROUGH,
        filtered: int = 0,
    ) -> RunResult:
        acct = self.account if account is None else account
        run_id = start_run(self.engine, acct, "transactions", importer=importer)
        return ingest_delivery(self.engine, run_id, rows, covered_through=covered_through, filtered=filtered)

    def q(self, sql: str, **params: Any) -> list[Any]:
        with self.engine.connect() as conn:
            return list(conn.execute(text(sql), params).all())

    def count(self, table: str) -> int:
        return int(self.q(f"SELECT count(*) FROM {table}")[0][0])  # noqa: S608

    def run_row(self, run_id: int) -> Any:
        return self.q("SELECT * FROM import_run WHERE id = :i", i=run_id)[0]


@pytest.fixture
def env(isolated_engine: Engine, make_account: Callable[..., int]) -> Env:
    with isolated_engine.begin() as conn:
        account = make_account(conn)
    return Env(isolated_engine, account)


@pytest.fixture
def ledger(isolated_engine: Engine, make_account: Callable[..., int]) -> Ledger:
    """Checking (unsynced, with one ok run) and Savings, committed, for the duplicate tests."""
    with isolated_engine.begin() as conn:
        checking = make_account(conn, name="Checking")
        savings = make_account(conn, name="Savings", kind="savings")
        run = make_run(conn, checking)
    return Ledger(isolated_engine, checking, savings, run)
