"""`GET /api/changes` (architecture §4.1, §4.2): whether what a view shows has changed.

The values come from the change register in process memory (`app.core.tasks.changes`); the only database
read is the list of account ids, so that `accounts` holds a value for every account (an account no write has
touched since the start has the start value). No lock. `active_task` is the current user's running task, as
`GET /api/sync/active` finds it: another user's is never shown.

A write's response carries the same values, minus `active_task`, in the `X-Ledger-Changes` header
(`changes_header`, set by the middleware in `app.api.app`).
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import Engine, text

from app.api.session import CurrentUser, EngineDep
from app.core.model.queue import ModelQueue
from app.core.tasks import TaskRegistry
from app.core.tasks.changes import DOCUMENTS, LEDGER, ChangeRegister

router = APIRouter(prefix="/api", tags=["changes"])

HEADER = "X-Ledger-Changes"


class ChangeValues(BaseModel):
    ledger: str
    documents: str
    accounts: dict[str, str]  # account id -> value; every account


class ChangesOut(ChangeValues):
    active_task: str | None  # the current user's running sync or discovery task
    model_pending: int  # entries the model still has to look at (0 without a model); the client polls faster
    model_pending_lines: int  # always 0: the model looks at entries only (kept until the client drops it)


def model_queue_of(request: Request) -> ModelQueue | None:
    queue: ModelQueue | None = getattr(request.app.state, "model", None)
    return queue


def register_of(request: Request) -> ChangeRegister:
    register: ChangeRegister = request.app.state.changes
    return register


def values_of(register: ChangeRegister, engine: Engine) -> ChangeValues:
    with engine.connect() as conn:
        ids = [int(i) for i in conn.execute(text("SELECT id FROM account ORDER BY id")).scalars()]
    return ChangeValues(
        ledger=register.value(LEDGER),
        documents=register.value(DOCUMENTS),
        accounts={str(i): v for i, v in register.accounts(ids).items()},
    )


@router.get("/changes")
def get_changes(request: Request, user: CurrentUser, engine: EngineDep) -> ChangesOut:
    """The change value of the ledger, of the documents and of each account, and the user's active task."""
    values = values_of(register_of(request), engine)
    tasks: TaskRegistry = request.app.state.tasks
    active = tasks.active(user.id)
    queue = model_queue_of(request)
    return ChangesOut(
        **values.model_dump(),
        active_task=active.task_id if active is not None else None,
        model_pending=queue.pending() if queue is not None else 0,
        model_pending_lines=0,
    )
