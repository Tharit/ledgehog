import psycopg
import pytest
from sqlalchemy import text

from app.core.domain.money import Money
from app.utils.config import Config
from app.utils.db import admin
from app.utils.db.engine import make_engine


def test_every_pooled_connection_gets_max_rate_age(isolated_db: Config):
    engine = make_engine(isolated_db, pool_size=2, max_overflow=0)
    try:
        for _ in range(3):  # connections are reused and set once on open
            with engine.connect() as conn:
                assert (
                    conn.execute(text("SELECT current_setting('ledger.max_rate_age')")).scalar_one()
                    == "7 days"
                )
        with engine.connect() as a, engine.connect() as b:
            for conn in (a, b):
                age = conn.execute(
                    text("SELECT current_setting('ledger.max_rate_age')::interval")
                ).scalar_one()
                assert age.days == 7
    finally:
        engine.dispose()


def test_max_rate_age_follows_configuration(isolated_db: Config):
    import dataclasses

    cfg = dataclasses.replace(isolated_db, max_rate_age_days=3)
    engine = make_engine(cfg)
    try:
        with engine.connect() as conn:
            assert (
                conn.execute(text("SELECT current_setting('ledger.max_rate_age')")).scalar_one() == "3 days"
            )
    finally:
        engine.dispose()


def test_base_value_runs_on_engine_connections_and_fails_without_the_setting(db_conn, isolated_db: Config):
    db_conn.execute(text("INSERT INTO ledger_setting (base_currency) VALUES ('EUR')"))
    assert db_conn.execute(text("SELECT base_value(100, 'EUR', DATE '2026-01-01')")).scalar_one() == 100
    # a connection that did not come from the engine has no setting: an error, never a default
    with admin.connect(isolated_db) as raw:
        raw.execute("INSERT INTO ledger_setting (base_currency) VALUES ('EUR')")
        with pytest.raises(psycopg.errors.UndefinedObject):
            raw.execute("SELECT base_value(100, 'EUR', DATE '2026-01-01')")


def test_float_binding_never_reaches_psycopg(db_conn):
    with pytest.raises(Exception, match="float"):
        db_conn.execute(text("SELECT CAST(:x AS numeric)"), {"x": 1.5})


def test_integer_money_binds_fine(db_conn):
    m = Money(-1234, "EUR")
    assert db_conn.execute(text("SELECT CAST(:x AS bigint)"), {"x": m.minor}).scalar_one() == -1234
