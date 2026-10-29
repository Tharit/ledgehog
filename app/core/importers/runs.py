"""The run list (spec §5.3, §5.4): what each import run did and whether it can still be reverted.

Read-only; the caller hands in a connection. A run is revertible only when it is the latest
successful, non-reverted transaction run of its account (the predicate revert itself uses,
`latest_ok_runs`), judged against the whole account, never against the filter in use.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import Connection, text

from app.core.ingest.revert import latest_ok_runs

_COLUMNS = (
    "id, importer, importer_instance_id, account_id, emits, status, started_at, finished_at, started_by,"
    " error_text, retryable, covered_from, covered_through, stats, reverted_at, reverted_by"
)


@dataclass(frozen=True)
class RunView:
    id: int
    importer: str
    instance_id: int | None
    account_id: int | None
    kind: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    started_by: int | None
    error_text: str | None
    retryable: bool | None  # a failed run: whether running it again can help; null otherwise
    covered_from: date | None
    covered_through: date | None
    stats: dict[str, Any]
    reverted_at: datetime | None
    reverted_by: int | None
    revertible: bool


def _views(conn: Connection, rows: list[Any]) -> list[RunView]:
    latest = latest_ok_runs(conn, sorted({r.account_id for r in rows if r.account_id is not None}))
    return [
        RunView(
            id=r.id,
            importer=r.importer,
            instance_id=r.importer_instance_id,
            account_id=r.account_id,
            kind=r.emits,
            status=r.status,
            started_at=r.started_at,
            finished_at=r.finished_at,
            started_by=r.started_by,
            error_text=r.error_text,
            retryable=r.retryable,
            covered_from=r.covered_from,
            covered_through=r.covered_through,
            stats=dict(r.stats),
            reverted_at=r.reverted_at,
            reverted_by=r.reverted_by,
            revertible=r.account_id is not None and latest.get(r.account_id) == r.id,
        )
        for r in rows
    ]


_FILTER = (
    " WHERE (CAST(:account AS bigint) IS NULL OR account_id = :account)"
    " AND (CAST(:inst AS bigint) IS NULL OR importer_instance_id = :inst)"
    " AND (CAST(:status AS text) IS NULL OR status = :status)"
)


def count_runs(
    conn: Connection,
    *,
    account_id: int | None = None,
    instance_id: int | None = None,
    status: str | None = None,
) -> int:
    """Every run the filters select, whatever the page."""
    return int(
        conn.execute(
            text("SELECT count(*) FROM import_run" + _FILTER),
            {"account": account_id, "inst": instance_id, "status": status},
        ).scalar_one()
    )


def list_runs(
    conn: Connection,
    *,
    account_id: int | None = None,
    instance_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[RunView]:
    """Runs, newest first (finish time, or start time while running; then id, so the order is total)."""
    rows = conn.execute(
        text(
            f"SELECT {_COLUMNS} FROM import_run"  # noqa: S608
            + _FILTER
            + " ORDER BY COALESCE(finished_at, started_at) DESC, id DESC LIMIT :limit OFFSET :offset"
        ),
        {"account": account_id, "inst": instance_id, "status": status, "limit": limit, "offset": offset},
    ).all()
    return _views(conn, list(rows))


def get_run(conn: Connection, run_id: int) -> RunView | None:
    rows = conn.execute(
        text(f"SELECT {_COLUMNS} FROM import_run WHERE id = :i"),  # noqa: S608
        {"i": run_id},
    ).all()
    return _views(conn, list(rows))[0] if rows else None
