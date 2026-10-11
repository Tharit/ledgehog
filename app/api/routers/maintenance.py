"""Maintenance operations (architecture §4.1): the integrity check and a manual settle."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.session import CurrentUser, EngineDep
from app.core.integrity import check_integrity
from app.core.settle.settle import SettleResult, settle

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])


class ViewCheckOut(BaseModel):
    rows: list[dict[str, Any]]
    truncated: bool


class CheckOut(BaseModel):
    ok: bool
    checks: dict[str, ViewCheckOut]


class SettleOut(BaseModel):
    touched_entry_ids: list[int]
    error: str | None

    @classmethod
    def of(cls, result: SettleResult) -> SettleOut:
        return cls(touched_entry_ids=list(result.touched_entry_ids), error=result.error)


@router.get("/check")
def check(user: CurrentUser, engine: EngineDep) -> CheckOut:
    """Every integrity view; each should be empty (at most 50 rows each are listed)."""
    with engine.connect() as conn:
        report = check_integrity(conn)
    return CheckOut(
        ok=report.ok,
        checks={n: ViewCheckOut(rows=c.rows, truncated=c.truncated) for n, c in report.checks.items()},
    )


@router.post("/settle")
def run_settle(user: CurrentUser, engine: EngineDep) -> SettleOut:
    """Settle now; a failure is the `error` of the result, not an HTTP error (architecture §5.2)."""
    return SettleOut.of(settle(engine))
