"""Committing a unit: keys, idempotence, conflicts, locks (spec §5.9, §6, architecture §4.1, §5.2)."""

from __future__ import annotations

import json
import threading
from typing import Any

import psycopg.errors
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.domain.errors import VersionConflict
from app.core.stale import StaleReference
from app.core.units import commit as commit_module
from app.core.units.commit import CommitRefused, UnitMoved
from app.core.units.draft import UnitDraft
from app.utils.db import locks
from tests import lockwatch
from tests.core.units.scene import DraftEntry, Scene, fixed

USER = json.dumps({"type": {"pass": "user"}, "category": {"pass": "user"}})


# ---- keys (spec §5.9, D212) ---------------------------------------------------------------------


def test_a_shown_basis_is_wrapped_under_user_for_a_value_the_client_accepted(scene: Scene) -> None:
    _s, (e,) = scene.movement(-700, counterparty="X")
    food = scene.category("Food")
    scene.commit(e, DraftEntry(e, category=fixed(food, ("history", {"matches": 4, "of": 4}))))
    key = scene.row(e).derivation["category"]
    assert key == {"pass": "user", "basis": {"pass": "history", "basis": {"matches": 4, "of": 4}}}


def test_a_user_key_left_unchanged_stays_and_one_never_wraps_another(scene: Scene) -> None:
    food = scene.category("Food")
    _s, (e,) = scene.movement(
        -700,
        type="flow",
        category_id=food,
        derivation=json.dumps(
            {
                "type": {"pass": "user"},
                "category": {"pass": "user", "basis": {"pass": "llm", "basis": {"x": 1}}},
            }
        ),
    )
    before = scene.row(e)
    scene.commit(e, DraftEntry(e, category=fixed(food, ("history", {}))))
    after = scene.row(e)
    assert after.derivation == before.derivation  # not wrapped again
    assert after.version == before.version


def test_a_standing_key_survives_a_commit_that_leaves_its_value_alone(scene: Scene) -> None:
    """I20: nothing changes a decided value on its own, and a commit leaves it as it was."""
    food = scene.category("Food")
    rule = {
        "type": {"pass": "rule", "basis": {"rule_id": 9}},
        "category": {"pass": "rule", "basis": {"rule_id": 9}},
    }
    _s, (e,) = scene.movement(-700, type="flow", category_id=food, derivation=json.dumps(rule))
    scene.settle()
    before = scene.row(e)
    scene.commit(e)
    scene.commit(e)
    after = scene.row(e)
    assert after.derivation == before.derivation and after.version == before.version
    assert after.review_flags == []


def test_a_changed_value_loses_the_standing_key_a_rule_gave_it(scene: Scene) -> None:
    food, fun = scene.category("Food"), scene.category("Fun")
    rule = {
        "type": {"pass": "rule", "basis": {"rule_id": 9}},
        "category": {"pass": "rule", "basis": {"rule_id": 9}},
    }
    _s, (e,) = scene.movement(-700, type="flow", category_id=food, derivation=json.dumps(rule))
    scene.commit(e, DraftEntry(e, category=fixed(fun)))
    assert scene.row(e).derivation["category"] == {"pass": "user"}
    assert scene.row(e).derivation["type"]["pass"] == "rule"  # its value did not change


def test_an_empty_field_carries_no_key(scene: Scene) -> None:
    food = scene.category("Food")
    _s, (e,) = scene.movement(-700, type="flow", category_id=food, derivation=USER)
    scene.commit(e, DraftEntry(e, category=fixed(None)))
    row = scene.row(e)
    assert row.category_id is None and "category" not in row.derivation


# ---- a commit does not confirm (D165) -----------------------------------------------------------


def test_a_transfer_without_a_partner_is_committed_whole_and_stays_in_review(scene: Scene) -> None:
    _s, (e,) = scene.movement(-1000, authored=True, description="withdrawal")
    result = scene.commit(
        e,
        DraftEntry(e, type=fixed("transfer"), counter_account=fixed(scene.cash), note=None),
    )
    row = scene.row(e)
    assert (row.type, row.counter_account_id, row.note) == ("transfer", scene.cash, None)
    assert row.derivation["counter_account"] == {"pass": "user"}
    assert result.units[0].state.reasons == ("unpaired_transfer",)  # kept, not confirmed
    assert scene.q("SELECT count(*) FROM ledger_entry WHERE counterpart_entry_id IS NOT NULL")[0][0] == 0


