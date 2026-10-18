"""Shared builders for the sync API tests: the app with the scripted `testfetch` importer registered, a task
registry with short timings, two signed-in users and the waits a background task needs. All data is
synthetic.

The app runs inside `with TestClient(...)`: that runs its lifespan, which sets the loop a task launched
from the threadpool runs on (the same loop the in-process client keeps alive between requests)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.api import create_app
from app.core.accounts import create_account
from app.core.importers.instances import create_instance
from app.core.tasks import TaskRegistry, TaskTuning
from app.plugins.importers.csv import CsvImporter
from app.plugins.importers.testfetch import TestFetchImporter
from app.utils.config import Config
from tests.api.conftest import login
from tests.conftest import CLOCK_START

API_TODAY = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
START = "2026-08-10"  # the scripted history starts here: a short fetch
TUNING = TaskTuning(
    prompt_timeout_s=10.0, poll_interval_s=0.02, abandon_grace_s=60.0, retention_s=900.0, keepalive_s=0.2
)
WAIT = 10.0


def acct(ref: str, **kw: Any) -> dict[str, Any]:
    """A scripted account: from the tenth of August, one row a day, unless said otherwise."""
    return {"ref": ref, "name": ref, "history_start": START, **kw}


PIN = {"ask": "secret", "subject": "pin", "expect": "1234"}


@dataclass
class Sync:
    client: TestClient  # anna
    other: TestClient  # ben
    engine: Engine
    registry: TaskRegistry
    app: Any

    # ---- seeding (straight into the core where the endpoint under test is not the setup) --------

    def instance(
        self,
        settings: Mapping[str, Any] | None = None,
        *,
        label: str = "Bank",
        access: str = "shared",
        owner: str = "anna",
        emits: tuple[str, ...] = ("transactions",),
        importer: str = "testfetch",
    ) -> int:
        owner_id = None
        if access == "owner":
            with self.engine.connect() as conn:
                owner_id = int(
                    conn.execute(text("SELECT id FROM app_user WHERE login = :l"), {"l": owner}).scalar_one()
                )
        return create_instance(
            self.engine,
            importer=importer,
            label=label,
            settings=dict(settings or {}),
            emits=list(emits),
            access=access,
            owner_id=owner_id,
        )

    def account(self, name: str = "Giro", *, currency: str = "EUR", external_ref: str | None = None) -> int:
        return create_account(
            self.engine, name=name, kind="checking", currency=currency, external_ref=external_ref
        )

    def link(self, instance: int, account: int, ref: str) -> None:
        r = self.client.post(
            f"/api/importers/instances/{instance}/links", json={"account_id": account, "external_ref": ref}
        )
        assert r.status_code == 200, r.text

    def world(
        self, settings: Mapping[str, Any] | None = None, refs: tuple[str, ...] = ("A1",), **kw: Any
    ) -> tuple[int, list[int]]:
        """An instance scripted with `refs` (plus `settings`), each linked to a new account."""
        merged = {"accounts": [acct(r) for r in refs], **(settings or {})}
        inst = self.instance(merged, **kw)
        accounts = []
        for ref in refs:
            a = self.account(f"Acct {ref}")
            self.link(inst, a, ref)
            accounts.append(a)
        return inst, accounts

    # ---- driving -----------------------------------------------------------------------------

    def start(self, items: Any = None, *, client: TestClient | None = None):
        who = client or self.client
        return who.post("/api/sync") if items is None else who.post("/api/sync", json={"items": items})

    def started(self, items: Any = None, *, client: TestClient | None = None) -> str:
        r = self.start(items, client=client)
        assert r.status_code == 202, r.text
        return str(r.json()["task_id"])

    def status(self, task_id: str, client: TestClient | None = None) -> dict[str, Any]:
        r = (client or self.client).get(f"/api/sync/tasks/{task_id}")
        assert r.status_code == 200, r.text
        return dict(r.json())

    def wait_ended(self, task_id: str, client: TestClient | None = None) -> dict[str, Any]:
        deadline = time.monotonic() + WAIT
        while time.monotonic() < deadline:
            st = self.status(task_id, client)
            if st["status"] == "ended":
                return st
            time.sleep(0.02)
        raise AssertionError("the task did not end")

    def events(
        self, task_id: str, last_id: int | None = None, client: TestClient | None = None
    ) -> list[Frame]:
        """The stream of a finished task, in full (it closes after `task_ended`)."""
        headers = {} if last_id is None else {"Last-Event-ID": str(last_id)}
        r = (client or self.client).get(f"/api/sync/tasks/{task_id}/events", headers=headers)
        assert r.status_code == 200, r.text
        return parse_frames(r.text)

    def open_prompt(self, task_id: str, after: int = 0) -> dict[str, Any]:
        """The first still-open `prompt` event's data above event id `after`, polled through the
        replay (a resolved prompt has no body)."""
        deadline = time.monotonic() + WAIT
        while time.monotonic() < deadline:
            for f in self.events_so_far(task_id, after):
                if f.event == "prompt" and "prompt" in f.data:
                    return f.data
            time.sleep(0.02)
        raise AssertionError("no prompt opened")

    def events_so_far(self, task_id: str, after: int = 0) -> list[Frame]:
        """What the task has emitted now, read from the task itself (the HTTP stream of a running task
        does not end, and the in-process client buffers it)."""
        task = self.registry.get(task_id, self.user_id("anna"))
        assert task is not None
        return [Frame(e.id, e.name, dict(e.data)) for e in task.events_after(after)]

    def user_id(self, login_name: str) -> int:
        with self.engine.connect() as conn:
            return int(
                conn.execute(text("SELECT id FROM app_user WHERE login = :l"), {"l": login_name}).scalar_one()
            )

    def answer(self, task_id: str, prompt_id: str, value: str | None = None, **kw: Any):
        body: dict[str, Any] = {"prompt_id": prompt_id, **kw}
        if value is not None:
            body["value"] = value
        return self.client.post(f"/api/sync/tasks/{task_id}/input", json=body)

    def run_count(self, where: str = "true") -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(text(f"SELECT count(*) FROM import_run WHERE {where}")).scalar_one())  # noqa: S608


@dataclass(frozen=True)
class Frame:
    id: int
    event: str
    data: dict[str, Any]


def parse_frames(body: str) -> list[Frame]:
    """The event frames of an SSE body (comments and `retry` lines are not frames)."""
    frames = []
    for block in body.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if line and not line.startswith(":"))
        if "event" in fields:
            frames.append(Frame(int(fields["id"]), fields["event"], json.loads(fields["data"])))
    return frames


def error_of(response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}, body
    assert body["error"]["code"] == code, body
    return dict(body["error"])


@pytest.fixture
def make_sync(api_config: Config, api_engine: Engine, clock) -> Iterator[Callable[..., Sync]]:
    entered: list[TestClient] = []  # with a lifespan: the loop tasks run on
    plain: list[TestClient] = []
    registries: list[TaskRegistry] = []

    def make(tuning: TaskTuning = TUNING) -> Sync:
        registry = TaskRegistry(tuning)
        registries.append(registry)
        importers = {"csv": CsvImporter(), "testfetch": TestFetchImporter()}
        app = create_app(api_config, api_engine, importers=importers, tasks=registry)
        anna = TestClient(app, base_url="http://localhost")
        anna.__enter__()
        entered.append(anna)
        ben = TestClient(app, base_url="http://localhost")
        plain.append(ben)
        assert login(anna, "anna").status_code == 200
        assert login(ben, "ben").status_code == 200
        return Sync(anna, ben, api_engine, registry, app)

    clock.advance(API_TODAY - CLOCK_START)
    yield make
    for registry in registries:  # a test may leave a task blocked on a prompt: stop it before the loop goes
        tasks = list(registry._tasks.values())
        for task in tasks:
            task.abort()
        deadline = time.monotonic() + WAIT
        while not all(t.ended for t in tasks) and time.monotonic() < deadline:
            time.sleep(0.02)
    for c in plain:
        c.close()
    for c in entered:
        c.__exit__(None, None, None)


@pytest.fixture
def sync(make_sync: Callable[..., Sync]) -> Sync:
    return make_sync()
