"""Seeding and assertions shared by the accounts, balance-record and maintenance API tests."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.core.accounts import create_account
from app.core.balance.records import set_manual_record
from tests.invariants.helpers import make_entry, make_run, make_source

DAY = date(2026, 3, 1)


def seed_account(engine: Engine, name: str = "Giro", **kw: Any) -> int:
    kw.setdefault("kind", "checking")
    kw.setdefault("currency", "EUR")
    return create_account(engine, name=name, **kw)


def seed_manual(engine: Engine, account_id: int, on: date = DAY, balance: int = 10_000) -> int:
    return set_manual_record(engine, account_id, on, balance).record_id


def seed_difference(engine: Engine, account_id: int) -> int:
    """A reported record that disagrees with the ledger: a manual anchor, a movement, a reported balance.

    Returns the reported record's id.
    """
    from app.core.balance.derived import recompute_derived

    seed_manual(engine, account_id, date(2026, 1, 31), 10_000)
    with engine.begin() as conn:
        run = make_run(conn, account_id, covered_through=date(2026, 3, 1))
        make_entry(
            conn, make_source(conn, account_id, run_id=run, amount=-1_000, booked_on=date(2026, 2, 10))
        )
        record = int(
            conn.execute(
                text(
                    "INSERT INTO balance_record"
                    " (account_id, kind, import_run_id, balance, currency, balance_on)"
                    " VALUES (:a, 'reported', :r, 8_000, 'EUR', DATE '2026-03-01') RETURNING id"
                ),
                {"a": account_id, "r": run},
            ).scalar_one()
        )
        recompute_derived(conn, account_id)
    return record


def q(engine: Engine, sql: str, **params: Any) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(text(sql), params).all())


def assert_envelope(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    return error  # type: ignore[no-any-return]


def assert_checks_ok(client: TestClient) -> None:
    body = client.get("/api/maintenance/check").json()
    assert body["ok"] is True, body
