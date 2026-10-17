"""Migration 0008: a CSV profile has no `label`; stored csv instances lose the key, other settings stay."""

from __future__ import annotations

import json

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


def _insert(conn: object, importer: str, label: str, settings: dict[str, object]) -> int:
    return int(
        conn.execute(  # type: ignore[attr-defined]
            text(
                "INSERT INTO importer_instance (importer, label, emits, access, settings)"
                " VALUES (:i, :l, ARRAY['transactions'], 'shared', CAST(:s AS jsonb)) RETURNING id"
            ),
            {"i": importer, "l": label, "s": json.dumps(settings)},
        ).scalar_one()
    )


def test_label_is_stripped_from_csv_instances_only(isolated_db: Config) -> None:
    _downgrade(isolated_db, "0007")
    engine = make_engine(isolated_db, pool_size=1, max_overflow=0)
    with engine.begin() as conn:
        old = _insert(conn, "csv", "Giro", {"label": "giro", "quote": '"', "balance": {"label": "Saldo"}})
        clean = _insert(conn, "csv", "Clean", {"quote": '"'})
        other = _insert(conn, "fints", "Bank", {"label": "keep me"})
    engine.dispose()

    migrate.upgrade(isolated_db)

    engine = make_engine(isolated_db, pool_size=1, max_overflow=0)
    with engine.connect() as conn:

        def settings(i: int) -> dict[str, object]:
            return dict(
                conn.execute(text("SELECT settings FROM importer_instance WHERE id = :i"), {"i": i}).scalar_one()
            )

        assert settings(old) == {"quote": '"', "balance": {"label": "Saldo"}}  # nested labels are the profile's
        assert settings(clean) == {"quote": '"'}
        assert settings(other) == {"label": "keep me"}
    engine.dispose()
