"""Discovering the accounts a credential can reach (architecture §4.1, §5.3).

A discovery is a task like a sync: it signs in (possibly prompting), lists the accounts and closes. The
list is the result on the task's status (`GET /api/sync/tasks/{id}`), each account with what it already is
here; this route only starts it. Creating or linking an account from the list uses the ordinary account and
link operations.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.ids import PathId
from app.api.routers.sync import job_env, loop_of, registry_of
from app.api.session import CurrentUser, EngineDep
from app.api.sync_models import StartedDiscovery
from app.core.importers import plan
from app.core.tasks import start_task

router = APIRouter(prefix="/api/importers/instances")


@router.post("/{instance_id}/discover-accounts", status_code=202)
def discover_accounts(
    instance_id: PathId, request: Request, user: CurrentUser, engine: EngineDep
) -> StartedDiscovery:
    """Start a discovery, refused as a sync start is, and 409 `not_an_account_source` for an instance that
    does not emit transactions."""
    with engine.connect() as conn:
        job = plan.plan_discovery(conn, user.id, instance_id, request.app.state.importers)
    started = start_task(
        registry_of(request),
        job_env(request, user.id),
        user.id,
        "discovery",
        [job],
        loop=loop_of(request),
    )
    return StartedDiscovery(task_id=started.task.task_id)