# ---- idempotence --------------------------------------------------------------------------------


def test_a_commit_that_changes_nothing_bumps_nothing_and_succeeds(scene: Scene) -> None:
    scene.confirmed("REWE", "Food")
    _s, (e,) = scene.movement(-700, counterparty="REWE")
    scene.settle()
    first = scene.commit(e)
    again = scene.commit(e)  # same versions: nothing moved
    assert scene.row(e).version == 1
    assert [r.version for r in again.entries] == [r.version for r in first.entries]


def test_a_replay_that_created_split_entries_conflicts(scene: Scene) -> None:
    _s, (e,) = scene.movement(-1000)
    draft = scene.draft(e, DraftEntry(-1, amount=-100, source_entry_id=e))
    scene.commit_draft(draft)
    with pytest.raises(VersionConflict) as exc:
        scene.commit_draft(draft)
    assert e in exc.value.entry_ids  # and the entry it created, which the replay carries no version for
    assert scene.q("SELECT count(*) FROM ledger_entry")[0][0] == 2


# ---- refusals -----------------------------------------------------------------------------------


def test_an_invalid_result_is_refused_by_code_and_writes_nothing(scene: Scene) -> None:
    _s, (e,) = scene.movement(-1000)
    before = scene.fingerprint()
    with pytest.raises(CommitRefused) as exc:
        scene.commit(e, DraftEntry(-1, amount=-1000, source_entry_id=e))
    assert [(p.code, p.entry_id) for p in exc.value.problems] == [("residual_zero", e)]
    assert scene.fingerprint() == before


def test_a_stale_partner_version_names_the_partner(scene: Scene) -> None:
    (_sa, (a,)), (_sb, (b,)) = scene.transfer_pair()
    versions = scene.versions(a)
    scene.tx(lambda c: c.execute(text("UPDATE ledger_entry SET note = 'moved' WHERE id = :i"), {"i": b}))
    with pytest.raises(VersionConflict) as exc:
        scene.commit_draft(UnitDraft(a, [DraftEntry(a, note="x")], versions=versions))
    assert exc.value.entry_ids == (b,)
    assert scene.row(a).note is None


def test_an_entry_the_commit_would_write_without_a_version_is_stale(scene: Scene) -> None:
    (_sa, (a,)), (_sb, (b,)) = scene.transfer_pair()
    versions = scene.versions(a)
    del versions[b]
    with pytest.raises(VersionConflict) as exc:
        scene.commit_draft(UnitDraft(a, [], versions=versions))
    assert exc.value.entry_ids == (b,)


