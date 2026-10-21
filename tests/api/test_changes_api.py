"""`GET /api/changes` and the `X-Ledger-Changes` header of a write (architecture §4.1, §4.2, §5.2)."""

from __future__ import annotations

import json

from sqlalchemy import text

from tests.api import sync_helpers as h
from tests.api.sync_helpers import PIN, Sync, error_of

sync = h.sync
make_sync = h.make_sync

HEADER = "X-Ledger-Changes"


def test_requires_a_session(sync: Sync) -> None:
    anonymous = type(sync.client)(sync.app, base_url="http://localhost")
    error_of(anonymous.get("/api/changes"), 401, "unauthenticated")


def test_the_read_has_every_account_and_a_start_value_for_one_no_write_touched(sync: Sync) -> None:
    insert = text("INSERT INTO account (name, kind, currency) VALUES (:n, 'checking', 'EUR') RETURNING id")
    with sync.engine.begin() as conn:  # rows inserted outside the server move nothing
        ids = [int(conn.execute(insert, {"n": n}).scalar_one()) for n in "AB"]
    body = sync.client.get("/api/changes").json()
    assert set(body) == {"ledger", "documents", "accounts", "active_task", "model_pending"}
    assert body["model_pending"] == 0
    assert set(body["accounts"]) == {str(i) for i in ids} and body["active_task"] is None
    start = sync.app.state.changes.start_value
    assert body["ledger"] == body["documents"] == start and set(body["accounts"].values()) == {start}


def test_a_value_moves_when_its_key_is_bumped_and_only_that_one(sync: Sync) -> None:
    a, b = sync.account("A"), sync.account("B")
    before = sync.client.get("/api/changes").json()
    sync.app.state.changes.bump(["ledger", f"account:{a}"])
    after = sync.client.get("/api/changes").json()
    assert after["ledger"] != before["ledger"] and after["accounts"][str(a)] != before["accounts"][str(a)]
    assert (
        after["documents"] == before["documents"] and after["accounts"][str(b)] == before["accounts"][str(b)]
    )


def test_a_write_response_carries_the_values_after_it_and_a_read_does_not(sync: Sync) -> None:
    inst, accounts = sync.world()
    account = sync.account("Second")
    before = sync.client.get("/api/changes").json()
    r = sync.client.post(
        f"/api/importers/instances/{inst}/links", json={"account_id": account, "external_ref": "ZZ"}
    )
    assert r.status_code == 200, r.text
    carried = json.loads(r.headers[HEADER])
    assert set(carried) == {"ledger", "documents", "accounts"}
    assert carried["ledger"] != before["ledger"]  # every write took the shared settle lock
    after = sync.client.get("/api/changes")
    assert HEADER not in after.headers
    assert {k: after.json()[k] for k in carried} == carried  # the values the next read gives
    assert set(carried["accounts"]) >= {str(a) for a in accounts}


def test_a_refused_write_carries_the_values_and_moves_nothing(sync: Sync) -> None:
    before = sync.client.get("/api/changes").json()
    r = sync.client.post("/api/importers/instances/999999/links", json={"account_id": 1, "external_ref": "x"})
    assert r.status_code >= 400
    assert json.loads(r.headers[HEADER])["ledger"] == before["ledger"]


def test_active_task_is_the_users_own_running_task(sync: Sync) -> None:
    sync.world({"open": [PIN]})
    task = sync.started()
    sync.open_prompt(task)
    assert sync.client.get("/api/changes").json()["active_task"] == task
    assert sync.other.get("/api/changes").json()["active_task"] is None  # never another user's
