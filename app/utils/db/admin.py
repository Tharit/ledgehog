"""Database-level administration for disposable databases (architecture §9).

Only names with a disposable prefix (`test_`, `tpl_`, `dev_`) can be created or
dropped here, so a typo or a bad variable can never touch a real database. Each
database carries its creation time in its comment, which is what the sweeper
reads (PostgreSQL keeps no creation time of its own).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

import psycopg
from psycopg import sql

from app.utils import clock
from app.utils.config import Config

PREFIXES = ("test_", "tpl_", "dev_")
_NAME = re.compile(r"^(test|tpl|dev)_[a-z0-9_]{1,50}$")
_STAMP = "ledgehog-created:"


@dataclass(frozen=True, slots=True)
class DatabaseInfo:
    name: str
    created_at: datetime | None


def connect(cfg: Config) -> psycopg.Connection[tuple[object, ...]]:
    """An autocommit connection to the database `cfg` names."""
    return psycopg.connect(
        host=cfg.db.host,
        port=cfg.db.port,
        dbname=cfg.db.name,
        user=cfg.db.user,
        password=cfg.db.password.reveal(),
        autocommit=True,
    )


def check_name(name: str) -> str:
    if not _NAME.match(name):
        raise ValueError(f"not a disposable database name: {name!r}")
    return name


def stamp(cfg: Config, name: str, when: datetime) -> None:
    check_name(name)
    with connect(cfg) as conn:
        conn.execute(
            sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                sql.Identifier(name), sql.Literal(_STAMP + when.isoformat())
            )
        )


def create_database(cfg: Config, name: str, *, template: str | None = None) -> None:
    check_name(name)
    if template is not None:
        check_name(template)
    query = sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name))
    if template is not None:
        query += sql.SQL(" TEMPLATE {}").format(sql.Identifier(template))
    with connect(cfg) as conn:
        conn.execute(query)
    stamp(cfg, name, clock.now())


def drop_database(cfg: Config, name: str) -> None:
    check_name(name)
    with connect(cfg) as conn:
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        )


def rename_database(cfg: Config, old: str, new: str) -> None:
    check_name(old)
    check_name(new)
    with connect(cfg) as conn:
        conn.execute(
            sql.SQL("ALTER DATABASE {} RENAME TO {}").format(
                sql.Identifier(old), sql.Identifier(new)
            )
        )


def database_exists(cfg: Config, name: str) -> bool:
    with connect(cfg) as conn:
        return conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone() is not None


def list_databases(cfg: Config, prefixes: tuple[str, ...] = PREFIXES) -> list[DatabaseInfo]:
    """Every database on the server whose name has one of `prefixes`."""
    with connect(cfg) as conn:
        rows = conn.execute(
            "SELECT d.datname, shobj_description(d.oid, 'pg_database') "
            "FROM pg_database d ORDER BY d.datname"
        ).fetchall()
    out: list[DatabaseInfo] = []
    for name, comment in rows:
        if not isinstance(name, str) or not name.startswith(prefixes):
            continue
        created = None
        if isinstance(comment, str) and comment.startswith(_STAMP):
            created = datetime.fromisoformat(comment[len(_STAMP) :])
        out.append(DatabaseInfo(name, created))
    return out


def sweep(
    cfg: Config,
    *,
    older_than: timedelta,
    dry_run: bool = False,
    prefixes: tuple[str, ...] = PREFIXES,
) -> list[str]:
    """Drop disposable databases older than `older_than`; returns the names.

    A `test_`/`tpl_` database without a stamp is an orphan from a crash between
    create and stamp and counts as old. A `dev_` one without a stamp is left
    alone: someone may have made it by hand.
    """
    cutoff = clock.now() - older_than
    dropped: list[str] = []
    for info in list_databases(cfg, prefixes):
        if not _NAME.match(info.name):
            continue
        if info.created_at is None:
            old = not info.name.startswith("dev_")
        else:
            old = info.created_at < cutoff
        if not old:
            continue
        dropped.append(info.name)
        if not dry_run:
            drop_database(cfg, info.name)
    return dropped
