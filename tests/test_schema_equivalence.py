"""A database built by the migration chain equals schema.sql applied to an empty one (architecture §7)."""

import uuid
from pathlib import Path

import pytest

from app.utils.config import Config
from app.utils.db import admin
from tests import catalog

SCHEMA_SQL = Path(__file__).resolve().parent.parent / "spec" / "schema.sql"


@pytest.fixture
def schema_sql_db(admin_cfg: Config):
    name = f"test_{uuid.uuid4().hex}"
    admin.create_database(admin_cfg, name)
    cfg = admin_cfg.with_database(name)
    try:
        with admin.connect(cfg) as conn:
            conn.execute(SCHEMA_SQL.read_text())
        yield cfg
    finally:
        admin.drop_database(admin_cfg, name)


def test_migrations_match_schema_sql(session_db: Config, schema_sql_db: Config):
    with admin.connect(session_db) as a, admin.connect(schema_sql_db) as b:
        migrated, reference = catalog.snapshot(a), catalog.snapshot(b)
    assert catalog.diff(migrated, reference) == []
    # the comparison must not be vacuous
    assert len(migrated["relations"]) > 30
    assert len(migrated["triggers"]) > 10
    assert len(migrated["data:currency"]) > 100
    assert migrated["extensions"] == reference["extensions"]
    assert ("pg_trgm",) in migrated["extensions"]


def test_the_comparison_detects_drift(session_db: Config, schema_sql_db: Config):
    with admin.connect(schema_sql_db) as b:
        b.execute("INSERT INTO currency VALUES ('ZZZ', 2)")
        b.execute("CREATE INDEX ix_drift ON account (name)")
        reference = catalog.snapshot(b)
    with admin.connect(session_db) as a:
        migrated = catalog.snapshot(a)
    problems = catalog.diff(migrated, reference)
    assert any(p.startswith("[data:currency]") for p in problems)
    assert any(p.startswith("[indexes]") for p in problems)
