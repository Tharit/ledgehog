"""Tag endpoints: CRUD, tagging one entry, applying a filter (architecture §4.1, plan B11-B15)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.api import create_app
from app.core.ledger import tags as tags_mod
from app.core.settle.settle import SettleResult
from tests.api.accounts_helpers import assert_checks_ok, assert_envelope, q
from tests.api.conftest import login
from tests.fixtures import ledger_seed as seed

TAGS = "/api/ledger/tags"
BAD_IDS = [0, -1, 2**63, 10**20]


@pytest.fixture
def anna(client: TestClient) -> TestClient:
    login(client)
    return client


@pytest.fixture
def acct(api_engine: Engine) -> int:
    with api_engine.begin() as conn:
        return seed.account(conn)


def add(engine: Engine, account_id: int, **kw: Any) -> int:
    with engine.begin() as conn:
        return seed.entry(conn, account_id, **kw)


def new_tag(client: TestClient, name: str = "Trip", **kw: Any) -> dict[str, Any]:
    r = client.post(TAGS, json={"name": name, **kw})
    assert r.status_code == 201, r.text
    return r.json()["tag"]  # type: ignore[no-any-return]


def memberships(engine: Engine) -> list[Any]:
    return q(engine, "SELECT ledger_entry_id, tag_id FROM ledger_entry_tag ORDER BY 1, 2")


# ---- auth and ids -----------------------------------------------------------------------------

ROUTES = [
    ("get", TAGS, None),
    ("post", TAGS, {"name": "x"}),
    ("put", f"{TAGS}/1", {"name": "x"}),
    ("delete", f"{TAGS}/1", None),
    ("post", f"{TAGS}/1/apply", {"from": "2026-03-01"}),
    ("put", "/api/ledger/entries/1/tags/1", None),
    ("delete", "/api/ledger/entries/1/tags/1", None),
]


@pytest.mark.parametrize(("method", "url", "body"), ROUTES)
def test_every_route_requires_a_session(client: TestClient, method: str, url: str, body: Any):
    assert_envelope(client.request(method, url, json=body), 401, "unauthenticated")


@pytest.mark.parametrize("bad", BAD_IDS)
@pytest.mark.parametrize(("method", "url", "body"), ROUTES[2:])
def test_path_ids_are_bounded(anna: TestClient, method: str, url: str, body: Any, bad: int):
    parts = url.split("/")
    for i, part in enumerate(parts):
        if part == "1":
            variant = parts.copy()
            variant[i] = str(bad)
            r = anna.request(method, "/".join(variant), json=body)
            err = assert_envelope(r, 422, "validation_error")
            assert any("path" in d["location"] for d in err["details"])


# ---- CRUD -------------------------------------------------------------------------------------


def test_create_list_update_delete(anna: TestClient, api_engine: Engine):
    r = anna.post(TAGS, json={"name": "  Trip ", "color": "teal"})
    assert r.status_code == 201
    body = r.json()
    t = body["tag"]
    assert body["settle"] == {"touched_entry_ids": [], "error": None}
    assert t == {
        "id": t["id"],
        "name": "Trip",
        "color": "teal",
        "starts_on": None,
        "ends_on": None,
        "entry_count": 0,
    }
    assert anna.get(TAGS).json() == {"tags": [t]}
    r = anna.put(f"{TAGS}/{t['id']}", json={"name": "Holiday"})
    assert (
        r.status_code == 200 and r.json()["tag"]["name"] == "Holiday" and r.json()["tag"]["color"] == "teal"
    )
    assert anna.put(f"{TAGS}/{t['id']}", json={"color": None}).json()["tag"]["color"] is None
    assert anna.put(f"{TAGS}/{t['id']}", json={}).json()["tag"]["name"] == "Holiday"  # absent keeps
    r = anna.delete(f"{TAGS}/{t['id']}")
    assert r.status_code == 200
    assert r.json() == {"removed_memberships": 0, "settle": {"touched_entry_ids": [], "error": None}}
    assert anna.get(TAGS).json() == {"tags": []}


def test_create_errors(anna: TestClient):
    new_tag(anna, "Trip")
    err = assert_envelope(anna.post(TAGS, json={"name": "tRIP"}), 409, "conflict")
    assert err["details"] == {"reason": "duplicate_name"}
    for body in ({"name": ""}, {"name": "   "}, {}, {"name": "x", "color": " "}, {"name": "x", "extra": 1}):
        assert_envelope(anna.post(TAGS, json=body), 422, "validation_error")
    assert len(anna.get(TAGS).json()["tags"]) == 1


def test_update_errors(anna: TestClient):
    new_tag(anna, "A")
    b = new_tag(anna, "B")
    err = assert_envelope(anna.put(f"{TAGS}/{b['id']}", json={"name": "a"}), 409, "conflict")
    assert err["details"] == {"reason": "duplicate_name"}
    assert_envelope(anna.put(f"{TAGS}/{b['id']}", json={"name": " "}), 422, "validation_error")
    assert_envelope(anna.put(f"{TAGS}/{b['id']}", json={"color": ""}), 422, "validation_error")
    assert_envelope(anna.put(f"{TAGS}/999", json={"name": "z"}), 404, "not_found")
    assert_envelope(anna.put(f"{TAGS}/999", json={}), 404, "not_found")


def test_delete_unknown_is_404_and_delete_counts_memberships(anna: TestClient, api_engine: Engine, acct: int):
    assert_envelope(anna.delete(f"{TAGS}/999"), 404, "not_found")
    t = new_tag(anna)
    for _ in range(3):
        e = add(api_engine, acct)
        anna.put(f"/api/ledger/entries/{e}/tags/{t['id']}")
    assert anna.delete(f"{TAGS}/{t['id']}").json()["removed_memberships"] == 3
    assert memberships(api_engine) == []
    assert q(api_engine, "SELECT 1 FROM ledger_entry") != []


def test_list_shows_spans_as_entries_are_tagged(anna: TestClient, api_engine: Engine, acct: int):
    t = new_tag(anna)
    e1 = add(api_engine, acct, on=date(2026, 1, 5))
    e2 = add(api_engine, acct, on=date(2026, 2, 9))
    for e in (e1, e2):
        anna.put(f"/api/ledger/entries/{e}/tags/{t['id']}")
    (row,) = anna.get(TAGS).json()["tags"]
    assert (row["starts_on"], row["ends_on"], row["entry_count"]) == ("2026-01-05", "2026-02-09", 2)
    anna.delete(f"/api/ledger/entries/{e1}/tags/{t['id']}")
    (row,) = anna.get(TAGS).json()["tags"]
    assert (row["starts_on"], row["ends_on"], row["entry_count"]) == ("2026-02-09", "2026-02-09", 1)


# ---- tag / untag one entry ---------------------------------------------------------------------


def test_tag_and_untag_one_entry_are_idempotent(anna: TestClient, api_engine: Engine, acct: int):
    a, b = new_tag(anna, "a")["id"], new_tag(anna, "b")["id"]
    e = add(api_engine, acct, flags=("unconfirmed",))
    before = q(api_engine, "SELECT version FROM ledger_entry")
    url = f"/api/ledger/entries/{e}/tags"
    r = anna.put(f"{url}/{b}")
    assert r.status_code == 200
    assert r.json() == {
        "entry": {"id": e, "tag_ids": [b]},
        "changed": True,
        "settle": r.json()["settle"],
    }
    assert anna.put(f"{url}/{b}").json()["changed"] is False
    assert anna.put(f"{url}/{a}").json()["entry"]["tag_ids"] == [a, b]
    r = anna.delete(f"{url}/{a}")
    assert (r.status_code, r.json()["changed"], r.json()["entry"]["tag_ids"]) == (200, True, [b])
    assert anna.delete(f"{url}/{a}").json()["changed"] is False
    assert q(api_engine, "SELECT version FROM ledger_entry") == before


def test_tagging_errors(anna: TestClient, api_engine: Engine, acct: int):
    t = new_tag(anna)["id"]
    e = add(api_engine, acct)
    with api_engine.begin() as conn:
        d = seed.derived(conn, acct)
    for method in ("put", "delete"):
        call = getattr(anna, method)
        err = assert_envelope(call(f"/api/ledger/entries/{d}/tags/{t}"), 409, "conflict")
        assert err["details"] == {"reason": "derived_entry"}
        assert_envelope(call(f"/api/ledger/entries/999/tags/{t}"), 404, "not_found")
        assert_envelope(call(f"/api/ledger/entries/{e}/tags/999"), 404, "not_found")
    assert memberships(api_engine) == []


def test_a_write_settles_once_and_a_failure_is_in_the_200_body(
    anna: TestClient, api_engine: Engine, acct: int, monkeypatch: pytest.MonkeyPatch
):
    calls: list[int] = []
    monkeypatch.setattr(
        tags_mod, "settle", lambda engine: calls.append(1) or SettleResult((4,), "settling failed")
    )
    t = new_tag(anna)["id"]
    e = add(api_engine, acct)
    r = anna.put(f"/api/ledger/entries/{e}/tags/{t}")
    assert r.status_code == 200
    assert r.json()["settle"] == {"touched_entry_ids": [4], "error": "settling failed"}
    assert len(calls) == 2  # the create and the tag
    assert memberships(api_engine) == [(e, t)]  # the write stood


# ---- apply ------------------------------------------------------------------------------------


def apply(client: TestClient, tid: int, /, **body: Any):
    return client.post(f"{TAGS}/{tid}/apply", json=body)


MAR = {"from": "2026-03-01", "to": "2026-03-31"}


def test_dry_run_then_confirm_with_expected_count(anna: TestClient, api_engine: Engine, acct: int):
    t = new_tag(anna)["id"]
    inside = [add(api_engine, acct, on=date(2026, 3, d)) for d in (2, 20)]
    add(api_engine, acct, on=date(2026, 4, 2))
    with api_engine.begin() as conn:
        seed.derived(conn, acct, on=date(2026, 3, 1))
    preview = apply(anna, t, **MAR, dry_run=True)
    assert preview.status_code == 200
    p = preview.json()
    assert p == {
        "dry_run": True,
        "selected": 3,
        "newly_tagged": 2,
        "already_tagged": 0,
        "skipped_derived": 1,
        "per_account": [{"account_id": acct, "newly_tagged": 2}],
        "span_before": {"starts_on": None, "ends_on": None, "entry_count": 0},
        "span_after": {"starts_on": "2026-03-02", "ends_on": "2026-03-20", "entry_count": 2},
        "entries": [],
        "settle": None,
    }
    assert memberships(api_engine) == []
    done = apply(anna, t, **MAR, expected_count=p["newly_tagged"])
    assert done.status_code == 200
    d = done.json()
    assert d["dry_run"] is False
    assert d["entries"] == [{"id": i, "tag_ids": [t]} for i in inside]
    assert d["settle"]["error"] is None
    assert {k: d[k] for k in ("selected", "newly_tagged", "already_tagged", "skipped_derived")} == {
        "selected": 3,
        "newly_tagged": 2,
        "already_tagged": 0,
        "skipped_derived": 1,
    }
    assert memberships(api_engine) == [(i, t) for i in inside]
    again = apply(anna, t, **MAR).json()
    assert (again["newly_tagged"], again["already_tagged"], again["per_account"]) == (0, 2, [])
    assert_checks_ok(anna)


def test_expected_count_mismatch_is_409_and_writes_nothing(anna: TestClient, api_engine: Engine, acct: int):
    t = new_tag(anna)["id"]
    add(api_engine, acct, on=date(2026, 3, 2))
    err = assert_envelope(apply(anna, t, **MAR, expected_count=5), 409, "conflict")
    assert err["details"] == {"reason": "filter_result_changed", "expected": 5, "actual": 1}
    assert memberships(api_engine) == []


def test_empty_filter_needs_all(anna: TestClient, api_engine: Engine, acct: int):
    t = new_tag(anna)["id"]
    add(api_engine, acct, on=date(2026, 1, 2))
    err = assert_envelope(apply(anna, t), 422, "validation_error")
    (detail,) = err["details"]
    assert (detail["location"], detail["type"]) == (["body", "all"], "empty_filter")
    assert_envelope(apply(anna, t, dry_run=True), 422, "validation_error")
    assert_envelope(apply(anna, t, all=False), 422, "validation_error")
    assert memberships(api_engine) == []
    r = apply(anna, t, all=True)
    assert r.status_code == 200 and r.json()["newly_tagged"] == 1


def test_filter_vocabulary_matches_the_list(anna: TestClient, api_engine: Engine, acct: int):
    with api_engine.begin() as conn:
        other = seed.account(conn, "B")
        root = seed.category(conn, "Living")
        kid = seed.category(conn, "Food", root)
        p = seed.payee(conn, "Pizzeria")
        other_tag = seed.tag(conn, "x")
        hit = seed.entry(
            conn, acct, on=date(2026, 3, 10), category_id=kid, payee_id=p, amount=-700,
            description="Lunch", tags=(other_tag,),
        )  # fmt: skip
        seed.entry(conn, other, on=date(2026, 3, 10), category_id=kid, payee_id=p, amount=-700)
        seed.entry(conn, acct, on=date(2026, 3, 10), amount=-700, description="Lunch")
    t = new_tag(anna)["id"]
    body = {
        "from": "2026-03-01",
        "to": "2026-03-31",
        "account_id": [acct],
        "category_id": [root],
        "category_descendants": True,
        "payee_id": [p],
        "tag_id": [other_tag],
        "amount_min": 100,
        "amount_max": 1000,
        "currency": "EUR",
        "direction": "out",
        "q": "lunch",
        "type": ["flow"],
    }
    r = apply(anna, t, **body)
    assert r.status_code == 200, r.text
    assert memberships(api_engine) == [(hit, other_tag), (hit, t)]
    listed = anna.get("/api/ledger/entries", params={**body, "from": "2026-03-01"}).json()
    assert [e["id"] for e in listed["entries"]] == [hit]  # same filter, same set


def test_uncategorised_flag_and_unreviewed_selection(anna: TestClient, api_engine: Engine, acct: int):
    t = new_tag(anna)["id"]
    flagged = add(api_engine, acct, on=date(2026, 3, 2), flags=("unclassified",))
    add(api_engine, acct, on=date(2026, 3, 2))
    assert apply(anna, t, flag=["unclassified"]).json()["newly_tagged"] == 1
    assert memberships(api_engine) == [(flagged, t)]


def test_filter_validation_is_shared_with_the_list(anna: TestClient, api_engine: Engine, acct: int):
    t = new_tag(anna)["id"]
    err = assert_envelope(apply(anna, t, amount_min=100), 422, "validation_error")
    assert err["details"][0]["location"] == ["body", "currency"]
    assert_envelope(apply(anna, t, **{"from": "2026-04-01", "to": "2026-03-01"}), 422, "validation_error")
    assert_envelope(apply(anna, t, amount_min=5, amount_max=1, currency="EUR"), 422, "validation_error")
    for bad in (
        {"direction": "sideways"},
        {"type": ["nope"]},
        {"flag": ["nope"]},
        {"q": ""},
        {"account_id": [0]},
        {"unknown": 1},
        {"expected_count": -1},
        {"currency": "eu", "amount_min": 1},
    ):
        assert_envelope(apply(anna, t, **bad), 422, "validation_error")
    assert memberships(api_engine) == []


def test_apply_to_an_unknown_tag_is_404(anna: TestClient):
    assert_envelope(apply(anna, 999, **MAR), 404, "not_found")


def test_apply_settles_once_and_reports_a_failure_in_the_body(
    anna: TestClient, api_engine: Engine, acct: int, monkeypatch: pytest.MonkeyPatch
):
    t = new_tag(anna)["id"]
    add(api_engine, acct, on=date(2026, 3, 2))
    calls: list[int] = []
    monkeypatch.setattr(tags_mod, "settle", lambda e: calls.append(1) or SettleResult((), "settling failed"))
    r = apply(anna, t, **MAR)
    assert r.status_code == 200 and r.json()["settle"]["error"] == "settling failed"
    assert calls == [1]
    apply(anna, t, **MAR, dry_run=True)
    assert calls == [1]  # a preview settles nothing


# ---- schema -----------------------------------------------------------------------------------


def test_responses_are_typed_in_the_openapi_schema(api_config, api_engine):
    schema = create_app(api_config, api_engine).openapi()
    expected = {
        ("/api/ledger/tags", "get"): ("200", "TagsOut"),
        ("/api/ledger/tags", "post"): ("201", "TagWriteOut"),
        ("/api/ledger/tags/{tag_id}", "put"): ("200", "TagWriteOut"),
        ("/api/ledger/tags/{tag_id}", "delete"): ("200", "TagDeleteOut"),
        ("/api/ledger/tags/{tag_id}/apply", "post"): ("200", "TagApplyOut"),
        ("/api/ledger/entries/{entry_id}/tags/{tag_id}", "put"): ("200", "EntryTagsOut"),
        ("/api/ledger/entries/{entry_id}/tags/{tag_id}", "delete"): ("200", "EntryTagsOut"),
    }
    for (path, method), (status, model) in expected.items():
        ref = schema["paths"][path][method]["responses"][status]["content"]["application/json"]["schema"]
        assert ref == {"$ref": f"#/components/schemas/{model}"}, (path, method)
    ids = {schema["paths"][p][m]["operationId"] for (p, m) in expected}
    assert len(ids) == 7  # every operation has its own name
    body = schema["components"]["schemas"]["TagApplyBody"]
    assert body["additionalProperties"] is False
    assert {"from", "to", "account_id", "dry_run", "expected_count", "all"} <= set(body["properties"])
