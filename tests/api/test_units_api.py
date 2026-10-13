"""`GET /api/units/{entry_id}`, `/api/units/queue` and `/queue/new-count` (architecture §4.1, spec §6)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.core.settle.flags import recompute_review_flags
from tests.api.accounts_helpers import assert_envelope
from tests.api.conftest import login
from tests.core.units.helpers import Bench, keys

QUEUE = "/api/units/queue"


@pytest.fixture
def anna(client: TestClient) -> TestClient:
    login(client)
    return client


@pytest.fixture
def world(api_engine: Engine, make_account: Any) -> Bench:
    with api_engine.begin() as conn:
        return Bench(conn, make_account)


def _make(api_engine: Engine, world: Bench, build: Any) -> Any:
    """Run `build(world)` in its own committed transaction (the bench's accounts exist already)."""
    with api_engine.begin() as conn:
        world.conn = conn
        return build(world)


def test_requires_a_session(client: TestClient) -> None:
    for url in ("/api/units/1", QUEUE, f"{QUEUE}/new-count?since=x"):
        assert_envelope(client.get(url), 401, "unauthenticated")


def test_get_unit_shape_for_a_pair_with_a_split(anna: TestClient, api_engine: Engine, world: Bench) -> None:
    def build(b: Bench) -> tuple[int, int, int, int, int]:
        s1, s2 = b.source(), b.source(b.b, amount=100, parts=2, authored=True)
        x = b.transfer(s1, derivation=keys(counter_account="history"))
        y = b.transfer(s2)
        sib = b.flow(s2, done=False)
        b.pair(x, y)
        recompute_review_flags(b.conn)
        return s1, x, y, sib, b.b

    s1, x, y, sib, acct_b = _make(api_engine, world, build)
    r = anna.get(f"/api/units/{sib}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"anchor_entry_id", "unit_key", "state", "entries"}
    assert (body["anchor_entry_id"], body["unit_key"]) == (x, s1)
    assert body["state"] == {"confirmed": False, "reasons": ["incomplete", "non_standing_keys"]}
    assert [e["id"] for e in body["entries"]] == [x, y, sib]
    by_id = {e["id"]: e for e in body["entries"]}
    assert by_id[x]["derivation"] == {"counter_account": {"pass": "history"}}
    assert by_id[x]["partner"] == {
        "entry_id": y,
        "account_id": by_id[y]["account_id"],
        "booked_on": "2026-03-10",
        "amount": {"amount": 100, "currency": "EUR"},
    }
    assert by_id[y]["partner"]["entry_id"] == x and by_id[sib]["partner"] is None
    assert {e["unit_key"] for e in body["entries"]} == {s1}
    assert by_id[sib]["review_flags"] == ["unclassified", "unconfirmed"]
    assert (by_id[x]["authored"], by_id[x]["source"] is None) == (False, False)  # imported
    assert all(by_id[i]["authored"] and by_id[i]["source"] is None for i in (y, sib))  # entered by hand
    assert {"version", "tag_ids"} <= set(by_id[x])
    assert by_id[sib]["account_id"] == acct_b


def test_get_unit_404_and_bounds(anna: TestClient) -> None:
    assert_envelope(anna.get("/api/units/12345"), 404, "not_found")
    assert_envelope(anna.get("/api/units/0"), 422, "validation_error")
    assert_envelope(anna.get(f"/api/units/{2**63}"), 422, "validation_error")
    assert_envelope(anna.get("/api/units/queue-ish"), 422, "validation_error")


def test_the_queue_shape_sections_and_order(anna: TestClient, api_engine: Engine, world: Bench) -> None:
    def build(b: Bench) -> tuple[int, int]:
        late = b.flow(b.source(on=date(2026, 6, 1)), done=False)
        early = b.flow(b.source(on=date(2026, 1, 1)), derivation=keys(category="history"))
        b.flow(b.source())  # confirmed
        return late, early

    late, early = _make(api_engine, world, build)
    r = anna.get(QUEUE)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"sections", "total", "snapshot"} and body["total"] == 2 and body["snapshot"]
    assert [(s["kind"], s["total"]) for s in body["sections"]] == [
        ("pending_review", 2),
        ("needs_account", 0),
        ("waiting", 0),
    ]
    pending = body["sections"][0]
    assert set(pending) == {"kind", "total", "units", "next_cursor"} and pending["next_cursor"] is None
    assert [u["anchor_entry_id"] for u in pending["units"]] == [early, late]
    assert pending["units"][0]["state"] == {"confirmed": False, "reasons": ["non_standing_keys"]}
    assert pending["units"][1]["state"]["reasons"] == ["incomplete"]
    assert set(pending["units"][0]) == {"anchor_entry_id", "unit_key", "state", "entries"}
    assert body["sections"][1]["units"] == [] and body["sections"][2]["next_cursor"] is None


def test_paging_with_limit_section_and_cursor(anna: TestClient, api_engine: Engine, world: Bench) -> None:
    def build(b: Bench) -> list[int]:
        return [b.flow(b.source(on=date(2026, 1, 1 + i)), done=False) for i in range(5)]

    anchors = _make(api_engine, world, build)
    first = anna.get(QUEUE, params={"limit": 2}).json()["sections"][0]
    assert [u["anchor_entry_id"] for u in first["units"]] == anchors[:2] and first["next_cursor"]
    p = {"limit": 2, "section": "pending_review", "cursor": first["next_cursor"]}
    second = anna.get(QUEUE, params=p).json()
    assert [s["kind"] for s in second["sections"]] == ["pending_review"] and second["total"] == 5
    assert [u["anchor_entry_id"] for u in second["sections"][0]["units"]] == anchors[2:4]
    last = anna.get(QUEUE, params={**p, "cursor": second["sections"][0]["next_cursor"]}).json()
    assert [u["anchor_entry_id"] for u in last["sections"][0]["units"]] == anchors[4:]
    assert last["sections"][0]["next_cursor"] is None


def test_queue_parameter_errors(anna: TestClient) -> None:
    for params in (
        {"limit": 0},
        {"limit": 501},
        {"section": "nope"},
        {"cursor": "abc"},  # a cursor needs its section
        {"section": "pending_review", "cursor": "not-a-cursor"},
    ):
        assert_envelope(anna.get(QUEUE, params=params), 422, "validation_error")
    assert_envelope(anna.get(f"{QUEUE}/new-count"), 422, "validation_error")
    assert_envelope(anna.get(f"{QUEUE}/new-count", params={"since": "junk"}), 422, "validation_error")


def test_new_count(anna: TestClient, api_engine: Engine, world: Bench) -> None:
    _make(api_engine, world, lambda b: b.flow(b.source(), done=False))
    snap = anna.get(QUEUE).json()["snapshot"]
    assert anna.get(f"{QUEUE}/new-count", params={"since": snap}).json()["new_count"] == 0

    def more(b: Bench) -> None:
        b.flow(b.source(), done=False)
        b.flow(b.source())

    _make(api_engine, world, more)
    body = anna.get(f"{QUEUE}/new-count", params={"since": snap}).json()
    assert set(body) == {"new_count", "snapshot"} and body["new_count"] == 1
    assert anna.get(f"{QUEUE}/new-count", params={"since": body["snapshot"]}).json()["new_count"] == 0


def test_operation_ids(anna: TestClient) -> None:
    ids = {
        (path, method): op["operationId"]
        for path, item in anna.app.openapi()["paths"].items()
        for method, op in item.items()
        if path.startswith("/api/units")
    }
    assert ids == {
        ("/api/units/queue", "get"): "get_review_queue",
        ("/api/units/queue/new-count", "get"): "get_new_unit_count",
        ("/api/units/{entry_id}", "get"): "get_unit",
        ("/api/units/preview", "post"): "preview_unit",
        ("/api/units/commit", "post"): "commit_unit",
    }
