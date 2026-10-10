"""Fixtures for the importer instance tests (the account fixtures are reused)."""

from __future__ import annotations

from typing import Any

import pytest

from app.core.accounts import create_account
from app.core.importers.instances import create_instance
from tests.core.accounts import conftest as _accounts
from tests.core.accounts.conftest import Db

db = _accounts.db  # fixtures shared with the account tests
settle_spy = _accounts.settle_spy


def make_instance(db: Db, **kw: Any) -> int:
    kw.setdefault("importer", "csv")
    kw.setdefault("label", "Giro CSV")
    kw.setdefault("settings", {})
    kw.setdefault("emits", ["transactions"])
    kw.setdefault("access", "shared")
    return create_instance(db.engine, **kw)


def make_acct(db: Db, name: str = "Giro", **kw: Any) -> int:
    kw.setdefault("kind", "checking")
    kw.setdefault("currency", "EUR")
    return create_account(db.engine, name=name, **kw)


@pytest.fixture
def user_id(db: Db) -> int:
    db.run("INSERT INTO app_user (login, pw_hash, display_name) VALUES ('anna', 'x', 'Anna')")
    return int(db.one("SELECT id FROM app_user")[0])
