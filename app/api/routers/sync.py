"""The sync operations (architecture §4.1, §4.2, §4.3): the plan, the start, the active task, a task's
status, its event stream, an answer to a prompt and the abort.

Thin over `app.core.importers.plan` (what a start would do, and its refusals) and `app.core.tasks`
(the registry, the task, the orchestration). Everything is a plain `def` run in the threadpool except the
event stream, which is the one coroutine: it waits on the task's wake-ups, bridged to the loop.

Secrets (§5.6): an answer arrives as a `SecretStr`, becomes a `SecretText` here and goes straight into the
task's hand-off. The body of a sync endpoint is never logged, and the validation envelope never echoes
the input it refused.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, Path, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, SecretStr
from sqlalchemy import Engine

from app.api.errors import ApiError, map_error
from app.api.ids import EntityId
from app.api.openapi import ErrorEnvelope
from app.api.routers.importers import account_currencies, to_json
from app.api.session import CurrentUser, EngineDep
from app.api.sync_models import (
    AccountMatchOut,
    DiscoveredAccountOut,
    DiscoveryEntryOut,
    DiscoveryResultOut,
    PlanAccountOut,
    PlanInstanceOut,
    StartedSync,
    TaskStatusOut,
)
from app.core.importers import plan
from app.core.importers.discovery import match_discovered
from app.core.plugins.fetch import SecretText
from app.core.tasks import (
    DiscoveryResult,
    InstanceBusy,
    InvalidAnswer,
    JobEnv,
    PromptNotOpen,
    Task,
    TaskActive,
    TaskRegistry,
    start_task,
)
from app.utils import clock

router = APIRouter(prefix="/api/sync")

# ---- error mapping -------------------------------------------------------------------------
# Unknown instance or account, a disabled instance, a closed or unlinked account and a discovery of an
# instance without transactions are mapped where their errors live (`importers.py`).

map_error(plan.InstanceForbidden, 403, "forbidden")
map_error(plan.NotAFetchSource, 409, "not_a_fetch_source")
map_error(plan.ImporterUnavailable, 409, "importer_unavailable")
map_error(plan.StartNotEditable, 422, "start_not_editable")
map_error(plan.NothingToSync, 422, "nothing_to_sync")


def _refused(*location: str) -> Callable[[Any], Any]:
    """The details of a 422 that names the field: the shape of a validation problem, without the input."""

    def details(exc: Any) -> Any:
        return [{"location": ["body", *location, exc.field], "message": str(exc), "type": "value_error"}]

    return details


map_error(plan.InvalidItem, 422, "validation_error", details=_refused("items"))
map_error(TaskActive, 409, "task_active", details=lambda exc: {"task_id": exc.task_id})
map_error(InstanceBusy, 409, "instance_busy", details=lambda exc: {"instance_ids": list(exc.instance_ids)})
map_error(PromptNotOpen, 409, "conflict", details=lambda exc: {"reason": exc.reason})
map_error(InvalidAnswer, 422, "validation_error", details=_refused())

TaskId = Annotated[str, Path(min_length=1, max_length=64)]


# ---- what a route needs from the app ----------------------------------------------------------


def registry_of(request: Request) -> TaskRegistry:
    registry: TaskRegistry = request.app.state.tasks
    return registry


def job_env(request: Request, user_id: int) -> JobEnv:
    """What a job needs: the engine, the registered importers, today in the household's zone and who
    started it."""
    app = request.app
    return JobEnv(app.state.engine, app.state.importers, today_of(request), user_id)


def today_of(request: Request) -> date:
    return clock.today(request.app.state.config.timezone)


def loop_of(request: Request) -> asyncio.AbstractEventLoop:
    """The loop a task launched from the threadpool runs on (set when the app's lifespan starts)."""
    loop: asyncio.AbstractEventLoop | None = request.app.state.loop
    if loop is None:
        raise RuntimeError("the application has not started (lifespan startup did not run)")
    return loop


def _task_of(request: Request, task_id: str, user_id: int) -> Task:
    """The user's task; another user's, an unknown one and an evicted one are all 404."""
    task = registry_of(request).get(task_id, user_id)
    if task is None:
        raise ApiError(404, "not_found", "no such task")
    return task


def status_out(engine: Engine, task: Task) -> TaskStatusOut:
    """The status; for an ended discovery its accounts, each matched to the household's accounts now."""
    st = task.status()
    result: DiscoveryResultOut | None = None
    if st.status == "ended" and isinstance(st.result, DiscoveryResult):
        with engine.connect() as conn:
            entries = match_discovered(conn, st.result.instance_id, st.result.accounts)
        result = DiscoveryResultOut(
            instance_id=st.result.instance_id,
            accounts=[
                DiscoveryEntryOut(
                    account=DiscoveredAccountOut(
                        external_ref=e.account.external_ref,
                        name=e.account.name,
                        currency=e.account.currency,
                        kind_hint=e.account.kind_hint,
                        capabilities=sorted(e.account.capabilities),  # type: ignore[arg-type]
                    ),
                    linked_account_id=e.linked_account_id,
                    matches_account=(
                        None
                        if e.matches_account is None
                        else AccountMatchOut(id=e.matches_account.id, closed=e.matches_account.closed)
                    ),
                )
                for e in entries
            ],
        )
    return TaskStatusOut(
        task_id=st.task_id,
        kind=st.kind,
        status=st.status,
        aborting=st.aborting,
        outcome=st.outcome,
        last_event_id=st.last_event_id,
        result=result,
    )


# ---- the plan and the start ----------------------------------------------------------------


@router.get("/plan")
def read_sync_plan(request: Request, user: CurrentUser, engine: EngineDep) -> list[PlanInstanceOut]:
    """What "sync everything" would do for the user, per instance and account."""
    with engine.connect() as conn:
        instances = plan.read_plan(
            conn,
            user.id,
            request.app.state.importers,
            today_of(request),
            busy=registry_of(request).held_instances(),
        )
    return [
        PlanInstanceOut(
            instance_id=i.instance_id,
            importer=i.importer,
            label=i.label,
            busy=i.busy,
            accounts=[
                PlanAccountOut(
                    account_id=a.account_id,
                    external_ref=a.external_ref,
                    since=a.since,
                    since_source=a.since_source,
                    editable=a.editable,
                )
                for a in i.accounts
            ],
            documents_since=i.documents_since,
        )
        for i in instances
    ]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SyncItem(_Body):
    """One thing to fetch: an instance, one account of it (with a `since` only if it has no coverage),
    or one kind of it."""

    instance_id: EntityId
    account_id: EntityId | None = None
    kind: Literal["transactions", "documents"] | None = None
    since: date | None = None


class StartSync(_Body):
    items: list[SyncItem] | None = None  # absent: everything the user may run


@router.post("", status_code=202)
def start_sync(
    request: Request, user: CurrentUser, engine: EngineDep, body: StartSync | None = None
) -> StartedSync:
    """Start a sync, validated as a whole: nothing starts if any item is refused."""
    items = (
        None
        if body is None or body.items is None
        else [plan.ItemRequest(i.instance_id, i.account_id, i.kind, i.since) for i in body.items]
    )
    with engine.connect() as conn:
        jobs = plan.plan_start(conn, user.id, items, request.app.state.importers, today_of(request))
    started = start_task(
        registry_of(request),
        job_env(request, user.id),
        user.id,
        "sync",
        jobs,
        skip_busy=items is None,  # "everything" leaves a held instance out and says so; an item does not
        loop=loop_of(request),
    )
    return StartedSync(task_id=started.task.task_id, busy=list(started.busy))


# ---- the active task and a task's status ----------------------------------------------------


@router.get("/active", responses={200: {"model": TaskStatusOut}, 204: {"description": "No task is running."}})
def active_sync(request: Request, user: CurrentUser, engine: EngineDep) -> Any:
    """The user's running task, so a reloaded tab can reattach; 204 when there is none."""
    task = registry_of(request).active(user.id)
    if task is None:
        return Response(status_code=204)
    return status_out(engine, task)


@router.get("/tasks/{task_id}")
def sync_task_status(
    task_id: TaskId, request: Request, user: CurrentUser, engine: EngineDep
) -> TaskStatusOut:
    return status_out(engine, _task_of(request, task_id, user.id))


# ---- the event stream -----------------------------------------------------------------------

_EVENTS_OK: dict[int | str, dict[str, Any]] = {
    200: {
        "description": (
            "Server-Sent Events: `retry: 3000`, then one frame per event (`id`, `event`, `data`), a "
            "`: keepalive` comment while idle, closed after `task_ended`. `event` is a key of "
            "`SyncEventPayloads` and `data` the JSON of its value."
        ),
        "content": {"text/event-stream": {"schema": {"$ref": "#/components/schemas/SyncEventPayloads"}}},
    },
    404: {"model": ErrorEnvelope, "description": "No such task (another user's included)."},
}


def _frame(event_id: int, name: str, data: Any) -> bytes:
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    return f"id: {event_id}\nevent: {name}\ndata: {payload}\n\n".encode()


def _after(header: str | None) -> int:
    """`Last-Event-ID`: the events after it. Absent or not a number: the whole task."""
    return int(header) if header is not None and header.strip().isdigit() else 0


@router.get("/tasks/{task_id}/events", responses=_EVENTS_OK)
async def sync_task_events(
    task_id: TaskId,
    request: Request,
    user: CurrentUser,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    """The task's events, replayed from the start (or after `Last-Event-ID`), then live."""
    task = _task_of(request, task_id, user.id)
    engine: Engine = request.app.state.engine
    start = _after(last_event_id)

    async def body() -> AsyncIterator[bytes]:
        loop = asyncio.get_running_loop()
        woken = asyncio.Event()

        def wake() -> None:  # called from whichever thread emitted
            loop.call_soon_threadsafe(woken.set)

        handle = task.subscribe(wake)  # an attached stream
        try:
            yield b"retry: 3000\n\n"
            last = start
            while True:
                woken.clear()  # before reading, so a wake-up between the read and the wait is kept
                events = task.events_after(last)
                for event in events:
                    data: Any = event.data
                    if event.name == "run_finished" and event.data.get("account_id") is not None:
                        currencies = await asyncio.to_thread(account_currencies, engine)
                        data = to_json(data, currency=currencies.get(event.data["account_id"]))
                    yield _frame(event.id, event.name, data)
                    last = event.id
                    if event.name == "task_ended":
                        return
                if events:
                    continue
                if task.ended and any(e.name == "task_ended" for e in task.events_after(0)):
                    return  # reattached after `task_ended`: nothing more will come
                try:
                    await asyncio.wait_for(woken.wait(), task.tuning.keepalive_s)
                except TimeoutError:
                    yield b": keepalive\n\n"
        finally:
            task.unsubscribe(handle)

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---- answering and aborting -----------------------------------------------------------------


class TaskInput(_Body):
    """An answer to the open prompt, or a cancel of it. `value` is a secret: never echoed or logged."""

    prompt_id: str
    value: SecretStr | None = None
    cancel: bool = False


@router.post("/tasks/{task_id}/input", status_code=204)
def answer_sync_prompt(task_id: TaskId, body: TaskInput, request: Request, user: CurrentUser) -> Response:
    task = _task_of(request, task_id, user.id)
    value = None if body.value is None else SecretText(body.value.get_secret_value())
    task.answer(body.prompt_id, value, cancel=body.cancel)
    return Response(status_code=204)


@router.post("/tasks/{task_id}/abort", status_code=202)
def abort_sync_task(
    task_id: TaskId, request: Request, response: Response, user: CurrentUser, engine: EngineDep
) -> TaskStatusOut:
    """Stop the task: 202 while it was running (it ends once the current call returns); 200 and no
    change for one that has ended."""
    task = _task_of(request, task_id, user.id)
    if task.ended:
        response.status_code = 200
    task.abort()
    return status_out(engine, task)
