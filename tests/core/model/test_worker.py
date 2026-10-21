"""The model's list and its worker (spec §5.9 pass 3, architecture §5.4): settling fills the list, one worker
asks, an answer is stored as the `llm` key and settles like any write, and gives way to the user."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from sqlalchemy import Engine, text

from app.core.model.queue import current_model_queue
from app.core.plugins.classifier import EntryInput
from app.core.settle import settle
from app.plugins.classifiers.llm.payload import fingerprint_of, payload_of
from app.utils.db.changes import install_change_hooks
from tests.core.model.rig import Rig, entry_row
from tests.core.settle.test_resolution_step import _new
from tests.invariants.helpers import make_category

MakeAccount = Callable[..., int]


@pytest.fixture
def acct(isolated_engine: Engine, make_account: MakeAccount) -> int:
    with isolated_engine.begin() as conn:
        return make_account(conn)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _toll(engine: Engine, acct: int, **cols: Any) -> tuple[int, int]:
    """An uninterpreted entry the model could place, and a category to place it in."""
    with engine.begin() as conn:
        cat = make_category(conn, "Tolls")
        e = _new(conn, acct, counterparty_name="AUCAT BAR CUBELLES", **cols)
    return e, cat


def _edit_payload(conn: Any, purpose: str) -> None:
    """Change what the model would read (a linked document does, in life; a source is immutable)."""
    conn.execute(text("ALTER TABLE source_transaction DISABLE TRIGGER USER"))
    conn.execute(text("UPDATE source_transaction SET purpose = :p"), {"p": purpose})
    conn.execute(text("ALTER TABLE source_transaction ENABLE TRIGGER USER"))


def _process_head(rig: Rig) -> None:
    item = rig.queue.head()
    assert item is not None
    asyncio.run(rig.worker.process(item))


# ---- settling fills the list -----------------------------------------------------------------------


def test_settling_lists_entries_whose_category_falls_to_the_model(rig: Rig, acct: int) -> None:
    e, _ = _toll(rig.engine, acct)
    with rig.engine.begin() as conn:
        _new(conn, acct, counterparty_ref="DE89370400440532013000")  # nothing the model may read
    assert settle(rig.engine).error is None
    assert rig.queue.pending() == 1 and rig.queue.entry_ids() == {e}
    assert rig.endpoint.requests == []  # settling never asks


def test_a_category_decided_by_a_rule_is_not_listed(rig: Rig, acct: int) -> None:
    from tests.fixtures import rule_seed as rs

    with rig.engine.begin() as conn:
        cat = make_category(conn, "Tolls")
        rs.rule(conn, "tolls", "category", cat, conditions=(rs.name_is("AUCAT"),))
        _new(conn, acct, counterparty_name="AUCAT")
    settle(rig.engine)
    assert rig.queue.pending() == 0


def test_without_a_model_nothing_is_listed(isolated_engine: Engine, acct: int) -> None:
    assert current_model_queue() is None
    _toll(isolated_engine, acct)
    assert settle(isolated_engine).error is None


# ---- storing the answer -----------------------------------------------------------------------------


def test_an_answer_is_stored_as_the_llm_key_and_settles_like_any_write(rig: Rig, acct: int) -> None:
    e, cat = _toll(rig.engine, acct)
    seen: list[frozenset[str]] = []
    install_change_hooks(rig.engine, seen.append)
    settle(rig.engine)
    seen.clear()
    rig.endpoint.category_id = cat

    _process_head(rig)

    row = entry_row(rig.engine, e)
    payload = payload_of(
        EntryInput(e, acct, "EUR", date(2026, 2, 10), 0, counterparty_name="AUCAT BAR CUBELLES")
    )
    assert payload is not None
    basis = {"model": "m-1", "rationale": "a short reason", "fingerprint": fingerprint_of(payload)}
    assert row.category_id == cat and row.type == "flow" and row.version == 1  # no version moves
    assert row.derivation["category"] == {"pass": "llm", "basis": basis}
    assert row.derivation["type"] == {"pass": "llm", "basis": basis}
    assert any("ledger" in keys for keys in seen)  # the ledger's change value moved
    assert rig.queue.pending() == 0
    assert settle(rig.engine).touched_entry_ids == ()  # it settles stable: the pass reuses the answer
    assert rig.queue.pending() == 0 and len(rig.endpoint.requests) == 1  # asked once per input


def test_without_a_model_a_stored_category_answer_stands(rig: Rig, acct: int) -> None:
    from app.core.model.queue import configure_model_queue

    e, cat = _toll(rig.engine, acct)
    settle(rig.engine)
    rig.endpoint.category_id = cat
    _process_head(rig)
    before = entry_row(rig.engine, e).derivation
    configure_model_queue(None)  # no model configured: the classifier is registered all the same
    assert settle(rig.engine).touched_entry_ids == ()
    row = entry_row(rig.engine, e)
    assert row.category_id == cat and row.derivation == before


def test_the_request_carries_the_payload_text_only(rig: Rig, acct: int) -> None:
    _toll(rig.engine, acct, counterparty_ref="DE89370400440532013000", mandate_ref="MANDATE-9")
    settle(rig.engine)
    _process_head(rig)
    body = rig.endpoint.requests[0].content.decode()
    assert "AUCAT BAR CUBELLES" in body
    assert "DE89370400440532013000" not in body and "MANDATE-9" not in body


def test_an_invalid_reply_stores_nothing_and_is_not_asked_again_until_a_restart(rig: Rig, acct: int) -> None:
    e, _ = _toll(rig.engine, acct)
    settle(rig.engine)
    rig.endpoint.category_id = 987654  # an id that is not listed
    _process_head(rig)
    row = entry_row(rig.engine, e)
    assert row.category_id is None and "category" not in row.derivation and rig.queue.pending() == 0
    settle(rig.engine)  # the same payload: not listed again (in memory only)
    assert rig.queue.pending() == 0 and len(rig.endpoint.requests) == 1


# ---- the user wins ---------------------------------------------------------------------------------


def _user_decides(engine: Engine, entry: int, category: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE ledger_entry SET category_id = :c, type = 'flow',"
                " derivation = CAST(:d AS jsonb) WHERE id = :i"
            ),
            {"c": category, "i": entry, "d": '{"type": {"pass": "user"}, "category": {"pass": "user"}}'},
        )


def test_an_answer_for_a_category_the_user_decided_meanwhile_is_dropped(rig: Rig, acct: int) -> None:
    e, cat = _toll(rig.engine, acct)
    with rig.engine.begin() as conn:
        mine = make_category(conn, "Mine")
    settle(rig.engine)
    rig.endpoint.category_id = cat
    rig.endpoint.during = lambda: _user_decides(rig.engine, e, mine)
    _process_head(rig)
    row = entry_row(rig.engine, e)
    assert row.category_id == mine and row.derivation["category"] == {"pass": "user"}
    assert rig.queue.pending() == 0


def test_a_category_decided_before_the_request_is_not_even_asked(rig: Rig, acct: int) -> None:
    e, cat = _toll(rig.engine, acct)
    settle(rig.engine)
    _user_decides(rig.engine, e, cat)
    _process_head(rig)
    assert rig.endpoint.requests == [] and rig.queue.pending() == 0


def test_an_answer_for_a_changed_payload_is_dropped_and_the_entry_listed_again(rig: Rig, acct: int) -> None:
    e, cat = _toll(rig.engine, acct)
    settle(rig.engine)
    rig.endpoint.category_id = cat

    def edit() -> None:
        with rig.engine.begin() as conn:
            _edit_payload(conn, "new text")

    rig.endpoint.during = edit
    _process_head(rig)
    assert entry_row(rig.engine, e).category_id is None
    rig.endpoint.during = None
    settle(rig.engine)
    assert rig.queue.pending() == 1  # the new payload is asked anew
    _process_head(rig)
    assert entry_row(rig.engine, e).category_id == cat


def test_a_stored_answer_goes_when_its_payload_changes(rig: Rig, acct: int) -> None:
    e, cat = _toll(rig.engine, acct)
    settle(rig.engine)
    rig.endpoint.category_id = cat
    _process_head(rig)
    assert entry_row(rig.engine, e).category_id == cat
    with rig.engine.begin() as conn:
        _edit_payload(conn, "something else")
    settle(rig.engine)
    assert entry_row(rig.engine, e).category_id is None  # the guess no longer stands
    assert rig.queue.pending() == 1


# ---- an unreachable model --------------------------------------------------------------------------


def test_an_unreachable_model_empties_the_list_logs_once_and_new_work_asks_again(
    rig: Rig, acct: int, caplog: pytest.LogCaptureFixture
) -> None:
    e, cat = _toll(rig.engine, acct)
    settle(rig.engine)
    rig.endpoint.status = 503
    with caplog.at_level(logging.WARNING, logger="ledgehog.model"):
        _process_head(rig)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "AUCAT" not in warnings[0].getMessage()
    assert rig.queue.pending() == 0 and rig.queue.unavailable

    settle(rig.engine)  # nothing new: the list stays empty
    assert rig.queue.pending() == 0 and rig.queue.unavailable

    with rig.engine.begin() as conn:  # settling hands it new work
        e2 = _new(conn, acct, counterparty_name="OTHER SHOP")
    settle(rig.engine)
    assert not rig.queue.unavailable and rig.queue.entry_ids() == {e, e2}


def test_the_worker_tries_again_after_its_delay(rig: Rig, acct: int) -> None:
    rig.worker.retry_after = 0.05
    e, cat = _toll(rig.engine, acct)
    settle(rig.engine)
    rig.endpoint.status = 503
    rig.endpoint.category_id = cat

    async def scenario() -> None:
        rig.worker.start()
        for _ in range(200):  # it fails and the list empties
            if rig.queue.unavailable:
                break
            await asyncio.sleep(0.01)
        assert rig.queue.unavailable and rig.queue.pending() == 0
        rig.endpoint.status = 200  # the model is back; the worker's retry settles and asks
        for _ in range(300):
            if entry_row(rig.engine, e).category_id == cat:
                break
            await asyncio.sleep(0.02)
        await rig.worker.stop()

    asyncio.run(scenario())
    assert entry_row(rig.engine, e).category_id == cat and not rig.queue.unavailable


def test_the_running_worker_works_through_the_list_in_order(rig: Rig, acct: int) -> None:
    with rig.engine.begin() as conn:
        cat = make_category(conn, "Shops")
        ids = [_new(conn, acct, counterparty_name=f"SHOP {n}") for n in range(3)]
    rig.endpoint.category_id = cat
    settle(rig.engine)
    assert rig.queue.pending() == 3

    async def scenario() -> None:
        rig.worker.start()
        for _ in range(300):
            if rig.queue.pending() == 0:
                break
            await asyncio.sleep(0.02)
        await rig.worker.stop()

    asyncio.run(scenario())
    assert all(entry_row(rig.engine, i).category_id == cat for i in ids)
    asked = [r.content.decode() for r in rig.endpoint.requests]
    assert [f"SHOP {n}" in a for n, a in enumerate(asked)] == [True] * 3
