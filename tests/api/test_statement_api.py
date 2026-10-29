"""The account statement over HTTP (architecture §4.1 'The account statement')."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.api.accounts_helpers import assert_envelope, seed_account, seed_difference, seed_manual
from tests.api.conftest import login
from tests.invariants.helpers import make_entry, make_source


@pytest.fixture
def anna(client: TestClient) -> TestClient:
    login(client)
    return client


def url(account: int, **query: object) -> str:
    qs = "&".join(f"{k}={v}" for k, v in query.items())
    return f"/api/ledger/accounts/{account}/statement" + (f"?{qs}" if qs else "")


def test_the_statement_needs_a_session(client: TestClient) -> None:
    assert_envelope(client.get(url(1)), 401, "unauthenticated")


def test_a_missing_account_is_not_found(anna: TestClient) -> None:
    assert_envelope(anna.get(url(999)), 404, "not_found")


def test_an_empty_account(anna: TestClient, api_engine: Engine) -> None:
    aid = seed_account(api_engine)
    assert anna.get(url(aid)).json() == {"items": [], "total": 0, "limit": 100, "offset": 0}


def test_items_of_both_kinds_with_money(anna: TestClient, api_engine: Engine) -> None:
    aid = seed_account(api_engine)
    record = seed_difference(
        api_engine, aid
    )  # anchor 10000 at 31.1., one -1000 row on 10.2., reported 8000 on 1.3.
    body = anna.get(url(aid)).json()
    assert (body["total"], body["limit"], body["offset"]) == (3, 100, 0)
    reported, source, anchor = body["items"]
    assert reported == {
        "kind": "record",
        "id": record,
        "balance_on": "2026-03-01",
        "record_kind": "reported",
        "balance": {"amount": 8000, "currency": "EUR"},
        "anchor": False,
        "rows_sum": {"amount": -1000, "currency": "EUR"},
        "difference": {"amount": -1000, "currency": "EUR"},  # 8000 - 10000 - (-1000)
    }
    assert source["kind"] == "source" and source["booked_on"] == "2026-02-10"
    assert source["amount"] == {"amount": -1000, "currency": "EUR"}
    assert "balance" not in source
    assert (source["authored"], source["duplicate_of"], source["run_id"] is not None) == (False, None, True)
    assert source["entry_id"] is not None
    assert "raw" not in source
    assert anchor["anchor"] is True and anchor["rows_sum"] is None and anchor["difference"] is None


def test_paging_and_the_amount_filter(anna: TestClient, api_engine: Engine) -> None:
    aid = seed_account(api_engine)
    seed_manual(api_engine, aid, date(2026, 1, 1), 1000)
    with api_engine.begin() as conn:
        ids = [
            make_source(conn, aid, amount=amount, booked_on=date(2026, 1, day))
            for day, amount in ((2, -5), (3, -7), (4, -5))
        ]
        for i in ids:
            make_entry(conn, i)
        make_source(conn, aid, amount=-5, booked_on=date(2026, 1, 5), duplicate_of=ids[0])
    page = anna.get(url(aid, limit=2, offset=1)).json()
    assert (page["total"], page["limit"], page["offset"], len(page["items"])) == (5, 2, 1, 2)
    hits = anna.get(url(aid, amount=-5)).json()
    assert hits["total"] == 2 and [i["id"] for i in hits["items"]] == [ids[2], ids[0]]
    assert all(i["kind"] == "source" and i["duplicate_of"] is None for i in hits["items"])


@pytest.mark.parametrize("query", ["limit=0", "limit=501", "offset=-1", "amount=x"])
def test_bad_paging_is_a_validation_error(anna: TestClient, api_engine: Engine, query: str) -> None:
    aid = seed_account(api_engine)
    assert_envelope(anna.get(url(aid) + "?" + query), 422, "validation_error")


def test_the_account_facts_carry_the_balance_everywhere(anna: TestClient, api_engine: Engine) -> None:
    aid = seed_account(api_engine)
    seed_difference(api_engine, aid)
    listed = anna.get("/api/ledger/accounts").json()["accounts"][0]
    # the opening 10000, the movement -1000 and the reconciliation -1000
    assert listed["balance"] == {"amount": 8000, "currency": "EUR"}
    written = anna.put(f"/api/ledger/accounts/{aid}", json={"name": "Renamed"}).json()["account"]
    assert written["balance"] == listed["balance"]
    newest = anna.get(url(aid)).json()["items"][0]
    assert newest["balance"] == listed["balance"]  # the newest item agrees with the ledger
