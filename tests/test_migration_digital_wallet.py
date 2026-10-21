"""Migration 0011: the account kind `paypal` becomes `digital_wallet`; the downgrade reverses it."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.utils.config import Config
from app.utils.db import migrate
from app.utils.db.engine import make_engine
from tests.test_migration_document_none import _downgrade


def _kinds(cfg: Config) -> dict[str, str]:
    engine = make_engine(cfg, pool_size=1, max_overflow=0)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT name, kind FROM account")).all()
    engine.dispose()
    return {name: kind for name, kind in rows}


def test_paypal_accounts_are_carried_over_and_back(isolated_db: Config, make_account: Any) -> None:
    _downgrade(isolated_db, "0010")
    engine = make_engine(isolated_db, pool_size=1, max_overflow=0)
    with engine.begin() as conn:
        make_account(conn, name="Giro", kind="checking")
        make_account(conn, name="PP", kind="paypal")
    engine.dispose()

    migrate.upgrade(isolated_db)
    assert _kinds(isolated_db) == {"Giro": "checking", "PP": "digital_wallet"}

    _downgrade(isolated_db, "0010")
    assert _kinds(isolated_db) == {"Giro": "checking", "PP": "paypal"}
    migrate.upgrade(isolated_db)