def test_a_closure_that_changed_under_the_locks_is_unit_moved(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    (_sa, (a,)), (_sb, (b,)) = scene.transfer_pair()
    real = commit_module._read_closure
    calls: list[int] = []

    def stale(conn: Any, anchor: int) -> tuple[int, ...] | None:
        calls.append(1)
        found = real(conn, anchor)
        return (anchor,) if len(calls) == 1 and found else found  # the first read saw a unit of one

    monkeypatch.setattr(commit_module, "_read_closure", stale)
    with pytest.raises(UnitMoved):
        scene.commit(a, DraftEntry(a, note="x"))
    assert scene.row(a).note is None


def test_a_category_that_no_longer_exists_is_a_stale_reference(scene: Scene) -> None:
    _s, (e,) = scene.movement(-1000)
    with pytest.raises(StaleReference) as exc:
        scene.commit(e, DraftEntry(e, category=fixed(99_999)))
    assert (exc.value.field, exc.value.entity, exc.value.entity_id) == ("category_id", "category", 99_999)
    assert scene.row(e).category_id is None


def test_a_unique_index_race_is_a_named_conflict_not_a_server_error(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    (_sa, (a,)), (_sb, (b,)) = scene.transfer_pair()

    def taken(conn: Any, plan: Any) -> dict[int, int]:
        raise IntegrityError("INSERT", {}, psycopg.errors.UniqueViolation("duplicate key"))

    monkeypatch.setattr(commit_module, "_write", taken)
    with pytest.raises(VersionConflict) as exc:
        scene.commit(a, DraftEntry(a, note="x"))
    assert set(exc.value.entry_ids) == {a, b}


def test_an_aborted_deferred_trigger_is_a_refusal_with_the_constraint_not_a_crash(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    _s, (e,) = scene.movement(-1000)

    def broken(conn: Any, plan: Any) -> dict[int, int]:
        conn.execute(
            text("UPDATE ledger_entry SET amount = -5 WHERE id = :i"), {"i": e}
        )  # breaks I3 at COMMIT
        return {}

    monkeypatch.setattr(commit_module, "_write", broken)
    with pytest.raises(CommitRefused) as exc:
        scene.commit(e)
    assert exc.value.problems[0].code == "invariant_violated"
    assert scene.row(e).amount == -1000


def test_a_deadlock_is_retried_once_then_named(scene: Scene, monkeypatch: pytest.MonkeyPatch) -> None:
    _s, (e,) = scene.movement(-1000)
    real = commit_module._commit_once
    attempts: list[int] = []

    def flaky(engine: Any, draft: Any) -> Any:
        attempts.append(1)
        if len(attempts) == 1:
            raise psycopg.errors.DeadlockDetected("deadlock detected")
        return real(engine, draft)

    monkeypatch.setattr(commit_module, "_commit_once", flaky)
    scene.commit(e, DraftEntry(e, note="kept"))
    assert len(attempts) == 2 and scene.row(e).note == "kept"

    def always(engine: Any, draft: Any) -> Any:
        raise psycopg.errors.DeadlockDetected("deadlock detected")

    monkeypatch.setattr(commit_module, "_commit_once", always)
    with pytest.raises(locks.WriteConflict):
        scene.commit(e, DraftEntry(e, note="lost"))
    assert scene.row(e).note == "kept"


# ---- concurrency --------------------------------------------------------------------------------


def test_a_commit_waits_for_the_account_locks_of_every_account_of_the_unit(scene: Scene) -> None:
    (_sa, (a,)), (_sb, (b,)) = scene.transfer_pair()
    draft = UnitDraft(a, [DraftEntry(a, note="x")], versions=scene.versions(a))
    done = threading.Event()
    errors: list[BaseException] = []

    def run() -> None:
        try:
            scene.commit_draft(draft)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            done.set()

    with scene.engine.connect() as holder:
        locks.lock_accounts(holder, [scene.savings])  # the PARTNER's account: the unit spans two
        t = threading.Thread(target=run)
        t.start()
        lockwatch.wait_until_waiting(scene.engine, "the commit to wait for the savings account")
        assert not done.is_set()
        holder.rollback()
    t.join(10)
    assert done.is_set() and not errors
    assert scene.row(a).note == "x"


def test_a_commit_waits_for_a_settle_and_not_for_other_commits(scene: Scene) -> None:
    _s, (e,) = scene.movement(-1000)
    done = threading.Event()
    draft = UnitDraft(e, [DraftEntry(e, note="x")], versions=scene.versions(e))

    def run() -> None:
        scene.commit_draft(draft)
        done.set()

    with scene.engine.connect() as settler:
        locks.lock_settle_exclusive(settler)
        t = threading.Thread(target=run)
        t.start()
        lockwatch.wait_until_waiting(scene.engine, "the commit to wait for the settle")
        assert not done.is_set()
        settler.rollback()
    t.join(10)
    assert done.is_set()


def test_two_commits_of_one_unit_serialise_and_the_second_sees_the_first(scene: Scene) -> None:
    _s, (e,) = scene.movement(-1000)
    versions = scene.versions(e)
    outcomes: dict[str, Any] = {}

    def run(name: str, note: str) -> None:
        try:
            scene.commit_draft(UnitDraft(e, [DraftEntry(e, note=note, description=note)], versions=versions))
            outcomes[name] = "ok"
        except VersionConflict as exc:
            outcomes[name] = exc

    threads = [threading.Thread(target=run, args=(n, n)) for n in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)
    winners = [n for n, o in outcomes.items() if o == "ok"]
    assert len(winners) == 1 and len(outcomes) == 2
    loser = next(o for o in outcomes.values() if o != "ok")
    assert loser.entry_ids == (e,)
    assert scene.row(e).note == winners[0]
