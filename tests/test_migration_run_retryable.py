"""Migration 0009: `import_run.retryable`, backfilled for failed runs from the error class prefix."""

from __future__ import annotations

from alembic import command
from sqlalchemy import text

from app.utils.config import Config
from app.utils.db import migrate
from app.utils.db.engine import make_engine


def _downgrade(cfg: Config, revision: str) -> None:
    engine = make_engine(cfg, pool_size=1, max_overflow=0)
    try:
        with engine.begin() as conn:
            alembic = migrate.alembic_config()
            alembic.attributes["connection"] = conn
            command.downgrade(alembic, revision)
    finally:
        engine.dispose()


def _insert(conn: object, status: str, error: str | None) -> int:
    return int(
        conn.execute(  # type: ignore[attr-defined]
            text(
                "INSERT INTO import_run (importer, emits, status, finished_at, error_text)"
                " VALUES ('test', 'rates', :s, now(), :e) RETURNING id"
            ),
            {"s": status, "e": error},
        ).scalar_one()
    )


def test_failed_runs_are_backfilled_from_their_error_class(isolated_db: Config) -> None:
    _downgrade(isolated_db, "0008")
    engine = make_engine(isolated_db, pool_size=1, max_overflow=0)
    with engine.begin() as conn:
        ids = {
            "auth": _insert(conn, "failed", "AuthRejected: wrong PIN"),
            "bank": _insert(conn, "failed", "SourceUnavailable: bank down"),
            "stopped": _insert(
                conn, "failed", "interrupted: the application stopped before the run finished"
            ),
            "parse": _insert(conn, "failed", "ParseFailed: no header row"),
            "other": _insert(conn, "failed", "IntegrityError: unexpected error"),
            "ok": _insert(conn, "ok", None),
        }
    engine.dispose()

    migrate.upgrade(isolated_db)

    engine = make_engine(isolated_db, pool_size=1, max_overflow=0)
    with engine.connect() as conn:
        got = {
            name: conn.execute(text("SELECT retryable FROM import_run WHERE id = :i"), {"i": i}).scalar_one()
            for name, i in ids.items()
        }
    engine.dispose()
    assert got == {
        "auth": True,
        "bank": True,
        "stopped": True,
        "parse": False,
        "other": False,
        "ok": None,
    }
