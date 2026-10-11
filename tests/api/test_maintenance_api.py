"""The maintenance endpoints: the integrity check and a manual settle (architecture §4.1)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.api.routers import maintenance
from app.core.settle.settle import SettleResult
from tests.api.accounts_helpers import assert_envelope, seed_account
from tests.api.conftest import login
from tests.invariants.helpers import make_source, triggers_disabled


def test_check_is_ok_on_a_clean_ledger_and_lists_every_view(client: TestClient, api_engine: Engine) -> None:
    login(client)
    r = client.get("/api/maintenance/check")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    with api_engine.connect() as conn:
        views = {
            x[0]
            for x in conn.execute(text("SELECT viewname FROM pg_views WHERE viewname LIKE 'v\\_check\\_%'"))
        }
    assert set(body["checks"]) == views and len(views) >= 10
    assert all(v == {"rows": [], "truncated": False} for v in body["checks"].values())


def test_check_reports_a_seeded_violation_under_its_view(client: TestClient, api_engine: Engine) -> None:
    login(client)
    account = seed_account(api_engine)
    with api_engine.begin() as conn, triggers_disabled(conn, "source_transaction", "ledger_entry"):
        make_source(conn, account, amount=-100)
    body = client.get("/api/maintenance/check").json()
    assert body["ok"] is False
    check = body["checks"]["v_check_split_sum"]
    assert len(check["rows"]) == 1 and check["truncated"] is False
    assert check["rows"][0]["source_amount"] == -100


def test_settle_returns_the_settle_result(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    login(client)
    calls: list[object] = []
    monkeypatch.setattr(
        maintenance, "settle", lambda engine: calls.append(engine) or SettleResult((3, 5), None)
    )
    r = client.post("/api/maintenance/settle")
    assert r.status_code == 200
    assert r.json() == {"touched_entry_ids": [3, 5], "error": None}
    assert len(calls) == 1


def test_a_settle_failure_is_a_notice_not_an_http_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    login(client)
    monkeypatch.setattr(maintenance, "settle", lambda engine: SettleResult((), "settling failed"))
    r = client.post("/api/maintenance/settle")
    assert r.status_code == 200 and r.json() == {"touched_entry_ids": [], "error": "settling failed"}


@pytest.mark.parametrize(
    ("method", "path"), [("get", "/api/maintenance/check"), ("post", "/api/maintenance/settle")]
)
def test_maintenance_requires_a_session(client: TestClient, method: str, path: str) -> None:
    assert_envelope(getattr(client, method)(path), 401, "unauthenticated")
