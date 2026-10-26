"""Category writes: create, update, delete, merge (spec §3.5, architecture §4.1, D200-D202)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.api import create_app
from app.core.ledger import categories as cat_mod
from app.core.settle.settle import SettleResult
from app.utils.db.locks import WriteConflict
from tests.api.accounts_helpers import assert_checks_ok, assert_envelope, q
from tests.api.conftest import login
from tests.api.dimension_helpers import counts, rule
from tests.fixtures import ledger_seed as seed

CATS = "/api/ledger/categories"
BAD_IDS = [0, -1, 2**63, 10**20]


@pytest.fixture
def anna(client: TestClient) -> TestClient:
    login(client)
    return client


@pytest.fixture
def acct(api_engine: Engine) -> int:
    with api_engine.begin() as conn:
        return seed.account(conn)


ENTRY_STATE = "SELECT id, derivation, review_flags, type, amount, payee_id FROM ledger_entry ORDER BY id"


def make(client: TestClient, name: str, parent: int | None = None, kind: str | None = None, **kw: Any) -> int:
    body: dict[str, Any] = {"name": name, **kw}
    if parent is not None:
        body["parent_id"] = parent
    if kind is not None:
        body["kind"] = kind
    r = client.post(CATS, json=body)
    assert r.status_code == 201, r.text
    return int(r.json()["category"]["id"])


def merge(client: TestClient, src: int, into: int, **body: Any):
    return client.post(f"{CATS}/{src}/merge", json={"into": into, **body})


def names(engine: Engine) -> dict[int, tuple[str, int | None]]:
    return {r.id: (r.name, r.parent_id) for r in q(engine, "SELECT id, name, parent_id FROM category")}


# ---- auth and ids -----------------------------------------------------------------------------

ROUTES = [
    ("post", CATS, {"name": "x", "kind": "expense"}),
    ("put", f"{CATS}/1", {"name": "x"}),
    ("delete", f"{CATS}/1", None),
    ("post", f"{CATS}/1/merge", {"into": 2, "dry_run": True}),
]


@pytest.mark.parametrize(("method", "url", "body"), ROUTES)
def test_every_route_requires_a_session(client: TestClient, method: str, url: str, body: Any):
    assert_envelope(client.request(method, url, json=body), 401, "unauthenticated")


@pytest.mark.parametrize("bad", BAD_IDS)
def test_ids_are_bounded(anna: TestClient, bad: int):
    for method, url, body in (
        ("put", f"{CATS}/{bad}", {"name": "x"}),
        ("delete", f"{CATS}/{bad}", None),
        ("post", f"{CATS}/{bad}/merge", {"into": 1}),
        ("post", f"{CATS}/1/merge", {"into": bad}),
        ("put", f"{CATS}/1", {"parent_id": bad}),
        ("post", CATS, {"name": "x", "parent_id": bad}),
    ):
        assert_envelope(anna.request(method, url, json=body), 422, "validation_error")


# ---- create -----------------------------------------------------------------------------------


def test_create_top_level_and_child(anna: TestClient):
    r = anna.post(CATS, json={"name": "  Living ", "kind": "expense", "icon": "home", "color": "teal"})
    assert r.status_code == 201
    body = r.json()
    root = body["category"]
    assert body["settle"] == {"touched_entry_ids": [], "error": None}
    assert root == {
        "id": root["id"], "parent_id": None, "name": "Living", "kind": "expense", "sort_order": 0,
        "icon": "home", "color": "teal",
    }  # fmt: skip
    child = anna.post(CATS, json={"name": "Food", "parent_id": root["id"], "sort_order": 3}).json()[
        "category"
    ]
    assert (child["kind"], child["parent_id"], child["sort_order"]) == ("expense", root["id"], 3)
    assert (child["icon"], child["color"]) == (None, None)  # null = inherit; the client resolves it
    again = anna.post(CATS, json={"name": "Drinks", "parent_id": root["id"], "kind": "expense"})
    assert again.status_code == 201  # repeating the parent's kind is fine
    assert [c["name"] for c in anna.get(CATS).json()["categories"]] == ["Living", "Drinks", "Food"]


def test_kind_mismatch_is_422_and_a_top_level_needs_a_kind(anna: TestClient):
    root = make(anna, "Pay", kind="income")
    err = assert_envelope(
        anna.post(CATS, json={"name": "x", "parent_id": root, "kind": "expense"}), 422, "validation_error"
    )
    assert err["details"][0]["location"] == ["body", "kind"]
    err = assert_envelope(anna.post(CATS, json={"name": "x"}), 422, "validation_error")
    assert err["details"][0]["location"] == ["body", "kind"]
    for bad in (
        {"name": " ", "kind": "income"},
        {"name": "x", "kind": "other"},
        {"name": "x", "kind": "income", "icon": " "},
        {"name": "x", "kind": "income", "extra": 1},
        {"kind": "income"},
        {"name": "x", "kind": "income", "sort_order": 1.5},
    ):
        assert_envelope(anna.post(CATS, json=bad), 422, "validation_error")
    assert len(anna.get(CATS).json()["categories"]) == 1


def test_duplicate_names_are_per_sibling_set_and_case_insensitive(anna: TestClient):
    a, b = make(anna, "A", kind="expense"), make(anna, "B", kind="expense")
    make(anna, "Food", a)
    err = assert_envelope(anna.post(CATS, json={"name": "fOOD ", "parent_id": a}), 409, "conflict")
    assert err["details"] == {"reason": "duplicate_name"}
    assert_envelope(anna.post(CATS, json={"name": "a", "kind": "expense"}), 409, "conflict")
    make(anna, "Food", b)  # another sibling set
    make(anna, "A", kind="income")  # another kind's top level


def test_create_under_a_missing_parent_is_a_stale_reference(anna: TestClient):
    err = assert_envelope(anna.post(CATS, json={"name": "x", "parent_id": 999}), 409, "stale_reference")
    assert err["details"] == {"field": "parent_id", "entity": "category", "id": 999}


# ---- update -----------------------------------------------------------------------------------


def test_update_fields_and_absent_fields_stay(anna: TestClient):
    root = make(anna, "Living", kind="expense", icon="home", color="teal")
    other = make(anna, "Fun", kind="expense")
    kid = make(anna, "Food", root)
    r = anna.put(
        f"{CATS}/{kid}", json={"name": " Eating ", "sort_order": 7, "icon": "fork", "parent_id": other}
    )
    assert r.status_code == 200
    assert r.json()["category"] == {
        "id": kid, "parent_id": other, "name": "Eating", "kind": "expense", "sort_order": 7,
        "icon": "fork", "color": None,
    }  # fmt: skip
    assert r.json()["settle"] == {"touched_entry_ids": [], "error": None}
    assert anna.put(f"{CATS}/{root}", json={}).json()["category"]["color"] == "teal"
    cleared = anna.put(f"{CATS}/{root}", json={"icon": None, "color": None}).json()["category"]
    assert (cleared["icon"], cleared["color"]) == (None, None)
    top = anna.put(f"{CATS}/{kid}", json={"parent_id": None}).json()["category"]
    assert top["parent_id"] is None and top["kind"] == "expense"  # the parent can be cleared; the kind stays


def test_update_collisions_and_unknowns(anna: TestClient):
    a, b = make(anna, "A", kind="expense"), make(anna, "B", kind="expense")
    x = make(anna, "X", a)
    make(anna, "x", b)
    err = assert_envelope(anna.put(f"{CATS}/{a}", json={"name": "b"}), 409, "conflict")
    assert err["details"] == {"reason": "duplicate_name"}
    err = assert_envelope(anna.put(f"{CATS}/{x}", json={"parent_id": b}), 409, "conflict")
    assert err["details"] == {"reason": "duplicate_name"}  # reparenting into a name clash
    assert_envelope(anna.put(f"{CATS}/999", json={"name": "z"}), 404, "not_found")
    assert_envelope(anna.put(f"{CATS}/999", json={}), 404, "not_found")
    assert_envelope(
        anna.put(f"{CATS}/{a}", json={"kind": "income"}), 422, "validation_error"
    )  # kind: not accepted
    err = assert_envelope(anna.put(f"{CATS}/{a}", json={"parent_id": 999}), 409, "stale_reference")
    assert err["details"]["field"] == "parent_id"
    income = make(anna, "Pay", kind="income")
    err = assert_envelope(anna.put(f"{CATS}/{a}", json={"parent_id": income}), 422, "validation_error")
    assert err["details"][0]["location"] == ["body", "parent_id"]


def test_reparenting_under_itself_or_a_descendant_is_a_cycle(anna: TestClient, api_engine: Engine):
    a = make(anna, "A", kind="expense")
    b = make(anna, "B", a)
    c = make(anna, "C", b)
    before = names(api_engine)
    for target in (a, b, c):
        err = assert_envelope(anna.put(f"{CATS}/{a}", json={"parent_id": target}), 409, "conflict")
        assert err["details"] == {"reason": "cycle"}
    assert names(api_engine) == before
    assert anna.put(f"{CATS}/{c}", json={"parent_id": a}).status_code == 200  # up the tree is fine


def test_the_trigger_refuses_a_cycle_on_its_own(api_engine: Engine):
    with api_engine.begin() as conn:
        a = seed.category(conn, "A")
        b = seed.category(conn, "B", a)
        c = seed.category(conn, "C", b)
    with pytest.raises(DBAPIError, match="cycle"), api_engine.begin() as conn:
        conn.execute(text("UPDATE category SET parent_id = :c WHERE id = :a"), {"a": a, "c": c})
    with pytest.raises(DBAPIError), api_engine.begin() as conn:  # and the kind is fixed
        conn.execute(text("UPDATE category SET kind = 'income' WHERE id = :a"), {"a": a})


# ---- delete -----------------------------------------------------------------------------------


def test_delete_an_unused_category_and_refusal_with_counts(anna: TestClient, api_engine: Engine, acct: int):
    unused = make(anna, "Unused", kind="expense")
    r = anna.delete(f"{CATS}/{unused}")
    assert r.status_code == 200
    assert r.json()["deleted"] is True and r.json()["settle"]["error"] is None
    assert anna.get(CATS).json() == {"categories": []}
    assert_envelope(anna.delete(f"{CATS}/{unused}"), 404, "not_found")

    used = make(anna, "Used", kind="expense")
    kid = make(anna, "Kid", used)
    with api_engine.begin() as conn:
        seed.entry(conn, acct, category_id=used)
        seed.entry(conn, acct, category_id=used)
        rule(conn, "r", category_id=used)
    err = assert_envelope(anna.delete(f"{CATS}/{used}"), 409, "conflict")
    assert err["details"] == {"reason": "category_in_use", "held": {"entries": 2, "rules": 1, "children": 1}}
    assert anna.delete(f"{CATS}/{kid}").status_code == 200  # the leaf was free
    assert used in names(api_engine)


def test_delete_dry_run_reports_and_writes_nothing(anna: TestClient, api_engine: Engine, acct: int):
    used = make(anna, "Used", kind="expense")
    free = make(anna, "Free", kind="expense")
    with api_engine.begin() as conn:
        seed.entry(conn, acct, category_id=used)
        before = counts(conn)
    r = anna.delete(f"{CATS}/{used}", params={"dry_run": "true"})
    assert r.status_code == 200
    assert r.json() | {"category": None} == {
        "dry_run": True, "category": None, "deletable": False,
        "held": {"entries": 1, "rules": 0, "children": 0}, "deleted": False, "settle": None,
    }  # fmt: skip
    r = anna.delete(f"{CATS}/{free}", params={"dry_run": "true"})
    assert (r.json()["deletable"], r.json()["deleted"]) == (True, False)
    with api_engine.begin() as conn:
        assert counts(conn) == before


# ---- merge ------------------------------------------------------------------------------------


@pytest.fixture
def forest(anna: TestClient, api_engine: Engine, acct: int) -> dict[str, int]:
    """Source tree S{Food{Beer,Wine}, Pets} and target T{food{beer}, Cars}, plus an unrelated U.

    Food/food and Beer/beer collide by name (case-insensitively), one level apart.
    """
    s = make(anna, "S", kind="expense")
    sf = make(anna, "Food", s)
    make(anna, "Beer", sf)
    make(anna, "Wine", sf)
    make(anna, "Pets", s)
    t = make(anna, "T", kind="expense")
    tf = make(anna, "food", t)
    make(anna, "beer", tf)
    make(anna, "Cars", t)
    make(anna, "U", kind="expense")
    make(anna, "Pay", kind="income")
    ids = {r.name: r.id for r in q(api_engine, "SELECT id, name FROM category")}
    with api_engine.begin() as conn:
        for name, n in (("S", 1), ("Food", 2), ("Beer", 3), ("Wine", 1), ("beer", 2)):
            for _ in range(n):
                seed.entry(conn, acct, category_id=ids[name])
        rule(conn, "r-food", category_id=ids["Food"])
        rule(conn, "r-s", category_id=ids["S"])
    return ids


def test_merge_dry_run_lists_every_pair_deepest_first_and_writes_nothing(
    anna: TestClient, api_engine: Engine, forest: dict[str, int]
):
    ids = forest
    with api_engine.begin() as conn:
        before = counts(conn)
    r = merge(anna, ids["S"], ids["T"], dry_run=True)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["dry_run"] is True and p["settle"] is None and p["entry_ids"] == []
    assert [(x["source_name"], x["target_name"], x["entries"], x["rules"]) for x in p["pairs"]] == [
        ("Beer", "beer", 3, 0),  # the deepest collision first
        ("Food", "food", 2, 1),
        ("S", "T", 1, 1),
    ]
    assert p["entry_count"] == 6 and len(p["rule_ids"]) == 2
    assert {(m["name"], m["from_id"], m["to_id"]) for m in p["moved_children"]} == {
        ("Wine", ids["Food"], ids["food"]),
        ("Pets", ids["S"], ids["T"]),
    }
    with api_engine.begin() as conn:
        assert counts(conn) == before


def test_merge_repoints_moves_children_keeps_keys_and_bumps_versions(
    anna: TestClient, api_engine: Engine, forest: dict[str, int]
):
    ids = forest
    with api_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE ledger_entry SET derivation ="
                " jsonb_build_object('category_id', jsonb_build_object('pass', 'user'))"
            ),
        )
        before = conn.execute(text(ENTRY_STATE)).all()
        versions_before = dict(conn.execute(text("SELECT id, version FROM ledger_entry")).all())
    dry = merge(anna, ids["S"], ids["T"], dry_run=True).json()
    r = merge(anna, ids["S"], ids["T"], expected_count=dry["entry_count"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is False and body["settle"]["error"] is None
    assert body["entry_count"] == 6 and len(body["entry_ids"]) == 6 and body["pairs"] == dry["pairs"]
    after = names(api_engine)
    now = {n: i for i, (n, _) in after.items()}
    assert sorted(n for n, _ in after.values()) == sorted(
        ["T", "food", "beer", "Cars", "Wine", "Pets", "U", "Pay"]
    )
    assert after[ids["Wine"]] == ("Wine", ids["food"]) and after[ids["Pets"]] == ("Pets", ids["T"])
    assert not {ids["S"], ids["Food"], ids["Beer"]} & set(after)
    assert now["T"] == ids["T"] and after[ids["T"]][0] == "T"  # the target keeps its own name
    with api_engine.begin() as conn:
        cats = {
            r.category_id: r.n
            for r in conn.execute(text("SELECT category_id, count(*) AS n FROM ledger_entry GROUP BY 1"))
        }
        rules = {r.name: r.category_id for r in conn.execute(text("SELECT name, category_id FROM rule"))}
        same = conn.execute(text(ENTRY_STATE)).all()
        versions_after = dict(conn.execute(text("SELECT id, version FROM ledger_entry")).all())
    assert cats == {ids["T"]: 1, ids["food"]: 2, ids["beer"]: 5, ids["Wine"]: 1}
    assert rules == {"r-food": ids["food"], "r-s": ids["T"]}
    assert same == before  # keys, flags, type, amounts: untouched
    moved = set(body["entry_ids"])
    assert {i for i, v in versions_after.items() if v != versions_before[i]} == moved
    assert all(versions_after[i] == versions_before[i] + 1 for i in moved)  # a merge bumps what it repoints
    assert_checks_ok(anna)


def test_merge_into_the_parent_is_allowed_and_a_child_named_like_the_source_survives(
    anna: TestClient, api_engine: Engine, acct: int
):
    p = make(anna, "Parent", kind="expense")
    s = make(anna, "Food", p)
    inner = make(anna, "food", s)  # named like its own parent: collides with the source for a moment
    leaf = make(anna, "Leaf", s)
    with api_engine.begin() as conn:
        seed.entry(conn, acct, category_id=s)
    r = merge(anna, s, p, dry_run=True)
    assert r.status_code == 200 and r.json()["entry_count"] == 1
    r = merge(anna, s, p, expected_count=1)
    assert r.status_code == 200, r.text
    assert names(api_engine) == {p: ("Parent", None), inner: ("food", p), leaf: ("Leaf", p)}
    assert q(api_engine, "SELECT category_id FROM ledger_entry") == [(p,)]


def test_merge_into_a_higher_ancestor_excludes_the_source_when_matching(anna: TestClient, api_engine: Engine):
    top = make(anna, "Top", kind="expense")
    mid = make(anna, "Mid", top)
    low = make(anna, "Low", mid)
    under = make(anna, "Mid", low)  # same name as `mid`, a child of the source
    assert merge(anna, low, top, expected_count=0).status_code == 200
    # `under` collides with `mid` (a child of the ancestor) and merges into it
    assert names(api_engine) == {top: ("Top", None), mid: ("Mid", top)}
    assert under not in names(api_engine)


def test_merge_into_a_descendant_same_or_other_kind_is_refused(anna: TestClient, api_engine: Engine):
    a = make(anna, "A", kind="expense")
    b = make(anna, "B", a)
    c = make(anna, "C", b)
    income = make(anna, "Pay", kind="income")
    before = names(api_engine)
    for target in (b, c):
        err = assert_envelope(merge(anna, a, target, dry_run=True), 409, "conflict")
        assert err["details"] == {"reason": "into_descendant"}
        assert_envelope(merge(anna, a, target, expected_count=0), 409, "conflict")
    err = assert_envelope(merge(anna, a, a, dry_run=True), 422, "validation_error")
    assert err["details"][0]["location"] == ["body", "into"]
    err = assert_envelope(merge(anna, a, income, dry_run=True), 422, "validation_error")
    assert err["details"][0]["location"] == ["body", "into"]
    assert names(api_engine) == before
    assert merge(anna, c, a, expected_count=0).status_code == 200  # the other way round is fine


def test_merge_errors_unknown_source_stale_target_and_missing_count(anna: TestClient, api_engine: Engine):
    a, b = make(anna, "A", kind="expense"), make(anna, "B", kind="expense")
    assert_envelope(merge(anna, 999, b, dry_run=True), 404, "not_found")
    err = assert_envelope(merge(anna, a, 999, dry_run=True), 409, "stale_reference")
    assert err["details"] == {"field": "into", "entity": "category", "id": 999}
    err = assert_envelope(merge(anna, a, b), 422, "validation_error")
    assert err["details"][0]["location"] == ["body", "expected_count"]
    assert_envelope(merge(anna, a, b, expected_count=-1), 422, "validation_error")
    assert set(names(api_engine)) == {a, b}


def test_expected_count_mismatch_is_409_and_writes_nothing(
    anna: TestClient, api_engine: Engine, forest: dict[str, int]
):
    with api_engine.begin() as conn:
        before = counts(conn)
    err = assert_envelope(merge(anna, forest["S"], forest["T"], expected_count=5), 409, "conflict")
    assert err["details"] == {"reason": "filter_result_changed", "expected": 5, "actual": 6}
    with api_engine.begin() as conn:
        assert counts(conn) == before


def test_a_write_naming_the_merged_away_category_is_a_stale_reference(
    anna: TestClient, api_engine: Engine, forest: dict[str, int]
):
    merge(anna, forest["S"], forest["T"], expected_count=6)
    err = assert_envelope(
        anna.post(CATS, json={"name": "New", "parent_id": forest["S"]}), 409, "stale_reference"
    )
    assert err["details"] == {"field": "parent_id", "entity": "category", "id": forest["S"]}
    assert_envelope(
        anna.put(f"{CATS}/{forest['U']}", json={"parent_id": forest["S"]}), 409, "stale_reference"
    )
    assert_envelope(
        anna.put(f"{CATS}/{forest['S']}", json={"name": "z"}), 404, "not_found"
    )  # the path names it


def test_a_lost_deadlock_is_a_409_try_again(anna: TestClient, monkeypatch: pytest.MonkeyPatch):
    def boom(*a: Any, **k: Any) -> None:
        raise WriteConflict

    monkeypatch.setattr("app.api.routers.categories.merge_category", boom)
    assert_envelope(merge(anna, 1, 2, dry_run=True), 409, "try_again")


def test_merge_settles_once_after_commit_and_failure_is_in_the_200_body(
    anna: TestClient, api_engine: Engine, forest: dict[str, int], monkeypatch: pytest.MonkeyPatch
):
    seen: list[int] = []

    def fake(engine: Engine) -> SettleResult:
        seen.append(len(q(engine, "SELECT 1 FROM category")))
        return SettleResult((5,), "settling failed")

    monkeypatch.setattr(cat_mod, "settle", fake)
    assert merge(anna, forest["S"], forest["T"], dry_run=True).json()["settle"] is None
    assert seen == []  # a preview settles nothing
    r = merge(anna, forest["S"], forest["T"], expected_count=6)
    assert r.status_code == 200 and r.json()["settle"] == {
        "touched_entry_ids": [5],
        "error": "settling failed",
    }
    assert seen == [8]  # once, after the commit: 11 categories, 3 merged away
    assert anna.delete(f"{CATS}/{forest['U']}").json()["settle"]["error"] == "settling failed"
    assert len(seen) == 2


# ---- schema -----------------------------------------------------------------------------------


def test_responses_are_typed_in_the_openapi_schema(api_config: Any, api_engine: Engine):
    schema = create_app(api_config, api_engine).openapi()
    expected = {
        (CATS, "post"): ("201", "CategoryWriteOut"),
        (f"{CATS}/{{category_id}}", "put"): ("200", "CategoryWriteOut"),
        (f"{CATS}/{{category_id}}", "delete"): ("200", "CategoryDeleteOut"),
        (f"{CATS}/{{category_id}}/merge", "post"): ("200", "CategoryMergeOut"),
    }
    for (path, method), (status, model) in expected.items():
        ref = schema["paths"][path][method]["responses"][status]["content"]["application/json"]["schema"]
        assert ref == {"$ref": f"#/components/schemas/{model}"}, (path, method)
    ops = {schema["paths"][p][m]["operationId"] for (p, m) in expected}
    assert ops == {
        "create_ledger_category",
        "update_ledger_category",
        "delete_ledger_category",
        "merge_ledger_category",
    }
    assert schema["components"]["schemas"]["CategoryMergeBody"]["additionalProperties"] is False
