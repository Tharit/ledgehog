from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import Engine

from tests.core.units.scene import Scene
from tests.invariants.helpers import make_run


def build_scene(engine: Engine, make_account: Callable[..., int]) -> Scene:
    with engine.begin() as conn:
        checking = make_account(conn, name="Checking")
        savings = make_account(conn, name="Savings", kind="savings")
        cash = make_account(conn, name="Cash", kind="cash")
        usd = make_account(conn, name="Dollars", kind="cash", currency="USD")
        run = make_run(conn, checking)
    return Scene(engine, checking, savings, cash, usd, run)


@pytest.fixture
def scene(isolated_engine: Engine, make_account: Callable[..., int]) -> Scene:
    return build_scene(isolated_engine, make_account)
