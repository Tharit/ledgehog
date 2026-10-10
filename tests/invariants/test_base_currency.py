"""ledger_setting and trg_base_currency_fixed (8.7)."""

from __future__ import annotations

import pytest
from sqlalchemy import Connection, text

from tests.invariants.helpers import (
    CHECK_VIOLATION,
    FK_VIOLATION,
    RAISE_EXCEPTION,
    UNIQUE_VIOLATION,
    rejects,
    scalar,
)


@pytest.fixture
def started(db_conn: Connection) -> Connection:
    db_conn.execute(text("INSERT INTO ledger_setting (base_currency) VALUES ('EUR')"))
    return db_conn


def test_the_base_currency_can_be_written_once(started: Connection) -> None:
    assert scalar(started, "SELECT base_currency FROM ledger_setting") == "EUR"


def test_changing_the_base_currency_is_refused(started: Connection) -> None:
    with rejects(started, sqlstate=RAISE_EXCEPTION, message="the base currency is fixed"):
        started.execute(text("UPDATE ledger_setting SET base_currency = 'USD'"))
    assert scalar(started, "SELECT base_currency FROM ledger_setting") == "EUR"


def test_rewriting_the_same_base_currency_is_accepted(started: Connection) -> None:
    started.execute(text("UPDATE ledger_setting SET base_currency = 'EUR'"))


def test_there_is_exactly_one_row(started: Connection) -> None:
    with rejects(started, sqlstate=UNIQUE_VIOLATION, constraint="ledger_setting_pkey"):
        started.execute(text("INSERT INTO ledger_setting (base_currency) VALUES ('USD')"))
    with rejects(started, sqlstate=CHECK_VIOLATION, constraint="ledger_setting_singleton_check"):
        started.execute(text("INSERT INTO ledger_setting (singleton, base_currency) VALUES (false, 'USD')"))


def test_the_base_currency_must_be_a_known_currency(db_conn: Connection) -> None:
    with rejects(db_conn, sqlstate=FK_VIOLATION):
        db_conn.execute(text("INSERT INTO ledger_setting (base_currency) VALUES ('XXX')"))


@pytest.mark.xfail(
    strict=True,
    reason=(
        "schema.sql 8.7 (lines 1267-1280) guards only UPDATE OF base_currency: the row can be deleted and "
        "re-inserted with another currency, bypassing 'fixed once written'. Reported, schema not edited."
    ),
)
def test_deleting_the_base_currency_row_is_refused(started: Connection) -> None:
    with rejects(started, sqlstate=RAISE_EXCEPTION):
        started.execute(text("DELETE FROM ledger_setting"))
