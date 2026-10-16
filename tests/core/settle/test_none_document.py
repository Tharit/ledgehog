"""Settling records "none" for the document of each transaction of a newly confirmed unit (spec §6, I20),
once, and is idempotent (I37)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, text

from app.core.importers.providers import reset_document_providers
from app.core.settle import settle
from tests.core.units.doc_helpers import make_doc_source, make_payee
from tests.core.units.helpers import D
from tests.invariants.helpers import make_category, make_entry, make_source

NONE = {"pass": "matcher_decision"}
STANDING = json.dumps({"category": {"pass": "user"}, "payee": {"pass": "user"}})


@pytest.fixture(autouse=True)
def _registry() -> Any:
    reset_document_providers()
    yield
    reset_document_providers()


def _row(engine: Engine, entry: int) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT derivation, version, document_id, review_flags FROM ledger_entry WHERE id = :i"),
            {"i": entry},
        ).one()


def _confirmed_unit(
    engine: Engine, make_account: Callable[..., int], *, split: bool = False, **src: Any
) -> tuple[int, int, int]:
    """A standing, complete unit (payee with a provider): (provider payee, first entry, second or 0)."""
    with engine.begin() as conn:
        acct = make_account(conn)
        cat = make_category(conn, "Food")
        payee = make_payee(conn, "PayPal", "paypal")
        source = make_source(conn, acct, amount=-200 if split else -100, booked_on=D, **src)
        kw = {"category_id": cat, "payee_id": payee, "derivation": STANDING}
        first = make_entry(conn, source, amount=-100, **kw)
        second = make_entry(conn, source, amount=-100, **kw) if split else 0
    return payee, first, second


def test_a_newly_confirmed_unit_records_none_on_its_original_entry_once(
    isolated_engine: Engine, make_account: Callable[..., int]
) -> None:
    _, first, second = _confirmed_unit(isolated_engine, make_account, split=True)
    before = _row(isolated_engine, first).version
    result = settle(isolated_engine)
    assert result.error is None
    assert _row(isolated_engine, first).derivation["document"] == NONE
    assert "document" not in _row(isolated_engine, second).derivation
    assert _row(isolated_engine, first).document_id is None
    assert _row(isolated_engine, first).version == before  # derivation bookkeeping: no bump
    assert first in result.touched_entry_ids


def test_a_second_settle_touches_nothing(isolated_engine: Engine, make_account: Callable[..., int]) -> None:
    _, first, _ = _confirmed_unit(isolated_engine, make_account)
    settle(isolated_engine)
    after = _row(isolated_engine, first)
    result = settle(isolated_engine)
    assert result.touched_entry_ids == () and result.error is None
    assert _row(isolated_engine, first) == after


def test_an_existing_document_decision_is_not_overwritten(
    isolated_engine: Engine, make_account: Callable[..., int]
) -> None:
    _, first, _ = _confirmed_unit(isolated_engine, make_account)
    with isolated_engine.begin() as conn:
        conn.execute(
            text("UPDATE ledger_entry SET derivation = derivation || CAST(:k AS jsonb) WHERE id = :i"),
            {"k": json.dumps({"document": {"pass": "user"}}), "i": first},
        )
    settle(isolated_engine)
    assert _row(isolated_engine, first).derivation["document"] == {"pass": "user"}


def test_a_unit_waiting_for_a_document_is_not_confirmed_and_records_nothing(
    isolated_engine: Engine, make_account: Callable[..., int]
) -> None:
    with isolated_engine.begin() as conn:
        make_doc_source(conn)  # never run
    _, first, _ = _confirmed_unit(isolated_engine, make_account)
    settle(isolated_engine)
    row = _row(isolated_engine, first)
    assert "document" not in row.derivation and list(row.review_flags) == ["waiting"]


def test_the_wait_ending_confirms_the_unit_and_records_none(
    isolated_engine: Engine, make_account: Callable[..., int]
) -> None:
    with isolated_engine.begin() as conn:
        instance = make_doc_source(conn)
    _, first, _ = _confirmed_unit(isolated_engine, make_account)
    settle(isolated_engine)
    with isolated_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO import_run (importer, importer_instance_id, emits, status, covered_through,"
                " finished_at) VALUES ('docs', :i, 'documents', 'ok', :d, now())"
            ),
            {"i": instance, "d": D + timedelta(days=30)},
        )
    settle(isolated_engine)
    row = _row(isolated_engine, first)
    assert row.derivation["document"] == NONE and list(row.review_flags) == []
    assert settle(isolated_engine).touched_entry_ids == ()


def test_a_source_added_later_cannot_reopen_the_confirmed_unit(
    isolated_engine: Engine, make_account: Callable[..., int]
) -> None:
    _, first, _ = _confirmed_unit(isolated_engine, make_account)
    settle(isolated_engine)
    with isolated_engine.begin() as conn:
        make_doc_source(conn)
    settle(isolated_engine)
    assert list(_row(isolated_engine, first).review_flags) == []
