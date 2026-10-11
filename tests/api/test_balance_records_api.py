"""The balance record endpoints (architecture §4.1, spec §3.10, §3.11)."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.core.balance import records as core_records
from app.core.settle.settle import SettleResult
from tests.api.accounts_helpers import (
    assert_checks_ok,
    assert_envelope,
    q,
    seed_account,
    seed_difference,
    seed_manual,
)
from tests.api.conftest import login


@pytest.fixture
def anna(client: TestClient) -> TestClient:
    login(client)
    return client


def money(amount, currency: str = "EUR") -> dict:
    return {"amount": amount, "currency": currency}


def derived(engine: Engine, aid: int) -> list[tuple[str, date, int]]:
    return [
        (r.type, r.booked_on, r.amount)
        for r in q(
            engine,
            "SELECT type, booked_on, amount FROM ledger_entry "
            "WHERE account_id = :a AND balance_record_id IS NOT NULL ORDER BY booked_on, id",
            a=aid,
        )
    ]


# ---- set (upsert) ---------------------------------------------------------------------------


def test_set_creates_a_manual_record_with_201_and_refreshed_account_facts(
    anna: TestClient, api_engine: Engine
) -> None:
    aid = seed_account(api_engine)
    r = anna.post(
        f"/api/ledger/accounts/{aid}/balance-records",
        json={"balance_on": "2026-03-01", "balance": money(12_345)},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["record"] == {
        "id": body["record"]["id"],
        "account_id": aid,
        "kind": "manual",
        "balance_on": "2026-03-01",
        "balance": money(12_345),
    }
    assert body["account"]["id"] == aid and body["account"]["anchored"] is True
    assert body["settle"] == {"touched_entry_ids": [], "error": None}
    assert derived(api_engine, aid) == [("opening", date(2026, 2, 28), 12_345)]
    assert_checks_ok(anna)


def test_the_same_date_edits_the_record_and_answers_200(anna: TestClient, api_engine: Engine) -> None:
    aid = seed_account(api_engine)
    url = f"/api/ledger/accounts/{aid}/balance-records"
    first = anna.post(url, json={"balance_on": "2026-03-01", "balance": money(100)})
    second = anna.post(url, json={"balance_on": "2026-03-01", "balance": money(250)})
    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json()["record"]["id"] == first.json()["record"]["id"]
    assert second.json()["record"]["balance"] == money(250)
    assert len(q(api_engine, "SELECT 1 FROM balance_record")) == 1


def test_set_refusals(anna: TestClient, api_engine: Engine) -> None:
    aid = seed_account(api_engine)
    ok = {"balance_on": "2026-03-01", "balance": money(1)}
    assert_envelope(anna.post("/api/ledger/accounts/9999/balance-records", json=ok), 404, "not_found")
    e = assert_envelope(
        anna.post(f"/api/ledger/accounts/{aid}/balance-records", json={**ok, "balance": money(1, "USD")}),
        422,
        "validation_error",
    )
    assert e["details"]["reason"] == "currency_mismatch"
    assert q(api_engine, "SELECT 1 FROM balance_record") == []


@pytest.mark.parametrize(
    "body",
    [
        {"balance": money(1)},
        {"balance_on": "2026-02-30", "balance": money(1)},
        {"balance_on": "soon", "balance": money(1)},
        {"balance_on": "2026-03-01", "balance": 100},  # money never travels without its currency
        {"balance_on": "2026-03-01", "balance": money(12.5)},
        {"balance_on": "2026-03-01", "balance": money("12")},
        {"balance_on": "2026-03-01", "balance": {"amount": 1}},
        {"balance_on": "2026-03-01", "balance": money(1), "kind": "reported"},
    ],
)
def test_set_validation_is_a_422_envelope(anna: TestClient, api_engine: Engine, body: dict) -> None:
    aid = seed_account(api_engine)
    r = anna.post(f"/api/ledger/accounts/{aid}/balance-records", json=body)
    assert_envelope(r, 422, "validation_error")
    assert "soon" not in r.text


# ---- edit -----------------------------------------------------------------------------------


def test_put_corrects_the_balance_and_the_date_of_a_manual_record(
    anna: TestClient, api_engine: Engine
) -> None:
    aid = seed_account(api_engine)
    rid = seed_manual(api_engine, aid, date(2026, 3, 1), 1_000)
    r = anna.put(f"/api/ledger/balance-records/{rid}", json={"balance": money(2_000)})
    assert r.status_code == 200 and r.json()["record"]["balance"] == money(2_000)
    assert derived(api_engine, aid) == [("opening", date(2026, 2, 28), 2_000)]
    r = anna.put(
        f"/api/ledger/balance-records/{rid}", json={"balance": money(2_000), "balance_on": "2026-02-01"}
    )
    assert r.json()["record"]["balance_on"] == "2026-02-01"
    assert derived(api_engine, aid) == [("opening", date(2026, 1, 31), 2_000)]
    assert_checks_ok(anna)


def test_put_refusals(anna: TestClient, api_engine: Engine) -> None:
    aid = seed_account(api_engine)
    a = seed_manual(api_engine, aid, date(2026, 3, 1), 1_000)
    seed_manual(api_engine, aid, date(2026, 3, 5), 1_100)
    e = assert_envelope(
        anna.put(f"/api/ledger/balance-records/{a}", json={"balance": money(1), "balance_on": "2026-03-05"}),
        409,
        "conflict",
    )
    assert e["details"]["reason"] == "record_date_taken"
    assert_envelope(
        anna.put("/api/ledger/balance-records/99999", json={"balance": money(1)}), 404, "not_found"
    )
    e = assert_envelope(
        anna.put(f"/api/ledger/balance-records/{a}", json={"balance": money(1, "USD")}),
        422,
        "validation_error",
    )
    assert e["details"]["reason"] == "currency_mismatch"
    for body in (
        {},
        {"balance": 5},
        {"balance": money(1), "balance_on": "x"},
        {"balance": money(1), "id": 3},
    ):
        assert_envelope(anna.put(f"/api/ledger/balance-records/{a}", json=body), 422, "validation_error")


def test_a_reported_record_is_not_editable_but_deletable(anna: TestClient, api_engine: Engine) -> None:
    aid = seed_account(api_engine)
    reported = seed_difference(api_engine, aid)
    e = assert_envelope(
        anna.put(f"/api/ledger/balance-records/{reported}", json={"balance": money(1)}), 409, "conflict"
    )
    assert e["details"]["reason"] == "reported_record_not_editable"
    assert anna.get("/api/ledger/accounts").json()["accounts"][0]["unexplained_difference"] is not None
    r = anna.delete(f"/api/ledger/balance-records/{reported}")
    assert r.status_code == 200
    assert r.json()["deleted_record"]["id"] == reported and r.json()["deleted_record"]["kind"] == "reported"
    assert r.json()["account"]["unexplained_difference"] is None  # its reconciliation went with it
    assert q(api_engine, "SELECT 1 FROM balance_record WHERE id = :i", i=reported) == []
    assert_checks_ok(anna)


# ---- delete ---------------------------------------------------------------------------------


def test_deleting_the_anchor_moves_the_anchor(anna: TestClient, api_engine: Engine) -> None:
    aid = seed_account(api_engine)
    first = seed_manual(api_engine, aid, date(2026, 1, 31), 10_000)
    seed_manual(api_engine, aid, date(2026, 2, 15), 9_000)
    assert derived(api_engine, aid) == [
        ("opening", date(2026, 1, 30), 10_000),
        ("reconciliation", date(2026, 2, 15), -1_000),
    ]
    r = anna.delete(f"/api/ledger/balance-records/{first}")
    assert r.status_code == 200 and r.json()["account"]["anchored"] is True
    assert derived(api_engine, aid) == [("opening", date(2026, 2, 14), 9_000)]
    only = q(api_engine, "SELECT id FROM balance_record")[0].id
    assert (
        anna.delete(f"/api/ledger/balance-records/{only}").json()["account"]["anchored"] is True
    )  # no entries left
    assert derived(api_engine, aid) == []
    assert_checks_ok(anna)


def test_delete_a_missing_record_is_404(anna: TestClient) -> None:
    assert_envelope(anna.delete("/api/ledger/balance-records/424242"), 404, "not_found")


# ---- settle ---------------------------------------------------------------------------------


def test_each_write_settles_once_and_a_failure_is_a_notice_in_a_200(
    anna: TestClient, api_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    outcome = [SettleResult((4,), None)]
    monkeypatch.setattr(core_records, "settle", lambda engine: calls.append(1) or outcome[0])
    aid = seed_account(api_engine)
    r = anna.post(
        f"/api/ledger/accounts/{aid}/balance-records", json={"balance_on": "2026-03-01", "balance": money(5)}
    )
    rid = r.json()["record"]["id"]
    assert r.json()["settle"] == {"touched_entry_ids": [4], "error": None} and len(calls) == 1
    outcome[0] = SettleResult((), "settling failed")
    r = anna.put(f"/api/ledger/balance-records/{rid}", json={"balance": money(6)})
    assert r.status_code == 200 and r.json()["settle"]["error"] == "settling failed" and len(calls) == 2
    r = anna.delete(f"/api/ledger/balance-records/{rid}")
    assert r.status_code == 200 and r.json()["settle"]["error"] == "settling failed" and len(calls) == 3


# ---- session --------------------------------------------------------------------------------

ROUTES = [
    ("post", "/api/ledger/accounts/1/balance-records", {"balance_on": "2026-03-01", "balance": money(1)}),
    ("put", "/api/ledger/balance-records/1", {"balance": money(1)}),
    ("delete", "/api/ledger/balance-records/1", None),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_every_balance_record_endpoint_requires_a_session(
    client: TestClient, method: str, path: str, body
) -> None:
    r = getattr(client, method)(path, **({"json": body} if body is not None else {}))
    assert_envelope(r, 401, "unauthenticated")
