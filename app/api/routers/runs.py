"""The run list and reverting a run (architecture §4.1, §4.4).

`revert` is the previewed operation: `dry_run` returns what a revert would remove or unpair, and
the version of every entry it writes, which the confirming request sends back.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from app.api.errors import map_error
from app.api.ids import MAX_ID, EntityId, EntityVersion, PathId, QueryId
from app.api.routers.importers import account_currencies, to_json
from app.api.session import CurrentUser, EngineDep
from app.core.domain.errors import VersionConflict
from app.core.importers.runs import count_runs, get_run, list_runs
from app.core.ingest.revert import NotLatestRun, NotRevertible, RunMissing, revert_run
from app.utils.db.locks import WriteConflict

router = APIRouter(prefix="/api/importers/runs")

map_error(RunMissing, 404, "not_found")
map_error(NotLatestRun, 409, "not_latest_run", details=lambda exc: {"newer_run_id": exc.newer_run_id})
map_error(NotRevertible, 409, "not_revertible", details=lambda exc: {"reason": exc.reason})
# the entries that moved since they were read, and those the revert writes but the request did not list
map_error(VersionConflict, 409, "conflict", details=lambda exc: {"entry_ids": list(exc.entry_ids)})
map_error(WriteConflict, 409, "try_again")


class RevertBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = False
    expected_versions: dict[EntityId, EntityVersion] | None = None


@router.get("")
def list_import_runs(
    user: CurrentUser,
    engine: EngineDep,
    account_id: QueryId | None = None,
    instance_id: QueryId | None = None,
    status: Literal["running", "ok", "failed", "reverted"] | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=MAX_ID)] = 0,
) -> Any:
    with engine.connect() as conn:
        found = list_runs(
            conn, account_id=account_id, instance_id=instance_id, status=status, limit=limit, offset=offset
        )
        total = count_runs(conn, account_id=account_id, instance_id=instance_id, status=status)
    page = {"runs": found, "total": total, "limit": limit, "offset": offset}
    return to_json(page, currencies=account_currencies(engine))


@router.get("/{run_id}")
def get_import_run(run_id: PathId, user: CurrentUser, engine: EngineDep) -> Any:
    with engine.connect() as conn:
        found = get_run(conn, run_id)
    if found is None:
        raise RunMissing(run_id)
    return to_json(found, currencies=account_currencies(engine))


@router.post("/{run_id}/revert")
def revert_import_run(
    run_id: PathId, user: CurrentUser, engine: EngineDep, body: RevertBody | None = None
) -> Any:
    body = body or RevertBody()
    result = revert_run(
        engine,
        run_id,
        user_id=user.id,
        expected_versions=body.expected_versions,
        dry_run=body.dry_run,
    )
    return to_json(result, currencies=account_currencies(engine))
