"""A ledger with its base currency (EUR) on a rolled-back connection."""

from __future__ import annotations

import pytest
from sqlalchemy import Connection, text

from tests.fixtures import ledger_seed as seed


@pytest.fixture
def ledger(db_conn: Connection) -> Connection:
    db_conn.execute(text("INSERT INTO ledger_setting (base_currency) VALUES ('EUR')"))
    return db_conn


@pytest.fixture
def giro(ledger: Connection) -> int:
    return seed.account(ledger, "Giro")
