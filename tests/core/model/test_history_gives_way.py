"""History gives way to the model on a mixed counterparty (spec §5.9 pass 2 and 3, D241): the entry is listed
with the categories history counted, the answer replaces history's proposal, and a changed set of those
categories asks again."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Engine, text

from app.core.settle import settle
from tests.core.model.rig import Rig, entry_row
from tests.core.model.test_worker import _process_head
from tests.core.settle.test_resolution_step import _confirmed, _new
from tests.invariants.helpers import make_category

MakeAccount = Callable[..., int]
NAME = "Friend Max"


@pytest.fixture
def acct(isolated_engine: Engine, make_account: MakeAccount) -> int:
    with isolated_engine.begin() as conn:
        return make_account(conn)


class World:
    def __init__(self, engine: Engine, acct: int) -> None:
        self.engine, self.acct = engine, acct
        with engine.begin() as conn:
            self.rent = make_category(conn, "Rent")
            self.dining = make_category(conn, "Dining")
            self.fun = make_category(conn, "Fun")
            self.misc = make_category(conn, "Misc")
        self.vote(self.rent, "Miete Juni", 3)
        self.vote(self.dining, "Pizza Essen Freitag", 2)

    def vote(self, category: int, purpose: str, n: int) -> None:
        with self.engine.begin() as conn:
            for _ in range(n):
                _confirmed(conn, self.acct, name=NAME, category=category, payee=None, purpose=purpose)

    def entry(self, purpose: str) -> int:
        with self.engine.begin() as conn:
            return _new(conn, self.acct, counterparty_name=NAME, purpose=purpose)


@pytest.fixture
def world(rig: Rig, acct: int) -> World:
    return World(rig.engine, acct)


def _user_message(rig: Rig, i: int = 0) -> str:
    return str(json.loads(rig.endpoint.requests[i].content)["messages"][1]["content"])


def test_a_mixed_counterparty_is_listed_with_its_categories_a_unanimous_one_is_not(
    rig: Rig, world: World
) -> None:
    mixed = world.entry("Konzert Karten")  # no similar purpose: all five matches, 3 of 5
    sure = world.entry("Pizza Essen Samstag")  # the similar ones are unanimous
    assert settle(rig.engine).error is None
    row = entry_row(rig.engine, mixed)
    assert row.category_id == world.rent  # until the model answers, history's majority stands
    assert row.derivation["category"]["pass"] == "history"
    sure_row = entry_row(rig.engine, sure)
    assert sure_row.category_id == world.dining and sure_row.derivation["category"]["basis"][
        "matched_on"
    ] == ("counterparty_name+booking_text+purpose")
    assert rig.queue.entry_ids() == {mixed}
    item = rig.queue.head()
    assert item is not None
    assert rig.queue.categories_of(item) == (world.dining, world.rent)  # path order
    assert rig.endpoint.requests == []


def test_the_model_is_told_the_categories_and_its_answer_replaces_history(rig: Rig, world: World) -> None:
    e = world.entry("Konzert Karten")
    settle(rig.engine)
    rig.endpoint.category_id = world.fun
    _process_head(rig)
    msg = _user_message(rig)
    assert "Expense > Dining" in msg and "Expense > Rent" in msg
    assert msg.index("Expense > Dining") < msg.index("Expense > Rent")  # path order
    assert not any(ch.isdigit() for ch in msg)  # no counts
    assert "Miete" not in msg and "Pizza" not in msg  # no past text
    row = entry_row(rig.engine, e)
    assert row.category_id == world.fun and row.derivation["category"]["pass"] == "llm"
    assert settle(rig.engine).touched_entry_ids == ()  # stable: the answer stands over history
    assert rig.queue.pending() == 0 and len(rig.endpoint.requests) == 1


def test_a_no_category_answer_replaces_history_too(rig: Rig, world: World) -> None:
    e = world.entry("Konzert Karten")
    settle(rig.engine)
    rig.endpoint.category_id = None
    _process_head(rig)
    row = entry_row(rig.engine, e)
    assert row.category_id is None and row.derivation["category"]["basis"]["none"] is True
    assert settle(rig.engine).touched_entry_ids == ()
    row = entry_row(rig.engine, e)
    assert row.category_id is None and row.derivation["category"]["pass"] == "llm"
    assert rig.queue.pending() == 0


def test_without_an_answer_history_stands_and_a_model_down_changes_nothing(rig: Rig, world: World) -> None:
    e = world.entry("Konzert Karten")
    settle(rig.engine)
    rig.endpoint.status = 500
    _process_head(rig)  # unreachable: the list empties
    assert rig.queue.pending() == 0
    row = entry_row(rig.engine, e)
    assert row.category_id == world.rent and row.derivation["category"]["pass"] == "history"


def test_changed_counts_keep_the_answer_a_new_category_in_the_top_three_asks_again(
    rig: Rig, world: World
) -> None:
    e = world.entry("Konzert Karten")
    settle(rig.engine)
    rig.endpoint.category_id = world.fun
    _process_head(rig)
    world.vote(world.rent, "Miete Juli", 2)  # counts move, the categories do not
    settle(rig.engine)
    row = entry_row(rig.engine, e)
    assert row.derivation["category"]["pass"] == "llm" and rig.queue.pending() == 0
    world.vote(world.misc, "Spiele", 6)  # a third category enters the top three (and no majority is left)
    settle(rig.engine)
    row = entry_row(rig.engine, e)
    assert "category" not in row.derivation  # the answer is stale: it no longer stands
    assert rig.queue.entry_ids() == {e}
    item = rig.queue.head()
    assert item is not None and rig.queue.categories_of(item) == (world.dining, world.misc, world.rent)
    rig.endpoint.category_id = world.misc
    _process_head(rig)
    assert len(rig.endpoint.requests) == 2
    assert entry_row(rig.engine, e).category_id == world.misc


def test_the_answer_is_dropped_when_history_became_unanimous_meanwhile(rig: Rig, world: World) -> None:
    e = world.entry("Konzert Karten")
    settle(rig.engine)
    changed: dict[str, Any] = {}

    def during() -> None:
        # the mixed votes are gone from the entry's point of view: history now proposes unanimously
        with rig.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE ledger_entry SET derivation = jsonb_set(derivation, '{category,basis}',"
                    ' \'{"agree": 5, "of": 5, "matched_on": "counterparty_name+booking_text"}\')'
                    " WHERE id = :i"
                ),
                {"i": e},
            )
        changed["done"] = True

    rig.endpoint.category_id = world.fun
    rig.endpoint.during = during
    _process_head(rig)
    assert changed
    row = entry_row(rig.engine, e)
    assert row.category_id != world.fun and row.derivation["category"]["pass"] == "history"
