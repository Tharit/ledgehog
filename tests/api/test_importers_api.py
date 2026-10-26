"""Importer instances and links over HTTP (architecture §4.1, §4.4)."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.accounts import close_account
from app.core.importers import instances as instances_module
from app.core.importers.instances import create_instance
from app.core.settle.settle import SettleResult
from app.plugins.importers.csv import load_presets
from tests.api import importers_helpers as h
from tests.api.importers_helpers import Api, SpyCsv, error_of
from tests.invariants.helpers import make_entry, make_source

BASE = "/api/importers/instances"
api = h.api  # fixtures shared by the importer API tests
make_api = h.make_api
PROFILE = load_presets()["consorsbank_giro"]

ROUTES = [
    ("GET", "/api/importers"),
    ("GET", BASE),
    ("POST", BASE),
    ("PUT", f"{BASE}/1"),
    ("POST", f"{BASE}/1/reset"),
    ("DELETE", f"{BASE}/1"),
    ("POST", f"{BASE}/1/links"),
    ("DELETE", f"{BASE}/1/links/1"),
    ("POST", f"{BASE}/1/upload"),
    ("GET", "/api/importers/runs"),
    ("GET", "/api/importers/runs/1"),
    ("POST", "/api/importers/runs/1/revert"),
]


@pytest.mark.parametrize(
    ("exc", "code"),
    [("BankSetupRequired", "bank_setup_required"), ("AccountUnsupported", "account_unsupported")],
)
def test_the_new_importer_errors_are_422_with_their_code_and_not_retryable(api: Api, exc, code):
    from app.core.plugins import errors

    @api.client.app.get("/api/_importer_error")
    def raises() -> None:
        raise getattr(errors, exc)("say what to fix")

    r = api.client.get("/api/_importer_error")
    assert r.status_code == 422
    assert r.json()["error"] == {
        "code": code,
        "message": "say what to fix",
        "details": {"retryable": False},
    }


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_every_route_needs_a_session(make_api, method, path):
    anon = make_api(signed_in=False)
    error_of(anon.client.request(method, path), 401, "unauthenticated")


# ---- instances -----------------------------------------------------------------------------


def test_the_list_starts_empty(api: Api):
    r = api.client.get(BASE)
    assert r.status_code == 200 and r.json() == []


def test_create_returns_the_instance_and_the_list_shows_it_with_links(api: Api):
    r = api.client.post(BASE, json={"importer": "csv", "label": "Giro CSV", "settings": PROFILE})
    assert r.status_code == 201
    inst = r.json()
    assert inst == {
        "id": inst["id"],
        "importer": "csv",
        "label": "Giro CSV",
        "emits": ["transactions"],
        "access": "shared",
        "owner_id": None,
        "owner_name": None,
        "settings": PROFILE,
        "disabled": False,
        "last_run_at": None,
        "accounts": [],
        "manageable": True,
    }
    acct = api.account()
    api.link(inst["id"], acct)
    (listed,) = api.client.get(BASE).json()
    assert listed["accounts"] == [{"account_id": acct, "external_ref": f"acct-{acct}"}]
    assert api.importer.validate_calls == 1


def test_create_validates_the_settings_with_the_registered_importer(api: Api):
    bad = {**PROFILE, "date_format": "not a pattern"}
    err = error_of(
        api.client.post(BASE, json={"importer": "csv", "label": "x", "settings": bad}), 422, "invalid_profile"
    )
    assert err["details"]["setting"]
    assert api.client.get(BASE).json() == []


def test_create_with_an_unknown_importer_is_refused(api: Api):
    r = api.client.post(BASE, json={"importer": "fints", "label": "x", "settings": {}})
    error_of(r, 422, "importer_not_available")
    assert api.client.get(BASE).json() == []


@pytest.mark.parametrize(
    "body",
    [
        {"importer": "csv", "label": "x", "settings": PROFILE, "access": "owner"},
        {"importer": "csv", "settings": PROFILE},
        {"importer": "csv", "label": "x", "settings": []},
    ],
    ids=["extra-field", "missing-label", "settings-not-an-object"],
)
def test_create_bodies_are_strict(api: Api, body):
    error_of(api.client.post(BASE, json=body), 422, "validation_error")


def test_a_blank_label_is_refused(api: Api):
    error_of(
        api.client.post(BASE, json={"importer": "csv", "label": "  ", "settings": PROFILE}),
        422,
        "invalid_instance",
    )


def test_update_changes_label_settings_and_disabled(api: Api):
    inst = api.instance()
    other = {**PROFILE, "quote": "'"}
    r = api.client.put(f"{BASE}/{inst}", json={"label": "Renamed", "settings": other, "disabled": True})
    assert r.status_code == 200
    assert (r.json()["label"], r.json()["settings"], r.json()["disabled"]) == ("Renamed", other, True)
    # a partial update leaves the rest
    r = api.client.put(f"{BASE}/{inst}", json={"disabled": False})
    assert (r.json()["label"], r.json()["disabled"]) == ("Renamed", False)


def test_update_validates_settings_only_when_given(api: Api):
    inst = api.instance()
    before = api.importer.validate_calls
    api.client.put(f"{BASE}/{inst}", json={"label": "x"})
    assert api.importer.validate_calls == before
    r = api.client.put(f"{BASE}/{inst}", json={"settings": {"delimiter": "??"}})
    error_of(r, 422, "invalid_profile")
    assert api.client.get(BASE).json()[0]["settings"] == PROFILE


def test_update_settings_of_an_instance_whose_importer_is_not_registered(make_api):
    api = make_api(importers={})
    inst = create_instance(
        api.engine, importer="csv", label="x", settings=PROFILE, emits=["transactions"], access="shared"
    )
    error_of(api.client.put(f"{BASE}/{inst}", json={"settings": PROFILE}), 422, "importer_not_available")
    assert api.client.put(f"{BASE}/{inst}", json={"label": "ok"}).status_code == 200


def test_update_and_reset_of_a_missing_instance(api: Api):
    error_of(api.client.put(f"{BASE}/999", json={"label": "x"}), 404, "not_found")
    error_of(api.client.post(f"{BASE}/999/reset"), 404, "not_found")
    error_of(api.client.delete(f"{BASE}/999"), 404, "not_found")


def test_update_with_a_blank_label_is_refused(api: Api):
    inst = api.instance()
    error_of(api.client.put(f"{BASE}/{inst}", json={"label": ""}), 422, "invalid_instance")


def test_reset_clears_the_state_and_keeps_the_settings(api: Api):
    inst = api.instance()
    from sqlalchemy import text

    with api.engine.begin() as conn:
        conn.execute(text("UPDATE importer_instance SET state = '{\"k\": 1}'::jsonb"))
    r = api.client.post(f"{BASE}/{inst}/reset")
    assert r.status_code == 200 and r.json()["settings"] == PROFILE
    assert api.one("SELECT state FROM importer_instance").state == {}


def test_delete_returns_the_settle_result(api: Api, monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(
        instances_module, "settle", lambda engine: calls.append(1) or SettleResult(touched_entry_ids=(4, 5))
    )
    inst = api.instance()
    r = api.client.delete(f"{BASE}/{inst}")
    assert r.status_code == 200
    assert r.json() == {"settle": {"touched_entry_ids": [4, 5], "error": None}}
    assert calls == [1]
    assert api.client.get(BASE).json() == []


# ---- links ---------------------------------------------------------------------------------


def _giro() -> bytes:
    from tests.plugins.importers.csv.fixtures import giro_bytes

    return giro_bytes()


def test_link_defaults_the_external_ref_and_returns_what_it_did(api: Api, monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(
        instances_module, "settle", lambda engine: calls.append(1) or SettleResult(touched_entry_ids=(7,))
    )
    inst, acct = api.instance(), api.account()
    r = api.client.post(f"{BASE}/{inst}/links", json={"account_id": acct})
    assert r.status_code == 200
    assert r.json() == {
        "instance_id": inst,
        "account_id": acct,
        "external_ref": f"acct-{acct}",
        "dry_run": False,
        "user_authored_count": 0,
        "first_booked_on": None,
        "last_booked_on": None,
        "account_becomes_synced": True,
        "warnings": [],
        "changes": r.json()["changes"],
        "settle": {"touched_entry_ids": [7], "error": None},
    }
    assert calls == [1]  # one settle per write


def test_a_file_importer_refuses_a_given_external_ref(api: Api):
    inst, acct = api.instance(), api.account()
    for dry_run in (False, True):
        r = api.client.post(
            f"{BASE}/{inst}/links", json={"account_id": acct, "external_ref": "DE00-main", "dry_run": dry_run}
        )
        err = error_of(r, 422, "validation_error")
        assert err["details"] == [
            {
                "location": ["body", "external_ref"],
                "message": "a file importer takes no reference",
                "type": "value_error",
            }
        ]
    assert api.client.get(BASE).json()[0]["accounts"] == []


class _FetchStub:
    """A registered importer that is not a file importer: it has no `parse`."""

    emits = frozenset({"transactions"})

    redelivery = "replace"

    def validate_settings(self, settings) -> None:
        return None


def _fetch_api(make_api) -> tuple[Api, int]:
    api = make_api({"csv": SpyCsv(), "bank": _FetchStub()})
    r = api.client.post(BASE, json={"importer": "bank", "label": "Bank", "settings": {}})
    assert r.status_code == 201, r.text
    return api, int(r.json()["id"])


def test_a_fetch_importer_requires_an_external_ref(make_api):
    api, inst = _fetch_api(make_api)
    acct = api.account()
    r = api.client.post(f"{BASE}/{inst}/links", json={"account_id": acct})
    err = error_of(r, 422, "validation_error")
    assert err["details"][0]["location"] == ["body", "external_ref"]
    r = api.client.post(f"{BASE}/{inst}/links", json={"account_id": acct, "external_ref": "DE00-main"})
    assert r.status_code == 200 and r.json()["external_ref"] == "DE00-main"


def test_link_dry_run_changes_nothing_and_equals_the_real_result(api: Api, monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(instances_module, "settle", lambda engine: calls.append(1) or SettleResult())
    inst, acct = api.instance(), api.account()
    # a user-authored row on the account: the preview warns about it
    with api.engine.begin() as conn:
        make_entry(conn, make_source(conn, acct, importer=None, booked_on=date(2026, 8, 1)))
    before = api.counts()
    dry = api.client.post(f"{BASE}/{inst}/links", json={"account_id": acct, "dry_run": True})
    assert dry.status_code == 200
    assert api.counts() == before and calls == []
    assert dry.json()["dry_run"] is True and dry.json()["settle"] is None
    assert dry.json()["user_authored_count"] == 1
    assert dry.json()["first_booked_on"] == dry.json()["last_booked_on"] == "2026-08-01"
    assert dry.json()["warnings"]
    real = api.client.post(f"{BASE}/{inst}/links", json={"account_id": acct})
    same = {k: v for k, v in real.json().items() if k not in ("dry_run", "settle")}
    assert same == {k: v for k, v in dry.json().items() if k not in ("dry_run", "settle")}
    assert real.json()["settle"] == {"touched_entry_ids": [], "error": None} and calls == [1]


def test_a_settle_error_comes_back_in_the_body_with_200(api: Api, monkeypatch):
    monkeypatch.setattr(instances_module, "settle", lambda engine: SettleResult(error="settle blew up"))
    inst, acct = api.instance(), api.account()
    r = api.client.post(f"{BASE}/{inst}/links", json={"account_id": acct})
    assert r.status_code == 200 and r.json()["settle"]["error"] == "settle blew up"
    assert len(api.client.get(BASE).json()[0]["accounts"]) == 1  # the link is committed


@pytest.mark.parametrize("dry_run", [False, True])
def test_link_refusals(api: Api, dry_run: bool):
    inst, acct = api.instance(), api.account()
    body = {"dry_run": dry_run}
    url = f"{BASE}/{inst}/links"
    error_of(api.client.post(f"{BASE}/999/links", json={"account_id": acct, **body}), 404, "not_found")
    error_of(api.client.post(url, json={"account_id": 999, **body}), 404, "not_found")
    closed = api.account("Old")
    close_account(api.engine, closed, date(2026, 8, 1))
    error_of(api.client.post(url, json={"account_id": closed, **body}), 409, "account_closed")
    docs = create_instance(
        api.engine, importer="csv", label="docs", settings={}, emits=["documents"], access="shared"
    )
    error_of(
        api.client.post(f"{BASE}/{docs}/links", json={"account_id": acct, **body}),
        409,
        "not_an_account_source",
    )
    api.client.put(f"{BASE}/{inst}", json={"disabled": True})
    error_of(api.client.post(url, json={"account_id": acct, **body}), 409, "instance_disabled")


def test_link_conflicts(make_api):
    api, inst = _fetch_api(make_api)
    acct, other = api.account(), api.account("Other")
    api.link(inst, acct, external_ref="same")
    url = f"{BASE}/{inst}/links"
    error_of(
        api.client.post(url, json={"account_id": acct, "external_ref": "different"}), 409, "already_linked"
    )
    error_of(
        api.client.post(url, json={"account_id": other, "external_ref": "same"}), 409, "external_ref_taken"
    )
    error_of(api.client.post(url, json={"account_id": other, "external_ref": " "}), 422, "invalid_instance")


def test_a_file_importer_link_twice_is_already_linked(api: Api):
    inst, acct = api.instance(), api.account()
    api.link(inst, acct)
    error_of(api.client.post(f"{BASE}/{inst}/links", json={"account_id": acct}), 409, "already_linked")


def test_link_bodies_are_strict(api: Api):
    inst = api.instance()
    error_of(api.client.post(f"{BASE}/{inst}/links", json={"account_id": 1, "x": 1}), 422, "validation_error")
    error_of(api.client.post(f"{BASE}/{inst}/links", json={}), 422, "validation_error")


def test_unlink_returns_the_settle_result(api: Api, monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(
        instances_module, "settle", lambda engine: calls.append(1) or SettleResult(touched_entry_ids=(9,))
    )
    inst, acct = api.world()
    calls.clear()
    r = api.client.delete(f"{BASE}/{inst}/links/{acct}")
    assert r.status_code == 200 and r.json() == {"settle": {"touched_entry_ids": [9], "error": None}}
    assert calls == [1]
    assert api.client.get(BASE).json()[0]["accounts"] == []
    error_of(api.client.delete(f"{BASE}/{inst}/links/{acct}"), 404, "not_found")


# ---- the catalog ---------------------------------------------------------------------------


class _DocStub:
    """A document importer: fetches, emits documents, ships no presets."""

    emits = frozenset({"documents"})

    redelivery = "replace"
    providers = frozenset({"paypal"})

    def validate_settings(self, settings) -> None:
        return None

    def fetch(self, settings, *, since, today):
        raise NotImplementedError


def test_the_catalog_lists_the_registered_importers_with_kind_emits_and_presets(make_api):
    api = make_api({"csv": SpyCsv(), "docs": _DocStub(), "bank": _FetchStub()})
    r = api.client.get("/api/importers")
    assert r.status_code == 200
    by_name = {e["name"]: e for e in r.json()}
    assert list(by_name) == ["bank", "csv", "docs"]  # by name
    csv = by_name["csv"]
    assert (csv["kind"], csv["emits"]) == ("file", ["transactions"])
    assert csv["presets"] == load_presets()  # the package data, as shipped
    assert (by_name["docs"]["kind"], by_name["docs"]["emits"], by_name["docs"]["presets"]) == (
        "fetch",
        ["documents"],
        {},
    )
    assert (by_name["bank"]["kind"], by_name["bank"]["emits"]) == ("fetch", ["transactions"])


def test_a_new_instance_takes_its_emits_from_the_catalog(make_api):
    api = make_api({"csv": SpyCsv(), "docs": _DocStub()})
    csv = api.client.post(BASE, json={"importer": "csv", "label": "Giro", "settings": PROFILE})
    assert (csv.json()["emits"], csv.json()["access"], csv.json()["owner_id"]) == (
        ["transactions"],
        "shared",
        None,
    )
    docs = api.client.post(BASE, json={"importer": "docs", "label": "PayPal", "settings": {}})
    assert docs.status_code == 201, docs.text
    assert (docs.json()["emits"], docs.json()["access"]) == (["documents"], "owner")
    assert docs.json()["owner_id"] is not None  # the creator
    shared = api.client.post(
        BASE, json={"importer": "docs", "label": "Shared", "settings": {}, "access": "shared"}
    )
    assert (shared.json()["access"], shared.json()["owner_id"]) == ("shared", None)
