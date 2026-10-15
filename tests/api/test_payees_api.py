"""Payee writes: create, update, delete, merge (spec §3.6, architecture §4.1, D200-D202)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.api import create_app
from app.core.ledger import payees as payee_mod
from app.core.settle.settle import SettleResult
from app.utils.db.locks import WriteConflict
from tests.api.accounts_helpers import assert_checks_ok, assert_envelope, q
from tests.api.conftest import login
from tests.api.dimension_helpers import counts, rule
from tests.fixtures import ledger_seed as seed

PAYEES = "/api/ledger/payees"
BAD_IDS = [0, -1, 2**63, 10**20]


@pytest.fixture
def anna(client: TestClient) -> TestClient:
    login(client)
    return client


@pytest.fixture
def acct(api_engine: Engine) -> int:
    with api_engine.begin() as conn:
        return seed.account(conn)


ENTRY_STATE = "SELECT id, derivation, review_flags, type, amount, category_id FROM ledger_entry ORDER BY id"


def make(client: TestClient, name: str, **kw: Any) -> dict[str, Any]:
    r = client.post(PAYEES, json={"name": name, **kw})
    assert r.status_code == 201, r.text
    return r.json()["payee"]  # type: ignore[no-any-return]


def merge(client: TestClient, src: int, into: int, **body: Any):
    return client.post(f"{PAYEES}/{src}/merge", json={"into": into, **body})


def payee_ids(engine: Engine) -> set[int]:
    return {r.id for r in q(engine, "SELECT id FROM payee")}


ROUTES = [
    ("post", PAYEES, {"name": "x"}),
    ("put", f"{PAYEES}/1", {"name": "x"}),
    ("delete", f"{PAYEES}/1", None),
    ("post", f"{PAYEES}/1/merge", {"into": 2, "dry_run": True}),
]


@pytest.mark.parametrize(("method", "url", "body"), ROUTES)
def test_every_route_requires_a_session(client: TestClient, method: str, url: str, body: Any):
    assert_envelope(client.request(method, url, json=body), 401, "unauthenticated")


@pytest.mark.parametrize("bad", BAD_IDS)
def test_ids_are_bounded(anna: TestClient, bad: int):
    for method, url, body in (
        ("put", f"{PAYEES}/{bad}", {"name": "x"}),
        ("delete", f"{PAYEES}/{bad}", None),
        ("post", f"{PAYEES}/{bad}/merge", {"into": 1}),
        ("post", f"{PAYEES}/1/merge", {"into": bad}),
    ):
        assert_envelope(anna.request(method, url, json=body), 422, "validation_error")


# ---- create / update --------------------------------------------------------------------------


def test_create_list_update(anna: TestClient):
    r = anna.post(
        PAYEES,
        json={
            "name": " Amazon ",
            "note": "n",
            "icon": "cart",
            "color": "blue",
            "document_provider": "amazon",
        },
    )
    assert r.status_code == 201
    body = r.json()
    p = body["payee"]
    assert body["settle"] == {"touched_entry_ids": [], "error": None}
    assert p == {
        "id": p["id"], "name": "Amazon", "icon": "cart", "color": "blue", "note": "n",
        "document_provider": "amazon",
    }  # fmt: skip
    assert anna.get(PAYEES).json() == {"payees": [p]}  # GET returns document_provider
    r = anna.put(f"{PAYEES}/{p['id']}", json={"name": "AMZ", "document_provider": None, "note": "m"})
    assert r.status_code == 200
    assert r.json()["payee"] == p | {"name": "AMZ", "document_provider": None, "note": "m"}
    assert anna.put(f"{PAYEES}/{p['id']}", json={}).json()["payee"]["icon"] == "cart"  # absent keeps
    cleared = anna.put(f"{PAYEES}/{p['id']}", json={"icon": None, "color": None}).json()["payee"]
    assert (cleared["icon"], cleared["color"]) == (None, None)
    assert make(anna, "Bare")["document_provider"] is None


def test_errors_duplicates_blank_and_unknown(anna: TestClient):
    a = make(anna, "Aldi")
    b = make(anna, "Bakery")
    err = assert_envelope(anna.post(PAYEES, json={"name": "aLDI"}), 409, "conflict")
    assert err["details"] == {"reason": "duplicate_name"}
    err = assert_envelope(anna.put(f"{PAYEES}/{b['id']}", json={"name": "aldi "}), 409, "conflict")
    assert err["details"] == {"reason": "duplicate_name"}
    assert anna.put(f"{PAYEES}/{a['id']}", json={"name": "ALDI"}).status_code == 200  # itself
    for bad in (
        {"name": " "},
        {},
        {"name": "x", "icon": " "},
        {"name": "x", "extra": 1},
        {"name": "x", "color": ""},
    ):
        assert_envelope(anna.post(PAYEES, json=bad), 422, "validation_error")
    assert_envelope(anna.put(f"{PAYEES}/999", json={"name": "z"}), 404, "not_found")
    assert_envelope(anna.put(f"{PAYEES}/999", json={}), 404, "not_found")
    assert len(anna.get(PAYEES).json()["payees"]) == 2


# ---- delete -----------------------------------------------------------------------------------


@pytest.fixture
def referenced(anna: TestClient, api_engine: Engine, acct: int) -> dict[str, int]:
    """Payee `used` (entries), `ruled` (a rule sets it, another has a payee condition on it), `free`."""
    used, ruled, free = (make(anna, n)["id"] for n in ("Used", "Ruled", "Free"))
    with api_engine.begin() as conn:
        cat = seed.category(conn, "C")
        seed.entry(conn, acct, payee_id=used)
        seed.entry(conn, acct, payee_id=used)
        sets = rule(conn, "sets-ruled", payee_id=ruled)
        cond = rule(conn, "cond-ruled", category_id=cat, condition_payee_id=ruled)
        unrelated = rule(conn, "other", payee_id=used)
    return {"used": used, "ruled": ruled, "free": free, "sets": sets, "cond": cond, "other": unrelated}


def test_delete_dry_run_lists_the_rules_and_writes_nothing(
    anna: TestClient, api_engine: Engine, referenced: dict[str, int]
):
    with api_engine.begin() as conn:
        before = counts(conn)
    r = anna.delete(f"{PAYEES}/{referenced['ruled']}", params={"dry_run": "true"})
    assert r.status_code == 200
    d = r.json()
    assert (d["dry_run"], d["deletable"], d["deleted"], d["settle"]) == (True, True, False, None)
    assert d["rules"] == [{"id": referenced["sets"], "name": "sets-ruled", "sets": "payee", "role": "sets"}]
    assert d["dangling_rules"] == [  # left alone by the delete, and never matching afterwards
        {"id": referenced["cond"], "name": "cond-ruled", "sets": "category", "role": "condition"}
    ]
    assert d["deleted_rule_ids"] == []
    d = anna.delete(f"{PAYEES}/{referenced['used']}", params={"dry_run": "true"}).json()
    assert (d["deletable"], d["held"]) == (False, {"entries": 2})  # a refusal is shown, not an error
    with api_engine.begin() as conn:
        assert counts(conn) == before


def test_delete_takes_the_rules_that_set_it_and_leaves_the_ones_whose_condition_names_it(
    anna: TestClient, api_engine: Engine, referenced: dict[str, int]
):
    r = anna.delete(f"{PAYEES}/{referenced['ruled']}")
    assert r.status_code == 200
    d = r.json()
    assert (d["deleted"], d["dry_run"], d["settle"]["error"]) == (True, False, None)
    assert d["deleted_rule_ids"] == [referenced["sets"]]
    assert [x["id"] for x in d["rules"]] == d["deleted_rule_ids"]
    assert [x["id"] for x in d["dangling_rules"]] == [referenced["cond"]]
    left = [r.id for r in q(api_engine, "SELECT id FROM rule ORDER BY id")]
    assert left == sorted([referenced["cond"], referenced["other"]])  # the condition rule stays
    assert referenced["ruled"] not in payee_ids(api_engine)
    assert anna.delete(f"{PAYEES}/{referenced['free']}").json()["deleted_rule_ids"] == []
    assert_envelope(anna.delete(f"{PAYEES}/{referenced['free']}"), 404, "not_found")


def test_a_payee_an_entry_references_is_refused(
    anna: TestClient, api_engine: Engine, referenced: dict[str, int]
):
    err = assert_envelope(anna.delete(f"{PAYEES}/{referenced['used']}"), 409, "conflict")
    assert err["details"] == {"reason": "payee_in_use", "held": {"entries": 2}}
    assert referenced["used"] in payee_ids(api_engine)
    assert q(api_engine, "SELECT count(*) FROM rule") == [(3,)]  # its rule stayed


# ---- merge ------------------------------------------------------------------------------------


@pytest.fixture
def pair(anna: TestClient, api_engine: Engine, acct: int) -> dict[str, int]:
    src = make(anna, "Amazon EU", note="src", icon="a", color="red", document_provider="amazon")["id"]
    tgt = make(anna, "Amazon", note="tgt", icon="b", color="blue")["id"]
    with api_engine.begin() as conn:
        cat = seed.category(conn, "Shop")
        for _ in range(3):
            seed.entry(conn, acct, payee_id=src)
        seed.entry(conn, acct, payee_id=tgt)
        seed.entry(conn, acct)  # no payee
        sets = rule(conn, "sets-src", payee_id=src)
        cond = rule(conn, "cond-src", category_id=cat, condition_payee_id=src)
        keep = rule(conn, "cond-tgt", category_id=cat, condition_payee_id=tgt)
    return {"src": src, "tgt": tgt, "sets": sets, "cond": cond, "keep": keep}


def test_merge_dry_run_previews_the_repointing_and_warns_about_the_provider(
    anna: TestClient, api_engine: Engine, pair: dict[str, int]
):
    with api_engine.begin() as conn:
        before = counts(conn)
    r = merge(anna, pair["src"], pair["tgt"], dry_run=True)
    assert r.status_code == 200, r.text
    p = r.json()
    assert (p["dry_run"], p["entry_count"], p["entry_ids"], p["settle"]) == (True, 3, [], None)
    assert p["setting_rule_ids"] == [pair["sets"]] and p["condition_rule_ids"] == [pair["cond"]]
    assert (p["document_provider_lost"], p["source_document_provider"]) == (True, "amazon")
    assert p["target"]["name"] == "Amazon" and p["source_id"] == pair["src"]
    with api_engine.begin() as conn:
        assert counts(conn) == before


def test_provider_warning_only_when_something_is_lost(anna: TestClient, api_engine: Engine):
    a = make(anna, "A", document_provider="paypal")["id"]
    b = make(anna, "B", document_provider="paypal")["id"]
    c = make(anna, "C")["id"]
    d = make(anna, "D", document_provider="amazon")["id"]
    assert merge(anna, a, b, dry_run=True).json()["document_provider_lost"] is False  # same
    assert merge(anna, c, a, dry_run=True).json()["document_provider_lost"] is False  # source has none
    assert merge(anna, a, c, dry_run=True).json()["document_provider_lost"] is True  # target has none
    assert merge(anna, a, d, dry_run=True).json()["document_provider_lost"] is True  # a different one


def test_merge_repoints_entries_and_rules_under_the_settling_flag(
    anna: TestClient, api_engine: Engine, pair: dict[str, int], monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(payee_mod, "settle", lambda engine: SettleResult())  # measure the merge alone
    with api_engine.begin() as conn:
        conn.execute(text('UPDATE ledger_entry SET derivation = \'{"payee_id": {"pass": "user"}}\'::jsonb'))
        before = conn.execute(text(ENTRY_STATE)).all()
        versions_before = dict(conn.execute(text("SELECT id, version FROM ledger_entry")).all())
        rules_before = conn.execute(text("SELECT id, name, sets, conditions FROM rule ORDER BY id")).all()
    r = merge(anna, pair["src"], pair["tgt"], expected_count=3)
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["dry_run"], d["entry_count"], len(d["entry_ids"]), d["settle"]["error"]) == (False, 3, 3, None)
    assert d["target"] == {
        "id": pair["tgt"], "name": "Amazon", "icon": "b", "color": "blue", "note": "tgt",
        "document_provider": None,
    }  # fmt: skip
    assert d["document_provider_lost"] is True  # the target's attributes won
    assert payee_ids(api_engine) == {pair["tgt"]}
    with api_engine.begin() as conn:
        assert {r.payee_id for r in conn.execute(text("SELECT payee_id FROM ledger_entry"))} == {
            pair["tgt"],
            None,
        }
        after = conn.execute(text(ENTRY_STATE)).all()
        by_name = {
            r.name: (r.payee_id, [c["value"] for c in r.conditions if c["field"] == "payee"])
            for r in conn.execute(text("SELECT name, payee_id, conditions FROM rule"))
        }
        rules_after = conn.execute(text("SELECT id, name, sets, conditions FROM rule ORDER BY id")).all()
        versions_after = dict(conn.execute(text("SELECT id, version FROM ledger_entry")).all())
    assert after == before  # keys and flags untouched
    bumped = {i for i, v in versions_after.items() if v != versions_before[i]}
    assert bumped == set(d["entry_ids"]) and bumped  # the repointed entries bump, no others
    # only the rule whose payee condition named the source changed: the element rewritten in place
    tgt = str(pair["tgt"])
    assert [(r.id, r.name, r.sets) for r in rules_after] == [(r.id, r.name, r.sets) for r in rules_before]
    changed = {r.id: r.conditions for r in rules_after if r not in rules_before}
    assert changed == {
        pair["cond"]: [
            {"field": "counterparty_ref", "op": "equals", "value": "ref"},
            {"field": "payee", "op": "is", "value": tgt},
        ]
    }
    assert by_name == {"sets-src": (pair["tgt"], []), "cond-src": (None, [tgt]), "cond-tgt": (None, [tgt])}
    assert_checks_ok(anna)


def test_merge_errors(anna: TestClient, api_engine: Engine, pair: dict[str, int]):
    err = assert_envelope(merge(anna, pair["src"], pair["src"], dry_run=True), 422, "validation_error")
    assert err["details"][0]["location"] == ["body", "into"]
    assert_envelope(merge(anna, 999, pair["tgt"], dry_run=True), 404, "not_found")
    err = assert_envelope(merge(anna, pair["src"], 999, dry_run=True), 409, "stale_reference")
    assert err["details"] == {"field": "into", "entity": "payee", "id": 999}
    err = assert_envelope(merge(anna, pair["src"], pair["tgt"]), 422, "validation_error")
    assert err["details"][0]["location"] == ["body", "expected_count"]
    with api_engine.begin() as conn:
        before = counts(conn)
    err = assert_envelope(merge(anna, pair["src"], pair["tgt"], expected_count=1), 409, "conflict")
    assert err["details"] == {"reason": "filter_result_changed", "expected": 1, "actual": 3}
    with api_engine.begin() as conn:
        assert counts(conn) == before


def test_a_write_naming_the_merged_payee_is_a_stale_reference_and_the_net_catches_the_rest(
    anna: TestClient, api_engine: Engine, pair: dict[str, int], acct: int
):
    merge(anna, pair["src"], pair["tgt"], expected_count=3)
    assert_envelope(merge(anna, pair["tgt"], pair["src"], dry_run=True), 409, "stale_reference")
    assert_envelope(
        anna.put(f"{PAYEES}/{pair['src']}", json={"name": "z"}), 404, "not_found"
    )  # the path names it
    # any write whose foreign key now points nowhere is the same conflict, whatever route it took
    app = anna.app

    @app.get("/api/_boom/{payee_id}")  # type: ignore[attr-defined]
    def boom(payee_id: int):
        with api_engine.begin() as conn:
            seed.entry(conn, acct, payee_id=payee_id)

    err = assert_envelope(anna.get(f"/api/_boom/{pair['src']}"), 409, "stale_reference")
    assert err["details"]["field"] == "payee_id" and err["details"]["entity"] == "payee"
    assert err["details"]["id"] == pair["src"]


def test_a_lost_deadlock_is_a_409_try_again(anna: TestClient, monkeypatch: pytest.MonkeyPatch):
    def boom(*a: Any, **k: Any) -> None:
        raise WriteConflict

    monkeypatch.setattr("app.api.routers.payees.merge_payee", boom)
    assert_envelope(merge(anna, 1, 2, dry_run=True), 409, "try_again")


def test_every_write_settles_after_commit_and_a_failure_is_in_the_200_body(
    anna: TestClient, api_engine: Engine, pair: dict[str, int], monkeypatch: pytest.MonkeyPatch
):
    seen: list[int] = []

    def fake(engine: Engine) -> SettleResult:
        seen.append(len(payee_ids(engine)))
        return SettleResult((9,), "settling failed")

    monkeypatch.setattr(payee_mod, "settle", fake)
    assert merge(anna, pair["src"], pair["tgt"], dry_run=True).json()["settle"] is None
    anna.delete(f"{PAYEES}/{pair['src']}", params={"dry_run": "true"})
    assert seen == []  # previews settle nothing
    r = merge(anna, pair["src"], pair["tgt"], expected_count=3)
    assert r.json()["settle"] == {"touched_entry_ids": [9], "error": "settling failed"}
    assert seen == [1]
    new = anna.post(PAYEES, json={"name": "N"})
    assert new.status_code == 201 and new.json()["settle"]["error"] == "settling failed"
    assert (
        anna.put(f"{PAYEES}/{new.json()['payee']['id']}", json={"document_provider": "paypal"}).status_code
        == 200
    )
    assert anna.delete(f"{PAYEES}/{new.json()['payee']['id']}").json()["settle"]["error"] == "settling failed"
    assert len(seen) == 4


# ---- schema -----------------------------------------------------------------------------------


def test_responses_are_typed_in_the_openapi_schema(api_config: Any, api_engine: Engine):
    schema = create_app(api_config, api_engine).openapi()
    expected = {
        (PAYEES, "post"): ("201", "PayeeWriteOut"),
        (f"{PAYEES}/{{payee_id}}", "put"): ("200", "PayeeWriteOut"),
        (f"{PAYEES}/{{payee_id}}", "delete"): ("200", "PayeeDeleteOut"),
        (f"{PAYEES}/{{payee_id}}/merge", "post"): ("200", "PayeeMergeOut"),
        (PAYEES, "get"): ("200", "PayeesOut"),
    }
    for (path, method), (status, model) in expected.items():
        ref = schema["paths"][path][method]["responses"][status]["content"]["application/json"]["schema"]
        assert ref == {"$ref": f"#/components/schemas/{model}"}, (path, method)
    assert "document_provider" in schema["components"]["schemas"]["PayeeOut"]["properties"]
    ops = {schema["paths"][p][m]["operationId"] for (p, m) in expected if m != "get"}
    assert ops == {"create_ledger_payee", "update_ledger_payee", "delete_ledger_payee", "merge_ledger_payee"}
