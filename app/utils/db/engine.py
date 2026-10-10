"""The synchronous SQLAlchemy Core engine over psycopg3 (architecture §2, §5.7).

Every connection the pool opens gets `ledger.max_rate_age` (read by the schema
function `base_value()`) and a guard that refuses float parameters: money is an
integer in minor units, rates are Decimal, and a float reaching the driver is a
bug (architecture §5.6).
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.adapt import Dumper
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL

from app.utils.config import Config


class _RefuseFloat(Dumper):
    def dump(self, obj: Any) -> bytes:
        raise TypeError("float parameters are refused: use int minor units or Decimal")


def database_url(cfg: Config) -> URL:
    return URL.create(
        "postgresql+psycopg",
        username=cfg.db.user,
        password=cfg.db.password.reveal(),
        host=cfg.db.host,
        port=cfg.db.port,
        database=cfg.db.name,
    )


def max_rate_age_setting(cfg: Config) -> str:
    return f"{cfg.max_rate_age_days} days"


def make_engine(cfg: Config, *, pool_size: int = 5, max_overflow: int = 5) -> Engine:
    engine = create_engine(
        database_url(cfg),
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
    )
    max_rate_age = max_rate_age_setting(cfg)

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn: psycopg.Connection[Any], _record: object) -> None:
        dbapi_conn.adapters.register_dumper(float, _RefuseFloat)
        previous = dbapi_conn.autocommit
        dbapi_conn.autocommit = True
        try:
            dbapi_conn.execute("SELECT set_config('ledger.max_rate_age', %s, false)", (max_rate_age,))
        finally:
            dbapi_conn.autocommit = previous

    return engine
