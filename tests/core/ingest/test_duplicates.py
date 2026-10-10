"""Marking and clearing duplicates by hand (spec §5.6, architecture §5.2)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Engine, text

from app.core.domain.errors import (
    AlreadyDuplicate,
    DuplicateChain,
    DuplicateCrossAccount,
    DuplicateOfSelf,
    DuplicateRowMissing,
    NotADuplicate,
    UserAuthoredRow,
    VersionConflict,
)
from app.core.ingest import duplicates
from app.core.ingest.duplicates import clear_duplicate, mark_duplicate
from app.core.settle.settle import SettleResult
from app.utils.db.locks import WriteConflict, lock_accounts, lock_settle_exclusive
from tests.core.ingest.conftest import Env, row
from tests.core.ingest.dup_helpers import DAY, Ledger, pair_key
from tests.invariants.helpers import make_entry, make_source, pair

# ---- marking -------------------------------------------------------------------------------


def test_mark_removes_the_entry_and_the_commit_time_triggers_pass(ledger: Ledger) -> None:
    a_src, a = ledger.movement(amount=-500)
    c_src, c = ledger.movement(amount=-500)
    result = mark_duplicate(ledger.engine, a_src, c_src)
    assert ledger.dup_of(a_src) == c_src
    assert ledger.entries_of(a_src) == [] and ledger.entries_of(c_src) == [c]
    assert result.affected.removed_entry_ids == (a,)
    assert result.settle.error is None
    ledger.assert_checks_clean()


def test_rows_that_pointed_at_the_marked_row_now_point_at_the_new_original(ledger: Ledger) -> None:
    a_src, _ = ledger.movement()
    b_src, _ = ledger.movement()
    c_src, _ = ledger.movement()
    mark_duplicate(ledger.engine, b_src, a_src)
    assert ledger.dup_of(b_src) == a_src
    mark_duplicate(ledger.engine, a_src, c_src)
    assert ledger.dup_of(b_src) == c_src and ledger.dup_of(a_src) == c_src
    assert ledger.dup_of(c_src) is None
    ledger.assert_checks_clean()


def test_marking_a_row_with_split_tags_document_and_partner_runs_the_routine(ledger: Ledger) -> None:
    other_src, _ = ledger.movement(amount=-50)

    def build(c: Any) -> tuple[int, int, int, int, int, int]:
        src = make_source(c, ledger.checking, run_id=ledger.run, amount=-3000, booked_on=DAY)
        e1 = make_entry(
            c,
            src,
            amount=-1000,
            type="transfer",
            counter_account_id=ledger.savings,
            derivation=pair_key(),
        )
        e2 = make_entry(c, src, amount=-2000)
        b_src = make_source(c, ledger.savings, importer=None, amount=1000, booked_on=DAY)
        b = make_entry(
            c,
            b_src,
            type="transfer",
            counter_account_id=ledger.checking,
            derivation=pair_key("user"),
            description="in",
            note="keep b",
        )
        pair(c, e1, b)
        doc = c.execute(
            text(
                "INSERT INTO external_document (provider, external_id, occurred_on, total, currency, raw)"
                " VALUES ('shop', 'o1', DATE '2026-03-10', -2000, 'EUR', '{}') RETURNING id"
            )
        ).scalar_one()
        tag = c.execute(text("INSERT INTO tag (name) VALUES ('t') RETURNING id")).scalar_one()
        c.execute(text("UPDATE ledger_entry SET document_id = :d WHERE id = :e"), {"d": doc, "e": e2})
        c.execute(text("INSERT INTO ledger_entry_tag VALUES (:e, :t)"), {"e": e2, "t": tag})
        return src, e1, e2, b_src, b, doc

    src, e1, e2, _, b, doc = ledger.tx(build)
    result = mark_duplicate(ledger.engine, src, other_src)
    assert ledger.entries_of(src) == []
    partner = ledger.one("SELECT * FROM ledger_entry WHERE id = :i", i=b)
    assert partner.counterpart_entry_id is None and partner.counter_account_id is None
    assert (partner.type, partner.description, partner.note) == ("transfer", "in", "keep b")
    assert result.affected.removed_entry_ids == (e1, e2)
    assert result.affected.partner_entry_ids == (b,)
    assert result.affected.freed_document_ids == (doc,)
    assert ledger.q("SELECT * FROM ledger_entry_tag") == []
    assert ledger.one("SELECT ledger_entry_id FROM v_document_link WHERE document_id = :d", d=doc)[0] is None
    ledger.assert_checks_clean()


def _nothing_written(ledger: Ledger, before: list[Any]) -> None:
    assert ledger.q("SELECT id, duplicate_of FROM source_transaction ORDER BY id") == before


def _snapshot(ledger: Ledger) -> list[Any]:
    return ledger.q("SELECT id, duplicate_of FROM source_transaction ORDER BY id")


def test_marking_refuses_a_chain_in_either_form(ledger: Ledger) -> None:
    a_src, _ = ledger.movement()
    b_src, _ = ledger.movement()
    c_src, _ = ledger.movement()
    mark_duplicate(ledger.engine, b_src, a_src)
    before = _snapshot(ledger)
    with pytest.raises(DuplicateChain, match="itself a duplicate"):
        mark_duplicate(ledger.engine, c_src, b_src)
    with pytest.raises(AlreadyDuplicate, match="already a duplicate"):
        mark_duplicate(ledger.engine, b_src, c_src)
    _nothing_written(ledger, before)


def test_marking_refuses_another_account(ledger: Ledger) -> None:
    a_src, _ = ledger.movement()
    s_src, _ = ledger.movement(account=ledger.savings, run_id=None)
    before = _snapshot(ledger)
    with pytest.raises(DuplicateCrossAccount, match="same account"):
        mark_duplicate(ledger.engine, a_src, s_src)
    _nothing_written(ledger, before)


def test_marking_refuses_a_user_authored_row_in_both_directions(ledger: Ledger) -> None:
    a_src, _ = ledger.movement()
    u_src, _ = ledger.movement(importer=None)
    before = _snapshot(ledger)
    with pytest.raises(UserAuthoredRow, match="user-authored"):
        mark_duplicate(ledger.engine, u_src, a_src)
    with pytest.raises(UserAuthoredRow, match="user-authored"):
        mark_duplicate(ledger.engine, a_src, u_src)
    _nothing_written(ledger, before)


def test_marking_refuses_itself_and_missing_rows(ledger: Ledger) -> None:
    a_src, _ = ledger.movement()
    with pytest.raises(DuplicateOfSelf, match="itself"):
        mark_duplicate(ledger.engine, a_src, a_src)
    with pytest.raises(DuplicateRowMissing):
        mark_duplicate(ledger.engine, a_src, 99999)
    with pytest.raises(DuplicateRowMissing):
        mark_duplicate(ledger.engine, 99999, a_src)


def test_a_moved_entry_version_refuses_the_mark_and_writes_nothing(ledger: Ledger) -> None:
    a_src, a = ledger.movement()
    c_src, c = ledger.movement()
    version = ledger.one("SELECT version FROM ledger_entry WHERE id = :i", i=a).version
    before = _snapshot(ledger)
    with pytest.raises(VersionConflict) as caught:
        mark_duplicate(ledger.engine, a_src, c_src, expected_versions={a: version + 1, c: 1})
    assert caught.value.entry_ids == (a,)
    _nothing_written(ledger, before)
    assert ledger.entries_of(a_src) == [a]
    # the right versions go through
    mark_duplicate(ledger.engine, a_src, c_src, expected_versions={a: version})
    assert ledger.dup_of(a_src) == c_src


def _version(ledger: Ledger, entry: int) -> int:
    return int(ledger.one("SELECT version FROM ledger_entry WHERE id = :i", i=entry).version)


def _pair_to_mark(ledger: Ledger) -> tuple[int, int, int, int]:
    """(row to mark, its entry, the partner's entry, the row it duplicates)."""
    a_src, a, _, b = ledger.transfer_pair()
    c_src, _ = ledger.movement(amount=-500)
    return a_src, a, b, c_src


def test_a_moved_partner_version_refuses_the_mark_and_writes_nothing(ledger: Ledger) -> None:
    a_src, a, b, c_src = _pair_to_mark(ledger)
    seen = {a: _version(ledger, a), b: _version(ledger, b)}
    ledger.tx(lambda c: c.execute(text("UPDATE ledger_entry SET note = 'moved' WHERE id = :i"), {"i": b}))
    assert _version(ledger, b) != seen[b]
    before = _snapshot(ledger)
    with pytest.raises(VersionConflict) as caught:
        mark_duplicate(ledger.engine, a_src, c_src, expected_versions=seen)
    assert caught.value.entry_ids == (b,)
    _nothing_written(ledger, before)
    assert ledger.entries_of(a_src) == [a]
    partner = ledger.one("SELECT counterpart_entry_id, note FROM ledger_entry WHERE id = :i", i=b)
    assert partner.counterpart_entry_id == a and partner.note == "moved"


def test_a_partner_missing_from_the_supplied_versions_is_refused_by_name(ledger: Ledger) -> None:
    a_src, a, b, c_src = _pair_to_mark(ledger)
    before = _snapshot(ledger)
    with pytest.raises(VersionConflict) as caught:
        mark_duplicate(ledger.engine, a_src, c_src, expected_versions={a: _version(ledger, a)})
    assert caught.value.entry_ids == (b,)
    _nothing_written(ledger, before)
    assert ledger.entries_of(a_src) == [a]


def test_an_empty_version_map_names_every_entry_the_mark_would_write(ledger: Ledger) -> None:
    a_src, a, b, c_src = _pair_to_mark(ledger)
    with pytest.raises(VersionConflict) as caught:
        mark_duplicate(ledger.engine, a_src, c_src, expected_versions={})
    assert caught.value.entry_ids == (a, b)


def test_moved_and_unsupplied_entries_are_reported_together(ledger: Ledger) -> None:
    a_src, a, b, c_src = _pair_to_mark(ledger)
    with pytest.raises(VersionConflict) as caught:
        mark_duplicate(ledger.engine, a_src, c_src, expected_versions={a: _version(ledger, a) + 1})
    assert caught.value.entry_ids == (a, b)


def test_a_complete_correct_version_map_succeeds_with_the_partner(ledger: Ledger) -> None:
    a_src, a, b, c_src = _pair_to_mark(ledger)
    result = mark_duplicate(
        ledger.engine, a_src, c_src, expected_versions={a: _version(ledger, a), b: _version(ledger, b)}
    )
    assert ledger.dup_of(a_src) == c_src and result.affected.partner_entry_ids == (b,)
    ledger.assert_checks_clean()


def test_no_version_map_means_no_check(ledger: Ledger) -> None:
    a_src, _, b, c_src = _pair_to_mark(ledger)
    ledger.tx(lambda c: c.execute(text("UPDATE ledger_entry SET note = 'moved' WHERE id = :i"), {"i": b}))
    mark_duplicate(ledger.engine, a_src, c_src, expected_versions=None)
    assert ledger.dup_of(a_src) == c_src


def test_a_version_refused_mark_does_not_settle(ledger: Ledger, monkeypatch: pytest.MonkeyPatch) -> None:
    a_src, a, _, c_src = _pair_to_mark(ledger)
    calls: list[int] = []
    monkeypatch.setattr(duplicates, "settle", lambda e: calls.append(1) or SettleResult())
    with pytest.raises(VersionConflict):
        mark_duplicate(ledger.engine, a_src, c_src, expected_versions={a: _version(ledger, a)})
    assert calls == []


# ---- clearing ------------------------------------------------------------------------------


def test_clearing_restores_exactly_the_entry_ingest_creates(env: Env) -> None:
    env.deliver([row(-500, source_id="a")], importer="anna")
    env.deliver([row(-500, source_id="b")], importer="ben")  # pairs by amount: a duplicate
    first, second = (r.id for r in env.q("SELECT id FROM source_transaction ORDER BY id"))
    assert env.q("SELECT duplicate_of FROM source_transaction WHERE id = :i", i=second)[0][0] == first
    result = clear_duplicate(env.engine, second)
    cols = (
        "account_id, amount, currency, booked_on, value_on, type, category_id,"
        " counterpart_entry_id, derivation, document_id"
    )
    entries = env.q(
        f"SELECT source_transaction_id, {cols} FROM ledger_entry ORDER BY source_transaction_id"  # noqa: S608
    )
    assert len(entries) == 2
    assert tuple(entries[0][1:]) == tuple(entries[1][1:])
    assert env.q("SELECT duplicate_of FROM source_transaction WHERE id = :i", i=second)[0][0] is None
    assert (
        result.created_entry_id
        == env.q("SELECT id FROM ledger_entry WHERE source_transaction_id = :s", s=second)[0][0]
    )
    assert result.settle.error is None


def test_clearing_a_row_that_is_not_a_duplicate_is_refused(ledger: Ledger) -> None:
    a_src, a = ledger.movement()
    with pytest.raises(NotADuplicate, match="not a duplicate"):
        clear_duplicate(ledger.engine, a_src)
    assert ledger.entries_of(a_src) == [a]
    with pytest.raises(DuplicateRowMissing):
        clear_duplicate(ledger.engine, 99999)


def test_mark_then_clear_leaves_the_checks_clean(ledger: Ledger) -> None:
    a_src, _ = ledger.movement(amount=-500)
    c_src, _ = ledger.movement(amount=-500)
    mark_duplicate(ledger.engine, a_src, c_src)
    clear_duplicate(ledger.engine, a_src)
    assert len(ledger.entries_of(a_src)) == 1 and ledger.dup_of(a_src) is None
    ledger.assert_checks_clean()


# ---- settle after commit -------------------------------------------------------------------


def test_settle_runs_once_after_commit_and_a_failure_keeps_the_write(
    ledger: Ledger, monkeypatch: pytest.MonkeyPatch
) -> None:
    a_src, _ = ledger.movement()
    c_src, _ = ledger.movement()
    seen: list[Any] = []

    def spy(engine: Engine) -> SettleResult:
        seen.append(ledger.dup_of(a_src))  # a separate connection: committed state only
        raise RuntimeError("settle down")

    monkeypatch.setattr(duplicates, "settle", spy)
    result = mark_duplicate(ledger.engine, a_src, c_src)
    assert seen == [c_src]
    assert result.settle.error is not None and "settle down" in result.settle.error
    assert ledger.dup_of(a_src) == c_src and ledger.entries_of(a_src) == []

    seen.clear()
    clear_duplicate(ledger.engine, a_src)
    assert seen == [None]
    assert ledger.dup_of(a_src) is None and len(ledger.entries_of(a_src)) == 1


def test_a_refused_operation_does_not_settle(ledger: Ledger, monkeypatch: pytest.MonkeyPatch) -> None:
    a_src, _ = ledger.movement()
    calls: list[int] = []
    monkeypatch.setattr(duplicates, "settle", lambda e: calls.append(1) or SettleResult())
    with pytest.raises(DuplicateOfSelf):
        mark_duplicate(ledger.engine, a_src, a_src)
    assert calls == []


# ---- lock order ----------------------------------------------------------------------------

_SETTLE_CLASS = 1 << 24  # advisory key (1 << 56) as pg_locks shows it: high 32 bits
_ACCOUNT_CLASS = 2 << 24


def _waiters(ledger: Ledger) -> int:
    return int(ledger.one("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted")[0])


def _held_by_others(ledger: Ledger, holder_pid: int, klass: int, mode: str) -> int:
    return int(
        ledger.one(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND granted AND pid <> :p"
            " AND classid = :c AND mode = :m",
            p=holder_pid,
            c=klass,
            m=mode,
        )[0]
    )


def _until(cond: Callable[[], bool], what: str, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            pytest.fail(f"timed out waiting for {what}")
        time.sleep(0.02)


@pytest.mark.parametrize("op", ["mark", "clear"])
def test_lock_order_settle_shared_then_account(ledger: Ledger, op: str) -> None:
    a_src, _ = ledger.movement()
    c_src, _ = ledger.movement()
    if op == "clear":
        mark_duplicate(ledger.engine, a_src, c_src)
    act: Callable[[], Any] = (
        (lambda: mark_duplicate(ledger.engine, a_src, c_src))
        if op == "mark"
        else (lambda: clear_duplicate(ledger.engine, a_src))
    )
    done: list[Any] = []

    # 1. someone holds the ACCOUNT lock: the writer already holds settle shared and waits here
    with ledger.engine.connect() as holder:
        with holder.begin():
            pid = int(holder.execute(text("SELECT pg_backend_pid()")).scalar_one())
            lock_accounts(holder, [ledger.checking])
            thread = threading.Thread(target=lambda: done.append(act()))
            thread.start()
            _until(lambda: _waiters(ledger) >= 1, "the write to wait for the account lock")
            assert _held_by_others(ledger, pid, _SETTLE_CLASS, "ShareLock") == 1
    thread.join(timeout=15)
    assert not thread.is_alive() and len(done) == 1

    # 2. someone holds settle EXCLUSIVE: the writer waits for it before taking any account lock
    done.clear()
    if op == "mark":
        clear_duplicate(ledger.engine, a_src)
    else:
        mark_duplicate(ledger.engine, a_src, c_src)
    with ledger.engine.connect() as holder:
        with holder.begin():
            pid = int(holder.execute(text("SELECT pg_backend_pid()")).scalar_one())
            lock_settle_exclusive(holder)
            thread = threading.Thread(target=lambda: done.append(act()))
            thread.start()
            _until(lambda: _waiters(ledger) >= 1, "the write to wait for the settle lock")
            assert _held_by_others(ledger, pid, _ACCOUNT_CLASS, "ExclusiveLock") == 0
    thread.join(timeout=15)
    assert not thread.is_alive() and len(done) == 1


# ---- partner accounts ----------------------------------------------------------------------


def _blocked_until_released(ledger: Ledger, account: int, act: Callable[[], Any]) -> Any:
    """Run `act` while another connection holds `account`'s lock: it must wait, then finish."""
    done: list[Any] = []
    with ledger.engine.connect() as holder:
        with holder.begin():
            lock_accounts(holder, [account])
            thread = threading.Thread(target=lambda: done.append(act()))
            thread.start()
            _until(lambda: _waiters(ledger) >= 1 or bool(done), "the write to wait for the account lock")
            assert thread.is_alive() and not done, "the write did not wait for the partner's account lock"
    thread.join(timeout=15)
    assert not thread.is_alive() and len(done) == 1
    return done[0]


def test_mark_waits_for_the_lock_of_a_transfer_partners_account(ledger: Ledger) -> None:
    a_src, _, b_src_unused, c_src = _pair_to_mark(ledger)
    result = _blocked_until_released(
        ledger, ledger.savings, lambda: mark_duplicate(ledger.engine, a_src, c_src)
    )
    assert ledger.dup_of(a_src) == c_src and result.affected.partner_entry_ids == (b_src_unused,)
    ledger.assert_checks_clean()


def test_a_partner_account_found_only_under_the_locks_extends_the_lock_set_and_retries(
    ledger: Ledger, monkeypatch: pytest.MonkeyPatch
) -> None:
    a_src, _, _, c_src = _pair_to_mark(ledger)
    real = duplicates._accounts_of_entries
    calls: list[int] = []

    def stale_first(conn: Any, entry_ids: Any) -> set[int]:
        calls.append(1)
        return set() if len(calls) == 1 else real(conn, entry_ids)

    monkeypatch.setattr(duplicates, "_accounts_of_entries", stale_first)
    _blocked_until_released(ledger, ledger.savings, lambda: mark_duplicate(ledger.engine, a_src, c_src))
    assert ledger.dup_of(a_src) == c_src and len(calls) >= 3


def test_an_ever_moving_partner_set_ends_in_write_conflict_and_writes_nothing(
    ledger: Ledger, monkeypatch: pytest.MonkeyPatch
) -> None:
    a_src, _, _, c_src = _pair_to_mark(ledger)
    n = iter(range(100_000, 200_000))
    monkeypatch.setattr(duplicates, "_accounts_of_entries", lambda conn, ids: {next(n)})
    before = _snapshot(ledger)
    with pytest.raises(WriteConflict):
        mark_duplicate(ledger.engine, a_src, c_src)
    _nothing_written(ledger, before)
