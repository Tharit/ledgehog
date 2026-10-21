"""The model's "no category fits" answer (spec §5.9 pass 3): kept as the `llm` key with `none` on an empty
category, settled around, not asked again for the same payload even after a restart."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import Engine, text

from app.core.model.queue import configure_model_queue
from app.core.settle import settle
from app.core.units.draft import DraftEntry
from tests.core.model.rig import Rig, entry_row, make_rig
from tests.core.model.test_worker import _edit_payload, _process_head, _toll, _user_decides
from tests.core.units.conftest import build_scene
from tests.core.units.scene import fixed
from tests.invariants.helpers import make_category

MakeAccount = Callable[..., int]
RATIONALE = "a Catalan motorway toll; there is no category for tolls"


@pytest.fixture
def acct(isolated_engine: Engine, make_account: MakeAccount) -> int:
    with isolated_engine.begin() as conn:
        return make_account(conn)


def _asked_none(rig: Rig, acct: int) -> int:
    e, _ = _toll(rig.engine, acct)
    settle(rig.engine)
    rig.endpoint.category_id = None
    rig.endpoint.rationale = RATIONALE
    _process_head(rig)
    return e


def _flags(engine: Engine, entry: int) -> list[str]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                text("SELECT review_flags FROM ledger_entry WHERE id = :i"), {"i": entry}
            ).scalar_one()
        )


def test_the_answer_is_stored_as_a_key_on_the_empty_category(rig: Rig, acct: int) -> None:
    e = _asked_none(rig, acct)
    row = entry_row(rig.engine, e)
    key = row.derivation["category"]
    assert row.category_id is None and row.type is None and row.version == 1
    assert key["pass"] == "llm"
    assert key["basis"]["none"] is True and key["basis"]["rationale"] == RATIONALE
    assert key["basis"]["model"] == "m-1" and len(key["basis"]["fingerprint"]) == 64
    assert "type" not in row.derivation
    assert rig.queue.pending() == 0


def test_settling_keeps_the_key_and_does_not_list_the_entry_again(rig: Rig, acct: int) -> None:
    e = _asked_none(rig, acct)
    before = entry_row(rig.engine, e).derivation
    assert settle(rig.engine).touched_entry_ids == ()  # a value-less key is not stale
    assert settle(rig.engine).touched_entry_ids == ()
    assert entry_row(rig.engine, e).derivation == before
    assert rig.queue.pending() == 0 and len(rig.endpoint.requests) == 1


def test_a_restart_does_not_ask_again(rig: Rig, isolated_engine: Engine, acct: int) -> None:
    e = _asked_none(rig, acct)
    restarted = make_rig(isolated_engine)  # a fresh queue and client: nothing in memory
    try:
        settle(isolated_engine)
        assert restarted.queue.pending() == 0 and restarted.endpoint.requests == []
        assert entry_row(isolated_engine, e).derivation["category"]["basis"]["none"] is True
    finally:
        configure_model_queue(rig.queue)


def test_a_changed_payload_drops_the_key_and_asks_anew(rig: Rig, acct: int) -> None:
    e = _asked_none(rig, acct)
    with rig.engine.begin() as conn:
        _edit_payload(conn, "something else")
    settle(rig.engine)
    assert "category" not in entry_row(rig.engine, e).derivation
    assert rig.queue.pending() == 1


def test_an_answer_for_a_changed_payload_is_dropped(rig: Rig, acct: int) -> None:
    e, _ = _toll(rig.engine, acct)
    settle(rig.engine)
    rig.endpoint.rationale = RATIONALE

    def edit() -> None:
        with rig.engine.begin() as conn:
            _edit_payload(conn, "new text")

    rig.endpoint.during = edit
    _process_head(rig)
    assert "category" not in entry_row(rig.engine, e).derivation


def test_an_answer_is_dropped_when_a_user_decided_meanwhile(rig: Rig, acct: int) -> None:
    e, cat = _toll(rig.engine, acct)
    settle(rig.engine)
    rig.endpoint.rationale = RATIONALE
    rig.endpoint.during = lambda: _user_decides(rig.engine, e, cat)
    _process_head(rig)
    row = entry_row(rig.engine, e)
    assert row.category_id == cat and row.derivation["category"] == {"pass": "user"}


def test_a_category_another_pass_decides_replaces_the_key(rig: Rig, acct: int) -> None:
    from tests.fixtures import rule_seed as rs

    e = _asked_none(rig, acct)
    with rig.engine.begin() as conn:
        cat = make_category(conn, "Roads")
        rs.rule(conn, "tolls", "category", cat, conditions=(rs.name_is("AUCAT BAR CUBELLES"),))
    settle(rig.engine)
    row = entry_row(rig.engine, e)
    assert row.category_id == cat and row.derivation["category"]["pass"] == "rule"


def test_the_entry_stays_unclassified_and_unconfirmed(rig: Rig, acct: int) -> None:
    e = _asked_none(rig, acct)
    assert _flags(rig.engine, e) == ["unclassified", "unconfirmed"]


def test_history_ignores_it(rig: Rig, acct: int) -> None:
    e = _asked_none(rig, acct)
    with rig.engine.begin() as conn:
        from tests.core.settle.test_resolution_step import _new

        other = _new(conn, acct, counterparty_name="AUCAT BAR CUBELLES")
    settle(rig.engine)
    assert entry_row(rig.engine, other).category_id is None  # no vote came from the unconfirmed entry
    assert entry_row(rig.engine, e).derivation["category"]["basis"]["none"] is True


def test_a_users_commit_of_a_category_replaces_the_key(
    rig: Rig, isolated_engine: Engine, make_account: MakeAccount
) -> None:
    scene = build_scene(isolated_engine, make_account)
    _s, (e,) = scene.movement(-700, counterparty="AUCAT BAR CUBELLES")
    cat = scene.category("Tolls")
    settle(isolated_engine)
    rig.endpoint.rationale = RATIONALE
    _process_head(rig)
    assert entry_row(isolated_engine, e).derivation["category"]["basis"]["none"] is True

    scene.commit(e, DraftEntry(e, category=fixed(cat)))
    row = entry_row(isolated_engine, e)
    assert row.category_id == cat and row.derivation["category"] == {"pass": "user"}


def test_a_commit_that_leaves_the_category_empty_keeps_the_key(
    rig: Rig, isolated_engine: Engine, make_account: MakeAccount
) -> None:
    scene = build_scene(isolated_engine, make_account)
    _s, (e,) = scene.movement(-700, counterparty="AUCAT BAR CUBELLES")
    scene.category("Food")  # the model is only asked with a tree to choose from
    settle(isolated_engine)
    rig.endpoint.rationale = RATIONALE
    _process_head(rig)
    key = entry_row(isolated_engine, e).derivation["category"]

    scene.commit(e, DraftEntry(e, note="checked"))
    assert entry_row(isolated_engine, e).derivation["category"] == key
    plan = scene.preview(e)
    category = next(r for r in plan.rows if r.id == e).fields["category"]
    assert category.value is None and category.key is not None and category.key["basis"]["none"] is True
