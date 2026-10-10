from app.utils.config import Config
from app.utils.db import admin, migrate


def test_upgrade_is_idempotent_and_records_head(isolated_db: Config):
    # isolated_db is a clone of the migrated template: already at head
    migrate.upgrade(isolated_db)
    migrate.upgrade(isolated_db)
    with admin.connect(isolated_db) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchall() == [("0001",)]


def test_every_migration_is_hand_written_sql():
    from tests.conftest import ROOT

    for path in (ROOT / "migrations" / "versions").glob("*.py"):
        text = path.read_text()
        assert "autogenerate" not in text
        assert "op.execute" in text or "driver_connection" in text
