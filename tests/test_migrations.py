from alembic.script import ScriptDirectory

from app.utils.config import Config
from app.utils.db import admin, migrate


def test_upgrade_is_idempotent_and_records_head(isolated_db: Config):
    # isolated_db is a clone of the migrated template: already at head
    migrate.upgrade(isolated_db)
    migrate.upgrade(isolated_db)
    head = ScriptDirectory.from_config(migrate.alembic_config()).get_heads()
    assert len(head) == 1
    with admin.connect(isolated_db) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchall() == [(head[0],)]


def test_every_migration_is_hand_written_sql():
    from tests.conftest import ROOT

    for path in (ROOT / "migrations" / "versions").glob("*.py"):
        text = path.read_text()
        assert "autogenerate" not in text
        assert "op.execute" in text or "driver_connection" in text


def test_0002_downgrades_to_the_baseline_and_upgrades_again(isolated_db: Config):
    from alembic import command

    from app.utils.db.engine import make_engine

    def has_kind() -> bool:
        with admin.connect(isolated_db) as conn:
            return bool(
                conn.execute(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'balance_record' AND column_name = 'kind'"
                ).fetchall()
            )

    engine = make_engine(isolated_db, pool_size=1, max_overflow=0)
    try:
        with engine.begin() as conn:
            alembic = migrate.alembic_config()
            alembic.attributes["connection"] = conn
            command.downgrade(alembic, "0001")
        assert has_kind()
        migrate.upgrade(isolated_db)
        assert not has_kind()
    finally:
        engine.dispose()
