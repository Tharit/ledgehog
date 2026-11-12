"""A task rig for the orchestration tests: a real database, the scripted `testfetch` importer, and the
orchestration coroutine on a background thread while the test plays the user."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import Engine, text

from app.core.accounts import create_account
from app.core.importers.instances import create_instance, link_account
from app.core.importers.plan import JobPlan, plan_start
from app.core.tasks import Event, JobEnv, Task, TaskRegistry, run_task
from app.plugins.importers.testing import TestDocumentImporter, TestFetchImporter
from tests.core.tasks.helpers import FAST, WAIT, open_prompt

TODAY = date(2026, 6, 15)
IMPORTERS: dict[str, object] = {"testfetch": TestFetchImporter(), "testdocs": TestDocumentImporter()}

DOC = {
    "provider": "paypal",
    "source_id": "D1",
    "occurred_on": "2026-06-02",
    "total_minor": -1500,
    "currency": "EUR",
    "merchant_name": "Shop",
    "lines": [{"description": "Thing", "amount_minor": -1500}],
}


def acct(ref: str, **kw: Any) -> dict[str, Any]:
    """A scripted account: from the first of June, one row a day, unless said otherwise."""
    return {"ref": ref, "history_start": "2026-06-01", **kw}


@dataclass
class Handle:
    """A running task: its thread, its task, and what the test needs to wait on it."""

    task: Task
    thread: threading.Thread
    registry: TaskRegistry

    def wait(self) -> list[Event]:
        self.thread.join(WAIT * 2)
        assert not self.thread.is_alive(), "the task did not end"
        return self.task.events_after(0)

    def names(self) -> list[str]:
        return [e.name for e in self.task.events_after(0)]

    def of(self, name: str) -> list[Mapping[str, Any]]:
        return [e.data for e in self.task.events_after(0) if e.name == name]

    def answer(self, value: str | None = None, *, cancel: bool = False, after: int = 0) -> Event:
        """Answer the next open prompt (above event id `after`) and return its event."""
        event = open_prompt(self.task, after)
        self.task.answer(event.data["prompt_id"], value, cancel=cancel)
        return event


@dataclass
class Rig:
    engine: Engine
    registry: TaskRegistry = field(default_factory=lambda: TaskRegistry(FAST))
    user_id: int = 0

    def __post_init__(self) -> None:
        with self.engine.begin() as conn:
            self.user_id = int(
                conn.execute(
                    text(
                        "INSERT INTO app_user (login, pw_hash, display_name) VALUES ('anna', 'x', 'Anna')"
                        " RETURNING id"
                    )
                ).scalar_one()
            )

    @property
    def env(self) -> JobEnv:
        return JobEnv(self.engine, IMPORTERS, TODAY, self.user_id)

    def instance(
        self,
        settings: Mapping[str, Any] | None = None,
        *,
        importer: str = "testfetch",
        label: str = "Bank",
        emits: Sequence[str] = ("transactions", "documents"),
    ) -> int:
        return create_instance(
            self.engine,
            importer=importer,
            label=label,
            settings=dict(settings or {}),
            emits=list(emits),
            access="shared",
        )

    def link(self, instance_id: int, ref: str, name: str | None = None, *, currency: str = "EUR") -> int:
        account = create_account(self.engine, name=name or ref, kind="checking", currency=currency)
        link_account(self.engine, instance_id, account, ref)
        return account

    def jobs(self, items: Any = None, user_id: int | None = None) -> tuple[JobPlan, ...]:
        with self.engine.connect() as conn:
            return plan_start(conn, self.user_id if user_id is None else user_id, items, IMPORTERS, TODAY)

    def start(
        self,
        jobs: Sequence[JobPlan] | None = None,
        *,
        kind: str = "sync",
        user_id: int | None = None,
        env: JobEnv | None = None,
        skip_busy: bool = False,
        attach: bool = True,
    ) -> Handle:
        """Start a task. A client is attached by default (as an open tab is); without one, the grace of
        the tuning decides whether the task is abandoned at a job boundary."""
        planned = self.jobs() if jobs is None else jobs
        started = self.registry.start(
            self.user_id if user_id is None else user_id,
            kind,  # type: ignore[arg-type]
            planned,
            skip_busy=skip_busy,
        )
        if attach:
            started.task.subscribe(lambda: None)
        thread = threading.Thread(
            target=asyncio.run,
            args=(run_task(self.registry, started.task, started.jobs, env or self.env),),
            daemon=True,
        )
        thread.start()
        return Handle(started.task, thread, self.registry)

    def run(self, jobs: Sequence[JobPlan] | None = None, **kw: Any) -> Handle:
        """Start and wait: for a task that needs no answers."""
        handle = self.start(jobs, **kw)
        handle.wait()
        return handle

    # ---- reading the database ----

    def q(self, sql: str, **params: Any) -> list[Any]:
        with self.engine.connect() as conn:
            return list(conn.execute(text(sql), params).all())

    def runs(self, where: str = "true") -> list[Any]:
        return self.q(f"SELECT * FROM import_run WHERE {where} ORDER BY id")  # noqa: S608

    def rows(self, account_id: int) -> int:
        sql = "SELECT count(*) FROM source_transaction WHERE account_id = :a"
        return int(self.q(sql, a=account_id)[0][0])

    def assert_none_running(self) -> None:
        assert self.q("SELECT count(*) FROM import_run WHERE status = 'running'")[0][0] == 0

    def state(self, instance_id: int) -> dict[str, Any]:
        return dict(self.q("SELECT state FROM importer_instance WHERE id = :i", i=instance_id)[0][0])
