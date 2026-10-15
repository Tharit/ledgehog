"""`/api/ledger/sources`: the entry form's create, edit and delete (architecture §4.1, spec §3.9, §5.6)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.api.openapi import build_openapi
from tests.api.accounts_helpers import assert_envelope
from tests.api.conftest import login
from tests.fixtures import ledger_seed as seed
from tests.invariants.helpers import link_account, make_entry, make_instance, make_source

URL = "/api/ledger/sources"


@pytest.fixture
def anna(client: TestClient) -> TestClient:
    login(client)
    return client


@pytest.fixture
def cash(api_engine: Engine) -> int:
    with api_engine.begin() as conn:
        return seed.account(conn, "Cash", kind="cash")


def body(account: int, **kw: Any) -> dict[str, Any]:
    return {
        "id": "form-0001",
        "account_id": account,
        "amount": -2500,
        "booked_on": "2026-03-10",
        "purpose": "bread",
        **kw,
    }


def versions_of(engine: Engine, *ids: int) -> dict[str, int]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, version FROM ledger_entry WHERE id = ANY(:i)"), {"i": list(ids)})
        return {str(r.id): int(r.version) for r in rows}


def test_requires_a_session(client: TestClient) -> None:
    assert_envelope(client.post(URL, json={}), 401, "unauthenticated")
    assert_envelope(client.put(f"{URL}/1", json={}), 401, "unauthenticated")
    assert_envelope(client.delete(f"{URL}/1"), 401, "unauthenticated")


def test_create_answers_201_with_the_unit_then_200_for_a_repeat(anna: TestClient, cash: int) -> None:
    r = anna.post(URL, json=body(cash))
    assert r.status_code == 201, r.text
    out = r.json()
    assert set(out) == {
        "source_transaction_id",
        "anchor_entry_id",
        "entries",
        "units",
        "removed_entry_ids",
        "settle",
    }
    (entry,) = out["entries"]
    assert out["anchor_entry_id"] == entry["id"]
    assert (entry["amount"], entry["booked_on"], entry["authored"]) == (
        {"amount": -2500, "currency": "EUR"},
        "2026-03-10",
        True,
    )
    assert entry["source"] == {
        "amount": {"amount": -2500, "currency": "EUR"},
        "counterparty_name": None,
        "counterparty_ref": None,
        "counterparty_bic": None,
        "purpose": "bread",
        "booking_text": None,
        "end_to_end_id": None,
        "mandate_ref": None,
        "instructed_amount": None,
        "source_format": None,
    }
    assert out["units"] == [
        {
            "anchor_entry_id": entry["id"],
            "entry_ids": [entry["id"]],
            "state": {"confirmed": False, "reasons": ["incomplete"]},
        }
    ]
    assert out["removed_entry_ids"] == [] and out["settle"]["error"] is None
    again = anna.post(URL, json=body(cash, amount=-1, purpose="different"))
    assert again.status_code == 200
    assert again.json()["entries"] == out["entries"]


def test_create_validation(anna: TestClient, cash: int) -> None:
    for bad in (
        body(cash, amount=0),
        body(cash, amount=1.5),
        body(cash, id=""),
        body(cash, id="has space"),
        body(cash, account_id=0),
        body(cash, booked_on="soon"),
        body(cash, purpose="x" * 501),
        {**body(cash), "currency": "EUR"},
    ):
        assert_envelope(anna.post(URL, json=bad), 422, "validation_error")
    missing = body(cash)
    del missing["id"]
    assert_envelope(anna.post(URL, json=missing), 422, "validation_error")


def test_create_without_a_purpose(anna: TestClient, cash: int) -> None:
    payload = body(cash)
    del payload["purpose"]
    assert anna.post(URL, json=payload).status_code == 201


def test_create_on_a_synced_account_is_account_synced(anna: TestClient, api_engine: Engine) -> None:
    with api_engine.begin() as conn:
        acct = seed.account(conn, "Giro")
        link_account(conn, acct, make_instance(conn))
    assert_envelope(anna.post(URL, json=body(acct)), 422, "account_synced")


def test_create_on_an_unknown_account_is_a_stale_reference(anna: TestClient) -> None:
    err = assert_envelope(anna.post(URL, json=body(9999)), 409, "stale_reference")
    assert err["details"]["field"] == "account_id"


def test_edit_dry_run_reports_and_writes_nothing(anna: TestClient, cash: int, api_engine: Engine) -> None:
    created = anna.post(URL, json=body(cash)).json()
    sid = created["source_transaction_id"]
    r = anna.put(f"{URL}/{sid}", json={"amount": -4000, "booked_on": "2026-03-11", "dry_run": True})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["dry_run"] is True and out["settle"] is None and out["entries"] == [] and out["units"] == []
    effects = out["effects"]
    assert set(effects) == {
        "collapsed_entry_ids",
        "unpaired_entry_ids",
        "deleted_entry_ids",
        "rederived_entry_ids",
        "returned_to_review_ids",
        "versions",
    }
    assert effects["versions"] == [
        {"entry_id": created["anchor_entry_id"], "version": created["entries"][0]["version"]}
    ]
    assert anna.get(f"/api/ledger/entries/{created['anchor_entry_id']}").json()["amount"]["amount"] == -2500


def test_edit_real_run_returns_the_rows(anna: TestClient, cash: int, api_engine: Engine) -> None:
    created = anna.post(URL, json=body(cash)).json()
    sid, eid = created["source_transaction_id"], created["anchor_entry_id"]
    r = anna.put(
        f"{URL}/{sid}",
        json={
            "amount": -4000,
            "booked_on": "2026-03-11",
            "purpose": "cake",
            "expected_versions": versions_of(api_engine, eid),
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    (entry,) = out["entries"]
    assert (entry["amount"]["amount"], entry["booked_on"]) == (-4000, "2026-03-11")
    assert entry["version"] > created["entries"][0]["version"]
    assert out["dry_run"] is False and out["anchor_entry_id"] == eid and out["settle"]["error"] is None
    assert out["units"][0]["entry_ids"] == [eid]


def test_edit_errors(anna: TestClient, cash: int, api_engine: Engine) -> None:
    created = anna.post(URL, json=body(cash)).json()
    sid, eid = created["source_transaction_id"], created["anchor_entry_id"]
    # the account is never edited
    assert_envelope(
        anna.put(f"{URL}/{sid}", json={"account_id": cash, "amount": -1}), 422, "validation_error"
    )
    # nothing to edit
    assert_envelope(anna.put(f"{URL}/{sid}", json={"expected_versions": {}}), 422, "validation_error")
    assert_envelope(anna.put(f"{URL}/{sid}", json={"amount": 0}), 422, "validation_error")
    assert_envelope(anna.put(f"{URL}/99999", json={"amount": -1, "dry_run": True}), 404, "not_found")
    # a real run without versions names the entries it writes
    err = assert_envelope(anna.put(f"{URL}/{sid}", json={"amount": -1}), 409, "conflict")
    assert err["details"]["entry_ids"] == [eid]
    err = assert_envelope(
        anna.put(f"{URL}/{sid}", json={"amount": -1, "expected_versions": {str(eid): 99}}), 409, "conflict"
    )
    assert err["details"]["entry_ids"] == [eid]
    # an imported row is refused
    with api_engine.begin() as conn:
        s = make_source(conn, cash)
        make_entry(conn, s)
    assert_envelope(anna.put(f"{URL}/{s}", json={"amount": -1, "dry_run": True}), 422, "not_user_authored")


def test_delete_dry_run_then_real(anna: TestClient, cash: int, api_engine: Engine) -> None:
    created = anna.post(URL, json=body(cash, purpose="REWE")).json()
    sid, eid = created["source_transaction_id"], created["anchor_entry_id"]
    dry = anna.delete(f"{URL}/{sid}", params={"dry_run": "true"})
    assert dry.status_code == 200, dry.text
    d = dry.json()
    assert d["dry_run"] is True and d["settle"] is None
    assert d["counts"] == {
        "entries": 1,
        "confirmed_entries": 0,
        "tagged_entries": 0,
        "tag_memberships": 0,
        "partners_returning_to_review": 0,
        "freed_documents": 0,
    }
    assert (
        [e["id"] for e in d["removed"]] == [eid] and d["removed_entry_ids"] == [eid] and d["partners"] == []
    )
    # a real run needs the versions
    err = assert_envelope(anna.delete(f"{URL}/{sid}"), 409, "conflict")
    assert err["details"]["entry_ids"] == [eid]
    assert_envelope(
        anna.delete(f"{URL}/{sid}", params={"expected_versions": "garbage"}), 422, "validation_error"
    )
    real = anna.delete(f"{URL}/{sid}", params={"expected_versions": f"{eid}:{d['removed'][0]['version']}"})
    assert real.status_code == 200, real.text
    assert real.json()["dry_run"] is False and real.json()["settle"]["error"] is None
    assert anna.get(f"/api/ledger/entries/{eid}").status_code == 404
    assert_envelope(anna.delete(f"{URL}/{sid}", params={"dry_run": "true"}), 404, "not_found")


def test_delete_refuses_an_imported_row(anna: TestClient, cash: int, api_engine: Engine) -> None:
    with api_engine.begin() as conn:
        s = make_source(conn, cash)
        make_entry(conn, s)
    assert_envelope(anna.delete(f"{URL}/{s}", params={"dry_run": "true"}), 422, "not_user_authored")


def test_the_concurrent_edit_is_a_conflict(anna: TestClient, cash: int, api_engine: Engine) -> None:
    created = anna.post(URL, json=body(cash)).json()
    sid, eid = created["source_transaction_id"], created["anchor_entry_id"]
    seen = versions_of(api_engine, eid)
    first = anna.put(f"{URL}/{sid}", json={"amount": -10, "expected_versions": seen})
    second = anna.put(f"{URL}/{sid}", json={"amount": -20, "expected_versions": seen})
    assert first.status_code == 200
    err = assert_envelope(second, 409, "conflict")
    assert err["details"]["entry_ids"] == [eid]


def test_openapi_documents_the_operations(anna: TestClient) -> None:
    app = anna.app
    schema = build_openapi(app)  # type: ignore[arg-type]
    paths = schema["paths"]
    assert paths[URL]["post"]["operationId"] == "create_ledger_source"
    assert paths[f"{URL}/{{source_id}}"]["put"]["operationId"] == "update_ledger_source"
    assert paths[f"{URL}/{{source_id}}"]["delete"]["operationId"] == "delete_ledger_source"
    post = paths[URL]["post"]["responses"]
    assert {"200", "201", "401", "409", "422"} <= set(post)
    assert (
        post["201"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/SourceWriteOut"
    )
    props = schema["components"]["schemas"]["SourceUpdateBody"]["properties"]
    assert set(props) == {"amount", "booked_on", "purpose", "expected_versions", "dry_run"}
    assert schema["components"]["schemas"]["SourceUpdateBody"]["additionalProperties"] is False
    assert schema["components"]["schemas"]["SourceCreateBody"]["additionalProperties"] is False
