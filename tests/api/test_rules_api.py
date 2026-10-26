"""Rules: list, get, create, update, delete, each write previewed (spec §5.9, architecture §4.1, D198)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.api.accounts_helpers import assert_envelope, q
from tests.api.conftest import login
from tests.api.dimension_helpers import counts
from tests.fixtures import ledger_seed as seed
from tests.fixtures import rule_seed as rs

RULES = "/api/ledger/rules"
BAD_IDS = [0, -1, 2**63, 10**20]


@pytest.fixture
def anna(client: TestClient) -> TestClient:
    login(client)
    return client


@pytest.fixture
def w(api_engine: Engine) -> dict[str, int]:
    with api_engine.begin() as conn:
        return {
            "acct": seed.account(conn, "Giro"),
            "cash": seed.account(conn, "Cash"),
            "food": seed.category(conn, "Food"),
            "fun": seed.category(conn, "Fun"),
            "rewe": rs.payee(conn, "Rewe"),
        }


def c(field: str, op: str, value: str) -> dict[str, str]:
    return {"field": field, "op": op, "value": value}


def body(w: dict[str, int], **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "Rewe",
        "sets": "category",
        "category_id": w["food"],
        "conditions": [c("counterparty_name", "equals", "REWE")],
    }
    base.update(kw)
    return {k: v for k, v in base.items() if v is not ...}


def create(client: TestClient, w: dict[str, int], count: int = 0, **kw: Any) -> int:
    r = client.post(RULES, json=body(w, expected_count=count, **kw))
    assert r.status_code == 201, r.text
    return int(r.json()["rule"]["id"])


def snapshot(engine: Engine) -> dict[str, Any]:
    with engine.connect() as conn:
        return counts(conn)


# ---- auth and ids ----------------------------------------------------------------------------

ROUTES = [
    ("get", RULES, None),
    ("get", f"{RULES}/1", None),
    (
        "post",
        RULES,
        {
            "name": "x",
            "sets": "payee",
            "payee_id": 1,
            "conditions": [c("purpose", "contains", "x")],
            "dry_run": True,
        },
    ),
    (
        "put",
        f"{RULES}/1",
        {"name": "x", "payee_id": 1, "conditions": [c("purpose", "contains", "x")], "dry_run": True},
    ),
    ("delete", f"{RULES}/1?dry_run=true", None),
]


@pytest.mark.parametrize(("method", "url", "payload"), ROUTES)
def test_every_route_requires_a_session(client: TestClient, method: str, url: str, payload: Any):
    assert_envelope(client.request(method, url, json=payload), 401, "unauthenticated")


@pytest.mark.parametrize("bad", BAD_IDS)
def test_ids_are_bounded(anna: TestClient, w: dict[str, int], bad: int):
    for method, url, payload in (
        ("get", f"{RULES}/{bad}", None),
        ("put", f"{RULES}/{bad}", body(w, dry_run=True)),
        ("delete", f"{RULES}/{bad}?dry_run=true", None),
        ("post", RULES, body(w, category_id=bad, dry_run=True)),
    ):
        assert_envelope(anna.request(method, url, json=payload), 422, "validation_error")


def test_paging_parameters_are_bounded(anna: TestClient, w: dict[str, int]):
    for query in ("limit=0", "limit=501", "offset=-1", "limit=x"):
        assert_envelope(anna.post(f"{RULES}?{query}", json=body(w, dry_run=True)), 422, "validation_error")
        assert_envelope(anna.delete(f"{RULES}/1?dry_run=true&{query}"), 422, "validation_error")
    assert anna.post(f"{RULES}?limit=500&offset=0", json=body(w, dry_run=True)).status_code == 200


# ---- create, read ----------------------------------------------------------------------------


def test_create_returns_the_rule_the_preview_and_the_settle_result(
    anna: TestClient, w: dict[str, int], api_engine: Engine
):
    with api_engine.begin() as conn:
        e = rs.new_entry(conn, w["acct"], counterparty_name="REWE")
    dry = anna.post(RULES, json=body(w, name="  Rewe  ", priority=7, dry_run=True))
    assert dry.status_code == 200  # nothing was created
    assert (
        dry.json()["rule"] is None
        and dry.json()["settle"] is None
        and dry.json()["settle_breakdown"] is None
        and dry.json()["dry_run"] is True
    )
    preview = dry.json()["preview"]
    assert preview["matches"]["total"] == 1 and preview["would_confirm"] == 1
    row = preview["matches"]["rows"][0]
    assert row["entry_id"] == e and row["amount"] == {"amount": -1000, "currency": "EUR"}
    assert row["confirmed"] is False and row["current_value"] is None and row["shadowed_by_rule_id"] is None
    assert row["source"] == {
        "amount": {"amount": -1000, "currency": "EUR"},
        "counterparty_name": "REWE", "counterparty_ref": None, "counterparty_bic": None, "purpose": None,
        "booking_text": None, "end_to_end_id": None, "mandate_ref": None, "instructed_amount": None,
        "source_format": "csv", "booking": None,
    }  # fmt: skip
    assert "counterparty_name" not in row  # no flat copy beside `source`
    r = anna.post(RULES, json=body(w, name="  Rewe  ", priority=7, expected_count=1))
    assert r.status_code == 201
    out = r.json()
    assert out["rule"] == {
        "id": out["rule"]["id"], "name": "Rewe", "sets": "category", "counter_account_id": None,
        "payee_id": None, "category_id": w["food"],
        "conditions": [{"field": "counterparty_name", "op": "equals", "value": "REWE"}], "priority": 7,
    }  # fmt: skip
    assert out["settle"] == {"touched_entry_ids": [e], "error": None}  # settling applied it
    assert out["settle_breakdown"] == {"total": 1, "this_rule": 1, "history": 0, "other_rules": 0, "other": 0}
    # the preview is the one the dry run showed: the rule as written, the entries before settling applied it
    assert out["preview"]["matches"]["total"] == 1 and out["preview"]["would_confirm"] == 1
    assert out["preview"]["different_value"]["total"] == 0  # settling replaces what it held: nothing to check
    assert q(api_engine, "SELECT category_id FROM ledger_entry WHERE id = :i", i=e)[0][0] == w["food"]
    assert anna.get(f"{RULES}/{out['rule']['id']}").json() == out["rule"]
    assert anna.get(RULES).json() == [out["rule"]]


def test_the_target_must_be_the_one_sets_names(anna: TestClient, w: dict[str, int], api_engine: Engine):
    before = snapshot(api_engine)
    for payload in (
        body(w, payee_id=w["rewe"]),  # a second target
        body(w, category_id=None),  # none
        body(w, sets="payee"),  # category_id for a payee rule
        body(w, sets="counter_account", category_id=None, payee_id=w["rewe"]),
    ):
        err = assert_envelope(anna.post(RULES, json={**payload, "dry_run": True}), 422, "invalid_rule")
        assert err["details"][0]["type"] == "invalid_rule"
    assert snapshot(api_engine) == before
    assert_envelope(anna.post(RULES, json=body(w, sets="nothing", dry_run=True)), 422, "validation_error")
    assert_envelope(anna.post(RULES, json=body(w, extra=1, dry_run=True)), 422, "validation_error")
    assert_envelope(anna.post(RULES, json=body(w, sets=...)), 422, "validation_error")


@pytest.mark.parametrize(
    ("kw", "field"),
    [
        ({"conditions": [c("purpose", "regex", "(SECRETPATTERN")]}, "conditions[0].value"),
        ({"conditions": [c("purpose", "regex", "SECRETPATTERN" + "a" * 200)]}, "conditions[0].value"),
        (
            {"conditions": [c("purpose", "contains", "ok"), c("mandate_ref", "regex", "SECRET(")]},
            "conditions[1].value",
        ),
        ({"conditions": []}, "conditions"),
        ({"conditions": [c("counterparty_name", "equals", " ")]}, "conditions[0].value"),
        ({"conditions": [c("counterparty_name", "equals", "")]}, "conditions[0].value"),
        ({"conditions": [c("SECRETFIELD", "equals", "x")]}, "conditions[0].field"),
        ({"conditions": [c("purpose", "SECRETOP", "x")]}, "conditions[0].op"),
        (
            {"sets": "payee", "category_id": None, "payee_id": 1, "conditions": [c("payee", "is", "1")]},
            "conditions[0].field",
        ),
        ({"conditions": [c("payee", "equals", "1")]}, "conditions[0].op"),
        ({"conditions": [c("payee", "regex", "1")]}, "conditions[0].op"),
        ({"conditions": [c("purpose", "is", "1")]}, "conditions[0].op"),
        (
            {"conditions": [c("purpose", "contains", "x"), c("payee", "is", "SECRETPATTERN")]},
            "conditions[1].value",
        ),
        ({"conditions": [c("payee", "is", "0")]}, "conditions[0].value"),
        ({"conditions": [c("payee", "is", "-3")]}, "conditions[0].value"),
        ({"conditions": [c("payee", "is", " ")]}, "conditions[0].value"),
    ],
)
def test_an_invalid_rule_is_422_invalid_rule_and_never_quotes_the_pattern(
    anna: TestClient, w: dict[str, int], kw: dict[str, Any], field: str
):
    r = anna.post(RULES, json=body(w, expected_count=0, **kw))
    err = assert_envelope(r, 422, "invalid_rule")
    assert err["details"][0]["location"] == ["body", field]
    assert "SECRETPATTERN" not in r.text


def test_conditions_round_trip_in_order_with_payee_conditions_among_them(anna: TestClient, w: dict[str, int]):
    conds = [
        c("purpose", "contains", " Miete "),  # stored as typed
        c("payee", "is", str(w["rewe"])),
        c("purpose", "regex", "^m.*e$"),
        c("counterparty_ref", "starts_with", "DE89 3704"),
    ]
    rid = create(anna, w, name="both", conditions=conds)
    assert anna.get(f"{RULES}/{rid}").json()["conditions"] == conds
    # a payee condition alone is a condition; several are allowed (they are ANDed)
    alone = create(anna, w, name="alone", conditions=[c("payee", "is", str(w["rewe"]))])
    assert anna.get(f"{RULES}/{alone}").json()["conditions"] == [c("payee", "is", str(w["rewe"]))]
    twice = [c("payee", "is", str(w["rewe"])), c("payee", "is", str(w["rewe"]))]
    assert create(anna, w, name="twice", conditions=twice)
    # a PUT replaces the whole list; absent means none, which is refused now
    r = anna.put(f"{RULES}/{rid}", json=body(w, name="both", conditions=[conds[1]], expected_count=0))
    assert r.status_code == 200 and r.json()["rule"]["conditions"] == [conds[1]]
    assert "condition_payee_id" not in r.json()["rule"]
    assert_envelope(
        anna.put(f"{RULES}/{rid}", json=body(w, name="both", conditions=[], dry_run=True)),
        422,
        "invalid_rule",
    )


def test_the_preview_of_a_rule_with_a_payee_condition(
    anna: TestClient, w: dict[str, int], api_engine: Engine
):
    with api_engine.begin() as conn:
        hit = rs.confirmed_entry(
            conn, w["acct"], category=w["food"], payee=w["rewe"], counterparty_name="REWE"
        )
        rs.confirmed_entry(conn, w["acct"], category=w["food"], counterparty_name="REWE")
    r = anna.post(
        RULES,
        json=body(
            w,
            conditions=[c("payee", "is", str(w["rewe"])), c("counterparty_name", "equals", "REWE")],
            dry_run=True,
        ),
    )
    assert r.status_code == 200, r.text
    assert [row["entry_id"] for row in r.json()["preview"]["matches"]["rows"]] == [hit]


def test_a_payee_condition_on_a_rule_that_does_not_set_a_category_is_refused(
    anna: TestClient, w: dict[str, int]
):
    r = anna.post(
        RULES,
        json=body(
            w,
            sets="payee",
            category_id=None,
            payee_id=w["rewe"],
            conditions=[c("purpose", "contains", "x"), c("payee", "is", str(w["rewe"]))],
            dry_run=True,
        ),
    )
    err = assert_envelope(r, 422, "invalid_rule")
    assert err["details"][0]["location"] == ["body", "conditions[1].field"]


@pytest.mark.parametrize(
    "bad",
    [
        {"conditions": "x"},
        {"conditions": [{"field": "purpose", "op": "equals"}]},
        {"conditions": [{"field": "purpose", "op": "equals", "value": 5}]},
        {"conditions": [{"field": "purpose", "op": "equals", "value": "x", "extra": 1}]},
        {"conditions": [c("purpose", "equals", "x" * 2001)]},
        {"conditions": [c("purpose", "equals", "x")] * 51},
        {"name_exact": "REWE"},  # the old flat fields are gone
    ],
)
def test_a_malformed_conditions_body_is_a_validation_error(
    anna: TestClient, w: dict[str, int], bad: dict[str, Any]
):
    assert_envelope(anna.post(RULES, json=body(w, dry_run=True, **bad)), 422, "validation_error")


def test_blank_name_and_negative_priority_bounds(anna: TestClient, w: dict[str, int]):
    for payload in (
        body(w, name="  "),
        body(w, name="x" * 201),
        body(w, priority=2**31),
        body(w, priority=1.5),
        body(w, expected_count=-1),
        body(w, name=...),
    ):
        assert_envelope(anna.post(RULES, json={**payload, "dry_run": True}), 422, "validation_error")


def test_duplicate_names_are_409_conflict(anna: TestClient, w: dict[str, int]):
    create(anna, w, name="Rent")
    err = assert_envelope(anna.post(RULES, json=body(w, name=" rENT ", dry_run=True)), 409, "conflict")
    assert err["details"] == {"reason": "duplicate_name"}


def test_stale_references_are_409_stale_reference_naming_the_field(anna: TestClient, w: dict[str, int]):
    for kw, field, entity in (
        ({"category_id": 999_999}, "category_id", "category"),
        ({"sets": "payee", "category_id": None, "payee_id": 999_999}, "payee_id", "payee"),
        (
            {"sets": "counter_account", "category_id": None, "counter_account_id": 999_999},
            "counter_account_id",
            "account",
        ),
        (
            {"conditions": [c("purpose", "contains", "x"), c("payee", "is", "999999")]},
            "conditions[1].value",
            "payee",
        ),
        (
            {"conditions": [c("purpose", "contains", "x"), c("account", "is", "999999")]},
            "conditions[1].value",
            "account",
        ),
    ):
        err = assert_envelope(anna.post(RULES, json=body(w, dry_run=True, **kw)), 409, "stale_reference")
        assert err["details"] == {"field": field, "entity": entity, "id": 999_999}


# ---- expected_count --------------------------------------------------------------------------


def test_a_real_write_needs_expected_count_and_a_moved_number_is_409(
    anna: TestClient, w: dict[str, int], api_engine: Engine
):
    with api_engine.begin() as conn:
        rs.new_entry(conn, w["acct"], counterparty_name="REWE")
    before = snapshot(api_engine)
    err = assert_envelope(anna.post(RULES, json=body(w)), 422, "validation_error")
    assert err["details"][0]["location"] == ["body", "expected_count"]
    err = assert_envelope(anna.post(RULES, json=body(w, expected_count=5)), 409, "conflict")
    assert err["details"] == {"reason": "filter_result_changed", "expected": 5, "actual": 1}
    assert snapshot(api_engine) == before
    rid = create(anna, w, count=1)
    assert_envelope(anna.put(f"{RULES}/{rid}", json=body(w, name="x")), 422, "validation_error")
    err = assert_envelope(
        anna.put(f"{RULES}/{rid}", json=body(w, name="x", expected_count=0)), 409, "conflict"
    )
    assert err["details"]["actual"] == 1
    assert_envelope(anna.delete(f"{RULES}/{rid}"), 422, "validation_error")
    err = assert_envelope(anna.delete(f"{RULES}/{rid}?expected_count=3"), 409, "conflict")
    assert err["details"] == {"reason": "filter_result_changed", "expected": 3, "actual": 1}
    assert q(api_engine, "SELECT count(*) FROM rule")[0][0] == 1


# ---- update ----------------------------------------------------------------------------------


def test_update_replaces_the_rule_and_never_changes_what_it_sets(
    anna: TestClient, w: dict[str, int], api_engine: Engine
):
    with api_engine.begin() as conn:
        done = rs.confirmed_entry(conn, w["acct"], category=w["fun"], counterparty_name="REWE")
    rid = create(anna, w, count=1)
    before = snapshot(api_engine)
    dry = anna.put(
        f"{RULES}/{rid}",
        json=body(
            w, category_id=w["fun"], conditions=[c("counterparty_name", "starts_with", "REW")], dry_run=True
        ),
    )
    assert (
        dry.status_code == 200
        and dry.json()["rule"]["category_id"] == w["fun"]
        and dry.json()["settle"] is None
    )
    assert dry.json()["preview"]["matches"]["total"] == 1
    assert snapshot(api_engine) == before
    other = anna.put(
        f"{RULES}/{rid}",
        json=body(w, sets="payee", category_id=None, payee_id=w["rewe"], expected_count=1),
    )
    assert_envelope(other, 422, "invalid_rule")
    r = anna.put(
        f"{RULES}/{rid}",
        json=body(
            w,
            sets="category",
            category_id=w["fun"],
            conditions=[c("counterparty_name", "starts_with", "REW")],
            expected_count=1,
        ),
    )
    assert r.status_code == 200
    rule = r.json()["rule"]
    assert (rule["category_id"], rule["conditions"], rule["sets"]) == (
        w["fun"],
        [c("counterparty_name", "starts_with", "REW")],
        "category",
    )
    assert r.json()["preview"]["different_value"]["total"] == 0  # the confirmed entry holds Fun already
    assert q(api_engine, "SELECT version FROM ledger_entry WHERE id = :i", i=done)[0][0] == 1
    assert_envelope(anna.put(f"{RULES}/999", json=body(w, dry_run=True)), 404, "not_found")
    assert_envelope(anna.get(f"{RULES}/999"), 404, "not_found")


def test_update_returns_list_b_of_the_entries_the_edit_stops_matching(
    anna: TestClient, w: dict[str, int], api_engine: Engine
):
    rid = create(anna, w, count=0, conditions=[c("counterparty_name", "starts_with", "REWE")])
    with api_engine.begin() as conn:
        lost = rs.confirmed_entry(
            conn,
            w["acct"],
            category=w["food"],
            keys={"type": rs.key(rid), "category": rs.key(rid)},
            counterparty_name="REWE CITY",
        )
    r = anna.put(
        f"{RULES}/{rid}",
        json=body(w, conditions=[c("counterparty_name", "starts_with", "REWE MARKT")], expected_count=0),
    )
    assert r.status_code == 200
    lost_key = r.json()["preview"]["lost_key"]
    assert lost_key["total"] == 1
    assert (lost_key["rows"][0]["entry_id"], lost_key["rows"][0]["keyed_fields"]) == (
        lost,
        ["type", "category"],
    )
    assert lost_key["rows"][0]["current_key"] == rs.key(rid)


# ---- delete ----------------------------------------------------------------------------------


def test_delete_previews_then_deletes_and_keys_stay(anna: TestClient, w: dict[str, int], api_engine: Engine):
    with api_engine.begin() as conn:
        rid = rs.rule(conn, "rewe", "category", w["food"], conditions=(rs.name_is("REWE"),))
        e = rs.confirmed_entry(
            conn,
            w["acct"],
            category=w["food"],
            keys={"type": rs.key(rid), "category": rs.key(rid)},
            counterparty_name="REWE",
        )
    before = snapshot(api_engine)
    dry = anna.delete(f"{RULES}/{rid}?dry_run=true")
    assert dry.status_code == 200
    d = dry.json()
    assert (d["dry_run"], d["deleted"], d["settle"], d["settle_breakdown"]) == (True, False, None, None)
    assert d["rule"]["id"] == rid and d["preview"]["lost_key"]["total"] == 1
    assert d["preview"]["lost_key"]["rows"][0]["entry_id"] == e
    assert snapshot(api_engine) == before
    r = anna.delete(f"{RULES}/{rid}?expected_count={d['preview']['matches']['total']}")
    assert r.status_code == 200 and r.json()["deleted"] is True and r.json()["settle"]["error"] is None
    assert r.json()["settle_breakdown"]["total"] == len(r.json()["settle"]["touched_entry_ids"])
    assert q(api_engine, "SELECT count(*) FROM rule")[0][0] == 0
    assert q(api_engine, "SELECT derivation -> 'category' FROM ledger_entry WHERE id = :i", i=e)[0][
        0
    ] == rs.key(rid)
    assert_envelope(anna.delete(f"{RULES}/{rid}?dry_run=true"), 404, "not_found")


def test_the_preview_rows_are_paged(anna: TestClient, w: dict[str, int], api_engine: Engine):
    with api_engine.begin() as conn:
        for _ in range(4):
            rs.confirmed_entry(conn, w["acct"], category=w["fun"], counterparty_name="REWE")
    r = anna.post(f"{RULES}?limit=3&offset=2", json=body(w, dry_run=True)).json()["preview"]
    assert r["matches"]["total"] == 4 and len(r["matches"]["rows"]) == 2
    assert r["different_value"]["total"] == 4 and len(r["different_value"]["rows"]) == 2


def test_a_deleted_payee_takes_its_rule_so_the_rule_is_gone_not_stale(
    anna: TestClient, w: dict[str, int], api_engine: Engine
):
    rid = create(anna, w, count=0, sets="payee", category_id=None, payee_id=w["rewe"], name="payee rule")
    assert anna.delete(f"/api/ledger/payees/{w['rewe']}").status_code == 200
    assert_envelope(anna.get(f"{RULES}/{rid}"), 404, "not_found")


def test_source_text_and_account_conditions_round_trip_and_an_account_condition_is_checked(
    anna: TestClient, w: dict[str, int]
):
    conditions = [c("source_text", "starts_with", "USB"), c("account", "is", str(w["acct"]))]
    rule_id = create(anna, w, conditions=conditions)
    assert anna.get(f"{RULES}/{rule_id}").json()["conditions"] == conditions
    # any rule may carry an account condition; its operator is `is`; its value an id
    ok = body(w, name="p", sets="payee", category_id=None, payee_id=w["rewe"], dry_run=True)
    assert anna.post(RULES, json={**ok, "conditions": [c("account", "is", "007")]}).status_code in (200, 409)
    err = assert_envelope(
        anna.post(RULES, json={**ok, "conditions": [c("account", "equals", "1")]}), 422, "invalid_rule"
    )
    assert err["details"][0]["location"] == ["body", "conditions[0].op"]
    err = assert_envelope(
        anna.post(RULES, json={**ok, "conditions": [c("account", "is", "abc")]}), 422, "invalid_rule"
    )
    assert err["details"][0]["location"] == ["body", "conditions[0].value"]
