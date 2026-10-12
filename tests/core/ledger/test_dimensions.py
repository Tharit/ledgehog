"""Category and payee writes at the core: the stale-reference net, the deadlock retry, locking."""

from __future__ import annotations

import threading
import time
from typing import Any

import psycopg.errors
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.core.ledger import categories as cat_mod
from app.core.ledger.categories import create_category, delete_category, merge_category
from app.core.ledger.dimensions import MergeCountChanged
from app.core.ledger.payees import PayeeInUse, delete_payee
from app.core.settle.settle import SettleResult
from app.core.stale import StaleReference, stale_from_integrity
from tests.fixtures import ledger_seed as seed


@pytest.fixture(autouse=True)
def _no_settle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cat_mod, "settle", lambda engine: SettleResult())


@pytest.fixture
def acct(isolated_engine: Engine) -> int:
    with isolated_engine.begin() as conn:
        return seed.account(conn)


def caught(engine: Engine, sql: str, **params: Any) -> DBAPIError:
    with pytest.raises(DBAPIError) as info, engine.begin() as conn:
        conn.execute(text(sql), params)
    return info.value


def test_a_dangling_foreign_key_on_write_is_a_stale_reference_naming_the_field(
    isolated_engine: Engine, acct: int
):
    with isolated_engine.begin() as conn:
        source = seed.entry(conn, acct)
    update = "UPDATE ledger_entry SET {col} = 999 WHERE id = :e"
    for col, field, entity in (("category_id", "category_id", "category"), ("payee_id", "payee_id", "payee")):
        stale = stale_from_integrity(caught(isolated_engine, update.format(col=col), e=source))
        assert stale is not None
        assert (stale.field, stale.entity, stale.entity_id) == (field, entity, 999)
    stale = stale_from_integrity(
        caught(isolated_engine, "INSERT INTO category (name, kind, parent_id) VALUES ('x', 'expense', 999)")
    )
    assert stale is not None and (stale.field, stale.entity) == ("parent_id", "category")


def test_a_refused_delete_is_not_a_stale_reference(isolated_engine: Engine, acct: int):
    with isolated_engine.begin() as conn:
        c = seed.category(conn, "C")
        seed.entry(conn, acct, category_id=c)
    exc = caught(isolated_engine, "DELETE FROM category WHERE id = :c", c=c)
    assert isinstance(exc.orig, psycopg.errors.RestrictViolation)
    assert stale_from_integrity(exc) is None
    assert stale_from_integrity(caught(isolated_engine, "SELECT 1/0")) is None


def test_a_deadlock_victim_is_retried_once(isolated_engine: Engine, monkeypatch: pytest.MonkeyPatch):
    with isolated_engine.begin() as conn:
        a, b = seed.category(conn, "A"), seed.category(conn, "B")
    real = cat_mod.previewable
    calls: list[int] = []

    def flaky(engine: Engine, dry_run: bool, work: Any) -> Any:
        calls.append(1)
        if len(calls) == 1:
            raise psycopg.errors.DeadlockDetected("victim")
        return real(engine, dry_run, work)

    monkeypatch.setattr(cat_mod, "previewable", flaky)
    result = merge_category(isolated_engine, a, b, dry_run=False, expected_count=0)
    assert len(calls) == 2 and [p.source_id for p in result.pairs] == [a]


def test_a_merge_waits_for_a_writer_that_references_the_source_and_counts_its_entry(
    isolated_engine: Engine, acct: int
):
    with isolated_engine.begin() as conn:
        src, tgt = seed.category(conn, "S"), seed.category(conn, "T")
        entry = seed.entry(conn, acct)
    preview = merge_category(isolated_engine, src, tgt, dry_run=True, expected_count=None)
    assert preview.entry_count == 0
    writer = isolated_engine.connect()
    trans = writer.begin()
    writer.execute(text("UPDATE ledger_entry SET category_id = :c WHERE id = :e"), {"c": src, "e": entry})
    outcome: dict[str, Any] = {}

    def run() -> None:
        try:
            merge_category(isolated_engine, src, tgt, dry_run=False, expected_count=0)
        except Exception as exc:  # noqa: BLE001
            outcome["error"] = exc

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.5)
    assert thread.is_alive()  # the writer's share lock on the source row holds the merge back
    trans.commit()
    writer.close()
    thread.join(10)
    assert isinstance(outcome.get("error"), MergeCountChanged)  # it now repoints 1 entry, not 0
    with isolated_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM category")).scalar_one() == 2  # nothing was merged


def test_creating_under_a_parent_a_merge_is_removing_is_stale_not_a_server_error(isolated_engine: Engine):
    with isolated_engine.begin() as conn:
        src, tgt = seed.category(conn, "S"), seed.category(conn, "T")
    merge_category(isolated_engine, src, tgt, dry_run=False, expected_count=0)
    with pytest.raises(StaleReference) as info:
        create_category(isolated_engine, name="x", parent_id=src)
    assert info.value.field == "parent_id"


def test_deleting_through_the_core_backstops_a_restricted_row(isolated_engine: Engine, acct: int):
    with isolated_engine.begin() as conn:
        c = seed.category(conn, "C")
        p = seed.payee(conn, "P")
        seed.entry(conn, acct, payee_id=p)
    assert delete_category(isolated_engine, c, dry_run=False).deleted
    with pytest.raises(PayeeInUse):
        delete_payee(isolated_engine, p)
