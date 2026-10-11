"""The accounts endpoints (architecture §4.1, spec §3.3)."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.core import accounts as core_accounts
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
from tests.invariants.helpers import make_entry, make_instance, make_run, make_source

NEW = {"name": "Giro", "kind": "checking", "currency": "EUR"}


@pytest.fixture
def anna(client: TestClient) -> TestClient:
    login(client)
    return client


# ---- list and facts -------------------------------------------------------------------------


def test_list_is_empty_then_carries_the_facts_of_each_account(anna: TestClient, api_engine: Engine) -> None:
    assert anna.get("/api/ledger/accounts").json() == {"accounts": []}
    aid = seed_account(api_engine, external_ref="DE00 1", sort_order=2, note="main")
    body = anna.get("/api/ledger/accounts").json()
    assert body["accounts"] == [
        {
            "id": aid,
            "name": "Giro",
            "kind": "checking",
            "currency": "EUR",
            "external_ref": "de001",
            "closed_on": None,
            "sort_order": 2,
            "note": "main",
            "synced": False,
            "synced_through": None,
            "last_data_on": None,
            "unexplained_difference": None,
            "anchored": True,
            "records_since_zero": None,
        }
    ]


def test_facts_after_a_manual_record_and_after_a_reconcile_difference(
    anna: TestClient, api_engine: Engine
) -> None:
    aid = seed_account(api_engine)
    seed_manual(api_engine, aid, date(2026, 1, 31), 10_000)
    facts = anna.get("/api/ledger/accounts").json()["accounts"][0]
    assert facts["anchored"] is True and facts["unexplained_difference"] is None
    assert facts["records_since_zero"] is None
    assert q(api_engine, "SELECT count(*) FROM ledger_entry WHERE account_id = :a", a=aid)[0][0] == 1

    reported = seed_difference(api_engine, aid)
    facts = anna.get("/api/ledger/accounts").json()["accounts"][0]
    assert facts["unexplained_difference"]["currency"] == "EUR"
    assert facts["unexplained_difference"]["amount"] != 0
    assert facts["records_since_zero"] == [reported]


def test_open_accounts_come_before_closed_ones(anna: TestClient, api_engine: Engine) -> None:
    old = seed_account(api_engine, "Aaa")
    new = seed_account(api_engine, "Zzz")
    anna.post(f"/api/ledger/accounts/{old}/close", json={"closed_on": "2026-01-01"})
    assert [a["id"] for a in anna.get("/api/ledger/accounts").json()["accounts"]] == [new, old]


# ---- create ---------------------------------------------------------------------------------


def test_create_answers_201_with_the_account_and_creates_nothing_else(
    anna: TestClient, api_engine: Engine
) -> None:
    r = anna.post("/api/ledger/accounts", json={**NEW, "sort_order": 4, "note": "n", "external_ref": "X 1"})
    assert r.status_code == 201
    body = r.json()
    assert body["account"]["name"] == "Giro" and body["account"]["sort_order"] == 4
    assert body["account"]["external_ref"] == "x1"
    assert body["settle"] == {"touched_entry_ids": [], "error": None}
    for table in ("ledger_entry", "source_transaction", "import_run", "balance_record", "account_source"):
        assert q(api_engine, f"SELECT count(*) FROM {table}")[0][0] == 0  # noqa: S608


def test_create_refusals(anna: TestClient, api_engine: Engine) -> None:
    seed_account(api_engine, external_ref="dup")
    e = assert_envelope(
        anna.post("/api/ledger/accounts", json={**NEW, "external_ref": "DUP"}), 409, "conflict"
    )
    assert e["details"]["reason"] == "duplicate_external_ref"
    e = assert_envelope(
        anna.post("/api/ledger/accounts", json={**NEW, "currency": "ZZZ"}), 422, "validation_error"
    )
    assert e["details"]["reason"] == "unknown_currency"
    assert len(q(api_engine, "SELECT 1 FROM account")) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "checking", "currency": "EUR"},  # no name
        {**NEW, "kind": "piggybank"},
        {**NEW, "currency": "eur"},
        {**NEW, "id": 5},  # unknown field
        {**NEW, "sort_order": "1"},
        {**NEW, "sort_order": 1.5},
    ],
)
def test_create_validation_is_a_422_envelope_that_does_not_echo_input(anna: TestClient, body: dict) -> None:
    r = anna.post("/api/ledger/accounts", json=body)
    assert_envelope(r, 422, "validation_error")
    assert "piggybank" not in r.text


# ---- update ---------------------------------------------------------------------------------


def test_update_clears_the_note_with_null_and_keeps_it_when_absent(
    anna: TestClient, api_engine: Engine
) -> None:
    aid = seed_account(api_engine, note="main")
    kept = anna.put(f"/api/ledger/accounts/{aid}", json={"name": "Other"})
    assert kept.json()["account"]["note"] == "main"
    cleared = anna.put(f"/api/ledger/accounts/{aid}", json={"note": None})
    assert cleared.status_code == 200 and cleared.json()["account"]["note"] is None
    assert q(api_engine, "SELECT note FROM account")[0].note is None


def test_a_whitespace_only_name_is_a_validation_error(anna: TestClient, api_engine: Engine) -> None:
    aid = seed_account(api_engine)
    for blank in ("", " ", "\t \n"):
        assert_envelope(
            anna.post("/api/ledger/accounts", json={**NEW, "name": blank}), 422, "validation_error"
        )
        assert_envelope(
            anna.put(f"/api/ledger/accounts/{aid}", json={"name": blank}), 422, "validation_error"
        )
    assert q(api_engine, "SELECT name FROM account")[0].name == "Giro"


def test_update_changes_what_is_given_and_returns_the_account(anna: TestClient, api_engine: Engine) -> None:
    aid = seed_account(api_engine)
    r = anna.put(
        f"/api/ledger/accounts/{aid}",
        json={"name": "Main", "sort_order": 9, "note": "x", "external_ref": "AB 12", "kind": "savings"},
    )
    assert r.status_code == 200
    acc = r.json()["account"]
    assert (acc["name"], acc["sort_order"], acc["note"], acc["external_ref"], acc["kind"]) == (
        "Main",
        9,
        "x",
        "ab12",
        "savings",
    )
    assert r.json()["settle"]["error"] is None


def test_update_can_clear_the_external_ref_and_leaves_it_alone_when_absent(
    anna: TestClient, api_engine: Engine
) -> None:
    aid = seed_account(api_engine, external_ref="keep")
    assert (
        anna.put(f"/api/ledger/accounts/{aid}", json={"name": "N"}).json()["account"]["external_ref"]
        == "keep"
    )
    assert (
        anna.put(f"/api/ledger/accounts/{aid}", json={"external_ref": None}).json()["account"]["external_ref"]
        is None
    )


def test_update_refusals(anna: TestClient, api_engine: Engine) -> None:
    a = seed_account(api_engine, external_ref="one")
    b = seed_account(api_engine, "B")
    e = assert_envelope(anna.put(f"/api/ledger/accounts/{b}", json={"external_ref": "ONE"}), 409, "conflict")
    assert e["details"]["reason"] == "duplicate_external_ref"
    e = assert_envelope(anna.put(f"/api/ledger/accounts/{a}", json={"kind": "depot"}), 409, "conflict")
    assert e["details"]["reason"] == "kind_class_change"
    assert_envelope(anna.put("/api/ledger/accounts/99999", json={"name": "x"}), 404, "not_found")


@pytest.mark.parametrize(
    "body", [{"currency": "USD"}, {"closed_on": "2026-01-01"}, {"sort_order": "x"}, {"kind": "nope"}]
)
def test_update_rejects_currency_and_unknown_fields_at_validation(
    anna: TestClient, api_engine: Engine, body: dict
) -> None:
    aid = seed_account(api_engine)
    assert_envelope(anna.put(f"/api/ledger/accounts/{aid}", json=body), 422, "validation_error")
    assert q(api_engine, "SELECT currency FROM account WHERE id = :a", a=aid)[0][0] == "EUR"


# ---- delete ---------------------------------------------------------------------------------


def test_delete_an_empty_account_is_200_with_the_settle_result(anna: TestClient, api_engine: Engine) -> None:
    aid = seed_account(api_engine)
    r = anna.delete(f"/api/ledger/accounts/{aid}")
    assert r.status_code == 200 and r.json() == {"settle": {"touched_entry_ids": [], "error": None}}
    assert q(api_engine, "SELECT 1 FROM account") == []


def test_delete_a_missing_account_is_404(anna: TestClient) -> None:
    assert_envelope(anna.delete("/api/ledger/accounts/12345"), 404, "not_found")


def _with_balance_record(engine: Engine, aid: int) -> None:
    seed_manual(engine, aid)


def _with_source_and_entry(engine: Engine, aid: int) -> None:
    with engine.begin() as conn:
        make_entry(conn, make_source(conn, aid, importer=None))


def _with_run(engine: Engine, aid: int) -> None:
    with engine.begin() as conn:
        make_run(conn, aid)


def _with_link(engine: Engine, aid: int) -> None:
    with engine.begin() as conn:
        from tests.invariants.helpers import link_account

        link_account(conn, aid, make_instance(conn))


@pytest.mark.parametrize("dependent", [_with_balance_record, _with_source_and_entry, _with_run, _with_link])
def test_delete_is_refused_for_each_kind_of_dependent_and_suggests_closing(
    anna: TestClient, api_engine: Engine, dependent
) -> None:
    aid = seed_account(api_engine)
    dependent(api_engine, aid)
    e = assert_envelope(anna.delete(f"/api/ledger/accounts/{aid}"), 409, "conflict")
    assert e["details"]["reason"] == "account_not_empty"
    assert "close" in e["message"] and e["details"]["held"]
    assert q(api_engine, "SELECT 1 FROM account WHERE id = :a", a=aid)


# ---- close and reopen -----------------------------------------------------------------------


def test_close_and_reopen_toggle_the_account_and_synced(anna: TestClient, api_engine: Engine) -> None:
    aid = seed_account(api_engine)
    with api_engine.begin() as conn:
        from tests.invariants.helpers import link_account

        link_account(conn, aid, make_instance(conn))
    assert anna.post(f"/api/ledger/accounts/{aid}/reopen").json()["account"]["synced"] is True
    r = anna.post(f"/api/ledger/accounts/{aid}/close", json={"closed_on": "2026-02-01"})
    assert r.status_code == 200
    assert r.json()["account"]["closed_on"] == "2026-02-01" and r.json()["account"]["synced"] is False
    r = anna.post(f"/api/ledger/accounts/{aid}/reopen")
    assert r.json()["account"]["closed_on"] is None and r.json()["account"]["synced"] is True


def test_close_and_reopen_refusals(anna: TestClient, api_engine: Engine) -> None:
    aid = seed_account(api_engine)
    assert_envelope(
        anna.post("/api/ledger/accounts/9999/close", json={"closed_on": "2026-02-01"}), 404, "not_found"
    )
    assert_envelope(anna.post("/api/ledger/accounts/9999/reopen"), 404, "not_found")
    for body in (
        {},
        {"closed_on": "2026-13-45"},
        {"closed_on": "yesterday"},
        {"closed_on": "2026-02-01", "x": 1},
    ):
        assert_envelope(anna.post(f"/api/ledger/accounts/{aid}/close", json=body), 422, "validation_error")


# ---- settle in the response -----------------------------------------------------------------


def test_each_write_settles_once_and_the_result_is_in_the_body(
    anna: TestClient, api_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    monkeypatch.setattr(core_accounts, "settle", lambda engine: calls.append(1) or SettleResult((7, 8), None))
    aid = seed_account(api_engine)
    r = anna.put(f"/api/ledger/accounts/{aid}", json={"external_ref": "zz"})
    assert r.json()["settle"] == {"touched_entry_ids": [7, 8], "error": None} and len(calls) == 1
    anna.post(f"/api/ledger/accounts/{aid}/close", json={"closed_on": "2026-02-01"})
    anna.post(f"/api/ledger/accounts/{aid}/reopen")
    assert len(calls) == 3


def test_a_settle_failure_is_a_notice_in_a_200_response(
    anna: TestClient, api_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(core_accounts, "settle", lambda engine: SettleResult((), "settling failed"))
    aid = seed_account(api_engine)
    r = anna.post(f"/api/ledger/accounts/{aid}/close", json={"closed_on": "2026-02-01"})
    assert r.status_code == 200
    assert r.json()["settle"]["error"] == "settling failed"
    assert r.json()["account"]["closed_on"] == "2026-02-01"  # the write stood


def test_a_settle_failure_after_a_delete_is_in_the_body(
    anna: TestClient, api_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(core_accounts, "settle", lambda engine: SettleResult((), "settling failed"))
    aid = seed_account(api_engine)
    r = anna.delete(f"/api/ledger/accounts/{aid}")
    assert r.status_code == 200 and r.json()["settle"]["error"] == "settling failed"
    assert q(api_engine, "SELECT 1 FROM account") == []


def test_a_settle_result_after_a_create_with_an_external_ref_is_in_the_body(
    anna: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(core_accounts, "settle", lambda engine: SettleResult((3,), "settling failed"))
    r = anna.post("/api/ledger/accounts", json={**NEW, "external_ref": "ref-1"})
    assert r.status_code == 201
    assert r.json()["settle"] == {"touched_entry_ids": [3], "error": "settling failed"}


def test_a_create_without_an_external_ref_does_not_settle(
    anna: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    monkeypatch.setattr(core_accounts, "settle", lambda engine: calls.append(1) or SettleResult())
    r = anna.post("/api/ledger/accounts", json=NEW)
    assert r.status_code == 201 and calls == []
    assert r.json()["settle"] == {"touched_entry_ids": [], "error": None}


# ---- session --------------------------------------------------------------------------------

ROUTES = [
    ("get", "/api/ledger/accounts", None),
    ("post", "/api/ledger/accounts", NEW),
    ("put", "/api/ledger/accounts/1", {"name": "x"}),
    ("delete", "/api/ledger/accounts/1", None),
    ("post", "/api/ledger/accounts/1/close", {"closed_on": "2026-01-01"}),
    ("post", "/api/ledger/accounts/1/reopen", None),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_every_account_endpoint_requires_a_session(client: TestClient, method: str, path: str, body) -> None:
    assert_envelope(
        getattr(client, method)(path, **({"json": body} if body is not None else {})), 401, "unauthenticated"
    )


def test_the_ledger_stays_clean_through_these_operations(anna: TestClient, api_engine: Engine) -> None:
    aid = seed_account(api_engine)
    seed_difference(api_engine, aid)
    anna.post(f"/api/ledger/accounts/{aid}/close", json={"closed_on": "2026-04-01"})
    anna.post(f"/api/ledger/accounts/{aid}/reopen")
    assert_checks_ok(anna)
