"""Run the Alembic migration chain (architecture §7). Hand-written SQL only."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig

from app.utils.config import Config
from app.utils.db.engine import make_engine

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"


def alembic_config() -> AlembicConfig:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    return cfg


def upgrade(cfg: Config, revision: str = "head") -> None:
    engine = make_engine(cfg, pool_size=1, max_overflow=0)
    try:
        with engine.begin() as conn:
            alembic = alembic_config()
            alembic.attributes["connection"] = conn
            command.upgrade(alembic, revision)
    finally:
        engine.dispose()
