"""What the API says of the model's list (architecture §4.1): `model_pending`, on units and on changes."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.core.model.queue import ModelQueue
from app.core.settle.flags import recompute_review_flags
from tests.api.conftest import login
from tests.core.units.helpers import Bench


@pytest.fixture
def anna(client: TestClient) -> TestClient:
    login(client)
    return client


@pytest.fixture
def world(api_engine: Engine, make_account: Any) -> Bench:
    with api_engine.begin() as conn:
        return Bench(conn, make_account)


def _two_flows(api_engine: Engine, world: Bench) -> tuple[int, int]:
    with api_engine.begin() as conn:
        world.conn = conn
        return world.flow(world.source(), done=False), world.flow(world.source(), done=False)


def test_the_queue_marks_the_units_the_model_is_looking_at(
    anna: TestClient, api_engine: Engine, world: Bench
) -> None:
    looked_at, other = _two_flows(api_engine, world)
    queue = ModelQueue(lambda entry: None)
    anna.app.state.model = queue  # type: ignore[attr-defined]
    queue.sync([("entry", looked_at, "f1")])

    body = anna.get("/api/units/queue").json()
    pending = {u["anchor_entry_id"]: u["model_pending"] for s in body["sections"] for u in s["units"]}
    assert pending == {looked_at: True, other: False}
    assert anna.get(f"/api/units/{looked_at}").json()["model_pending"] is True
    assert anna.get(f"/api/units/{other}").json()["model_pending"] is False

    queue.finish(("entry", looked_at, "f1"), answered=True)  # read at request time: it follows the list
    body = anna.get("/api/units/queue").json()
    assert not any(u["model_pending"] for s in body["sections"] for u in s["units"])


def test_an_entry_whose_line_is_on_the_list_is_pending_and_one_decided_otherwise_is_not(
    anna: TestClient, api_engine: Engine, world: Bench
) -> None:
    def with_line(conn: Any, external_id: str) -> tuple[int, int]:
        doc = int(
            conn.execute(
                text(
                    "INSERT INTO external_document (provider, external_id, occurred_on, total, currency, raw)"
                    " VALUES ('paypal', :e, '2026-03-10', -100, 'EUR', '{}') RETURNING id"
                ),
                {"e": external_id},
            ).scalar_one()
        )
        line = int(
            conn.execute(
                text(
                    "INSERT INTO external_document_line (document_id, line_no, description, amount)"
                    " VALUES (:d, 1, 'item', -100) RETURNING id"
                ),
                {"d": doc},
            ).scalar_one()
        )
        return doc, line

    with api_engine.begin() as conn:
        world.conn = conn
        doc_a, line_a = with_line(conn, "a")
        doc_b, line_b = with_line(conn, "b")
        waiting = world.flow(world.source(), done=False, document_id=doc_a, document_line_id=line_a)
        decided = world.flow(world.source(), done=True, document_id=doc_b, document_line_id=line_b)
    queue = ModelQueue(lambda entry: None)
    anna.app.state.model = queue  # type: ignore[attr-defined]
    queue.sync([("line", line_a, "f1"), ("line", line_b, "f2")])
    assert anna.get(f"/api/units/{waiting}").json()["model_pending"] is True
    assert anna.get(f"/api/units/{decided}").json()["model_pending"] is False  # a category it already has
    queue.sync([])
    assert anna.get(f"/api/units/{waiting}").json()["model_pending"] is False


def test_the_unit_and_the_queue_carry_the_models_none_key(
    anna: TestClient, api_engine: Engine, world: Bench
) -> None:
    key = {"pass": "llm", "basis": {"model": "m", "rationale": "a toll", "fingerprint": "f", "none": True}}
    with api_engine.begin() as conn:
        world.conn = conn
        e = world.flow(world.source(), done=False, derivation=json.dumps({"category": key}))
        recompute_review_flags(conn)

    body = anna.get(f"/api/units/{e}").json()
    (entry,) = body["entries"]
    assert entry["derivation"] == {"category": key} and entry["category_id"] is None
    assert entry["review_flags"] == ["unclassified", "unconfirmed"]
    queued = [u for s in anna.get("/api/units/queue").json()["sections"] for u in s["units"]]
    assert [u["entries"][0]["derivation"] for u in queued if u["anchor_entry_id"] == e] == [{"category": key}]


def test_an_explained_absence_reads_as_a_proposal_on_an_empty_value() -> None:
    from app.api.routers.unit_drafts import UnitFieldOut
    from app.core.resolution.types import Decided
    from app.core.units.plan import FieldResult

    basis = {"model": "m", "rationale": "a toll", "fingerprint": "f", "none": True}
    key = {"pass": "llm", "basis": basis}
    out = UnitFieldOut.of(FieldResult(None, Decided(None, "llm", basis), key, None, key), stored=False)
    assert out.value is None and out.is_proposal is True
    assert out.key is not None and out.key.pass_ == "llm" and out.key.basis == basis
    assert out.commit_key is not None and out.commit_key.basis == basis


def test_without_a_model_no_unit_is_pending(anna: TestClient, api_engine: Engine, world: Bench) -> None:
    _two_flows(api_engine, world)
    body = anna.get("/api/units/queue").json()
    assert not any(u["model_pending"] for s in body["sections"] for u in s["units"])


def test_the_change_poll_carries_how_many_entries_are_left(anna: TestClient) -> None:
    assert anna.get("/api/changes").json()["model_pending"] == 0
    queue = ModelQueue(lambda entry: None)
    anna.app.state.model = queue  # type: ignore[attr-defined]
    queue.sync([("entry", 1, "a"), ("line", 2, "b"), ("line", 2, "b")])
    assert anna.get("/api/changes").json()["model_pending"] == 2
    queue.mark_unavailable()
    assert anna.get("/api/changes").json()["model_pending"] == 0
