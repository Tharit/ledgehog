"""What the API says of the model's list (architecture §4.1): `model_pending`, on units and on changes."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.core.model.queue import ModelQueue
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
    queue.sync([(looked_at, "f1")])

    body = anna.get("/api/units/queue").json()
    pending = {u["anchor_entry_id"]: u["model_pending"] for s in body["sections"] for u in s["units"]}
    assert pending == {looked_at: True, other: False}
    assert anna.get(f"/api/units/{looked_at}").json()["model_pending"] is True
    assert anna.get(f"/api/units/{other}").json()["model_pending"] is False

    queue.finish((looked_at, "f1"), answered=True)  # read at request time: it follows the list
    body = anna.get("/api/units/queue").json()
    assert not any(u["model_pending"] for s in body["sections"] for u in s["units"])


def test_without_a_model_no_unit_is_pending(anna: TestClient, api_engine: Engine, world: Bench) -> None:
    _two_flows(api_engine, world)
    body = anna.get("/api/units/queue").json()
    assert not any(u["model_pending"] for s in body["sections"] for u in s["units"])


def test_the_change_poll_carries_how_many_entries_are_left(anna: TestClient) -> None:
    assert anna.get("/api/changes").json()["model_pending"] == 0
    queue = ModelQueue(lambda entry: None)
    anna.app.state.model = queue  # type: ignore[attr-defined]
    queue.sync([(1, "a"), (2, "b"), (2, "b")])
    assert anna.get("/api/changes").json()["model_pending"] == 2
    queue.mark_unavailable()
    assert anna.get("/api/changes").json()["model_pending"] == 0
