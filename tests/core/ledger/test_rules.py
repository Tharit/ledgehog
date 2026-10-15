"""Rule writes at the core: validation, locking, counts, settling (spec §5.9, D198-D204)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, text

from app.core.ledger import rules as rules_mod
from app.core.ledger.dimensions import DuplicateName, ExpectedCountRequired
from app.core.ledger.rules import (
    InvalidRule,
    RuleCountChanged,
    RuleDraft,
    RuleMissing,
    create_rule,
    delete_rule,
    get_rule,
    list_rules,
    update_rule,
)
from app.core.resolution.registry import RuleToolsNotConfigured, unconfigure_rule_tools
from app.core.settle.settle import SettleResult
from app.core.stale import StaleReference
from tests.api.dimension_helpers import counts
from tests.fixtures import ledger_seed as seed
from tests.fixtures import rule_seed as rs


@pytest.fixture
def world(isolated_engine: Engine) -> dict[str, Any]:
    with isolated_engine.begin() as conn:
        return {
            "acct": seed.account(conn, "Giro"),
            "cash": seed.account(conn, "Cash"),
            "food": seed.category(conn, "Food"),
            "fun": seed.category(conn, "Fun"),
            "rewe": rs.payee(conn, "Rewe"),
        }


@pytest.fixture
def settles(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []

    def spy(engine: Engine) -> SettleResult:
        calls.append(1)
        return SettleResult()

    monkeypatch.setattr(rules_mod, "settle", spy)
    return calls


def snap(engine: Engine) -> dict[str, Any]:
    with engine.connect() as conn:
        return counts(conn)


def draft(world: dict[str, Any], **kw: Any) -> RuleDraft:
    base: dict[str, Any] = {
        "name": "Rewe",
        "sets": "category",
        "category_id": world["food"],
        "conditions": (rs.name_is("REWE"),),
    }
    base.update(kw)
    return RuleDraft(**base)


def make(engine: Engine, d: RuleDraft, **kw: Any) -> int:
    written = create_rule(engine, d, expected_count=kw.pop("expected_count", 0), **kw)
    assert written.rule is not None
    return written.rule.id


# ---- create, read, update, delete ------------------------------------------------------------


def test_create_update_delete_round_trip(isolated_engine: Engine, world: dict[str, Any], settles: list[int]):
    created = create_rule(isolated_engine, draft(world, name="  Rewe  ", priority=7), expected_count=0)
    assert created.rule is not None and not created.deleted
    rid = created.rule.id
    assert (created.rule.name, created.rule.sets, created.rule.category_id) == (
        "Rewe",
        "category",
        world["food"],
    )
    assert (created.rule.priority, created.rule.conditions, created.rule.payee_id) == (
        7,
        (rs.name_is("REWE"),),
        None,
    )
    assert created.settle is not None and created.settle.error is None
    with isolated_engine.connect() as conn:
        assert get_rule(conn, rid) == created.rule
        assert [r.id for r in list_rules(conn)] == [rid]
    updated = update_rule(
        isolated_engine,
        rid,
        draft(
            world,
            name="Rewe markt",
            category_id=world["fun"],
            conditions=(rs.name_starts("REWE"),),
        ),
        expected_count=0,
    )
    assert updated.rule is not None
    assert (updated.rule.name, updated.rule.category_id, updated.rule.conditions) == (
        "Rewe markt",
        world["fun"],
        (rs.name_starts("REWE"),),
    )
    deleted = delete_rule(isolated_engine, rid, expected_count=0)
    assert deleted.deleted and deleted.rule is not None and deleted.rule.id == rid
    with isolated_engine.connect() as conn:
        assert get_rule(conn, rid) is None
    assert len(settles) == 3


def test_list_is_in_evaluation_order(isolated_engine: Engine, world: dict[str, Any]):
    with isolated_engine.begin() as conn:
        c = rs.rule(conn, "c", "category", world["food"], conditions=(rs.name_is("a"),), priority=1)
        p2 = rs.rule(conn, "p2", "payee", world["rewe"], conditions=(rs.name_is("a"),), priority=20)
        p1 = rs.rule(conn, "p1", "payee", world["rewe"], conditions=(rs.name_is("a"),), priority=10)
        t = rs.rule(conn, "t", "counter_account", world["cash"], conditions=(rs.name_is("a"),), priority=99)
    with isolated_engine.connect() as conn:
        assert [r.id for r in list_rules(conn)] == [t, p1, p2, c]


def test_missing_rule_is_refused(isolated_engine: Engine, world: dict[str, Any], settles: list[int]):
    with pytest.raises(RuleMissing):
        update_rule(isolated_engine, 999, draft(world), expected_count=0)
    with pytest.raises(RuleMissing):
        delete_rule(isolated_engine, 999, expected_count=0)
    assert settles == []


def test_sets_is_fixed_at_creation(isolated_engine: Engine, world: dict[str, Any]):
    rid = make(isolated_engine, draft(world))
    with pytest.raises(InvalidRule) as info:
        update_rule(
            isolated_engine,
            rid,
            draft(world, sets="payee", category_id=None, payee_id=world["rewe"]),
            dry_run=True,
        )
    assert info.value.field == "sets"
    # the same value restated is tolerated, and `sets` may be left out
    update_rule(isolated_engine, rid, draft(world, sets="category"), expected_count=0)
    update_rule(isolated_engine, rid, draft(world, sets=None), expected_count=0)


def test_a_payee_and_a_counter_account_rule(isolated_engine: Engine, world: dict[str, Any]):
    a = make(isolated_engine, draft(world, name="p", sets="payee", category_id=None, payee_id=world["rewe"]))
    b = make(
        isolated_engine,
        draft(world, name="t", sets="counter_account", category_id=None, counter_account_id=world["cash"]),
    )
    with isolated_engine.connect() as conn:
        assert get_rule(conn, a).target_id == world["rewe"]  # type: ignore[union-attr]
        assert get_rule(conn, b).target_id == world["cash"]  # type: ignore[union-attr]


# ---- names -----------------------------------------------------------------------------------


def test_names_are_unique_case_insensitively_and_not_blank(isolated_engine: Engine, world: dict[str, Any]):
    rid = make(isolated_engine, draft(world, name="Rent"))
    with pytest.raises(DuplicateName):
        create_rule(isolated_engine, draft(world, name="rent"), dry_run=True)
    other = make(isolated_engine, draft(world, name="Other"))
    with pytest.raises(DuplicateName):
        update_rule(isolated_engine, other, draft(world, name=" RENT "), dry_run=True)
    update_rule(isolated_engine, rid, draft(world, name="RENT"), expected_count=0)  # its own name
    from app.core.ledger.dimensions import InvalidValue

    with pytest.raises(InvalidValue):
        create_rule(isolated_engine, draft(world, name="   "), dry_run=True)


# ---- validation ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kw", "field"),
    [
        ({"conditions": (rs.cond("purpose", "regex", "(SECRETPATTERN"),)}, "conditions[0].value"),
        ({"conditions": (rs.cond("purpose", "regex", "SECRETPATTERN" + "a" * 200),)}, "conditions[0].value"),
        (
            {"conditions": (rs.name_is("ok"), rs.cond("mandate_ref", "regex", "(SECRETPATTERN"))},
            "conditions[1].value",
        ),
        ({"conditions": ()}, "conditions"),
        ({"conditions": (rs.name_is("  "),)}, "conditions[0].value"),
        ({"conditions": (rs.name_is(""),)}, "conditions[0].value"),
        ({"conditions": (rs.cond("amount", "equals", "SECRETPATTERN"),)}, "conditions[0].field"),
        ({"conditions": (rs.cond("purpose", "matches", "SECRETPATTERN"),)}, "conditions[0].op"),
        (
            {"sets": "payee", "category_id": None, "payee_id": 1, "conditions": (rs.payee_is(1),)},
            "conditions[0].field",
        ),
        ({"conditions": (rs.cond("payee", "equals", "1"),)}, "conditions[0].op"),
        ({"conditions": (rs.name_is("x"), rs.cond("payee", "is", "SECRETPATTERN"))}, "conditions[1].value"),
        ({"conditions": (rs.payee_is(0),)}, "conditions[0].value"),
        ({"payee_id": 1}, "payee_id"),  # a category rule naming a payee as well
        ({"category_id": None}, "category_id"),  # no target at all
        ({"sets": "nothing"}, "sets"),
    ],
)
def test_a_rule_that_cannot_be_saved_is_refused_without_quoting_it(
    isolated_engine: Engine, world: dict[str, Any], settles: list[int], kw: dict[str, Any], field: str
):
    before = snap(isolated_engine)
    with pytest.raises(InvalidRule) as info:
        create_rule(isolated_engine, draft(world, **kw), expected_count=0)
    assert info.value.field == field
    assert "SECRETPATTERN" not in str(info.value)
    assert snap(isolated_engine) == before
    assert settles == []


# ---- stale references ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kw", "field", "entity"),
    [
        ({"category_id": 999_999}, "category_id", "category"),
        ({"sets": "payee", "category_id": None, "payee_id": 999_999}, "payee_id", "payee"),
        (
            {"sets": "counter_account", "category_id": None, "counter_account_id": 999_999},
            "counter_account_id",
            "account",
        ),
        ({"conditions": (rs.name_is("x"), rs.payee_is(999_999))}, "conditions[1].value", "payee"),
    ],
)
def test_a_missing_target_or_condition_is_a_stale_reference(
    isolated_engine: Engine, world: dict[str, Any], kw: dict[str, Any], field: str, entity: str
):
    with pytest.raises(StaleReference) as info:
        create_rule(isolated_engine, draft(world, **kw), dry_run=True)
    assert (info.value.field, info.value.entity, info.value.entity_id) == (field, entity, 999_999)
    rid = make(isolated_engine, draft(world))
    kw_update = {k: v for k, v in kw.items() if k != "sets"}
    if "sets" not in kw:
        with pytest.raises(StaleReference):
            update_rule(isolated_engine, rid, draft(world, **kw_update), dry_run=True)


# ---- dry run, expected_count, settling -------------------------------------------------------


def test_a_dry_run_writes_nothing_and_does_not_settle(
    isolated_engine: Engine, world: dict[str, Any], settles: list[int]
):
    with isolated_engine.begin() as conn:
        rs.new_entry(conn, world["acct"], counterparty_name="REWE")
        rid = rs.rule(conn, "old", "category", world["fun"], conditions=(rs.name_is("REWE"),))
    before = snap(isolated_engine)
    c = create_rule(isolated_engine, draft(world), dry_run=True)
    u = update_rule(isolated_engine, rid, draft(world, name="renamed"), dry_run=True)
    d = delete_rule(isolated_engine, rid, dry_run=True)
    assert c.rule is None and u.rule is not None and u.rule.name == "renamed"
    assert d.rule is not None and not d.deleted
    assert c.settle is None and u.settle is None and d.settle is None
    assert snap(isolated_engine) == before
    assert settles == []


def test_a_real_write_needs_the_count_its_dry_run_reported(
    isolated_engine: Engine, world: dict[str, Any], settles: list[int]
):
    with isolated_engine.begin() as conn:
        rs.new_entry(conn, world["acct"], counterparty_name="REWE")
        rs.new_entry(conn, world["acct"], counterparty_name="REWE")
        rid = rs.rule(conn, "old", "category", world["fun"], conditions=(rs.name_is("REWE"),))
    before = snap(isolated_engine)
    with pytest.raises(ExpectedCountRequired):
        create_rule(isolated_engine, draft(world))
    with pytest.raises(ExpectedCountRequired):
        update_rule(isolated_engine, rid, draft(world, name="x"))
    with pytest.raises(ExpectedCountRequired):
        delete_rule(isolated_engine, rid)
    for call in (
        lambda: create_rule(isolated_engine, draft(world), expected_count=1),
        lambda: update_rule(isolated_engine, rid, draft(world, name="x"), expected_count=3),
        lambda: delete_rule(isolated_engine, rid, expected_count=0),
    ):
        with pytest.raises(RuleCountChanged) as info:
            call()
        assert info.value.actual == 2
    assert snap(isolated_engine) == before  # nothing written
    assert settles == []
    dry = create_rule(isolated_engine, draft(world), dry_run=True)
    assert dry.preview.matches.total == 2
    create_rule(isolated_engine, draft(world), expected_count=dry.preview.matches.total)
    assert len(settles) == 1


# ---- the effect on entries -------------------------------------------------------------------


def _entry_state(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT id, version, type, payee_id, category_id, derivation FROM ledger_entry ORDER BY id")
        ).all()


def test_a_rule_write_changes_no_entry_and_bumps_no_version(
    isolated_engine: Engine, world: dict[str, Any], monkeypatch
):
    monkeypatch.setattr(rules_mod, "settle", lambda engine: SettleResult())
    with isolated_engine.begin() as conn:
        rs.new_entry(conn, world["acct"], counterparty_name="REWE")
        rs.confirmed_entry(conn, world["acct"], category=world["fun"], counterparty_name="REWE")
    before = _entry_state(isolated_engine)
    rid = make(isolated_engine, draft(world), expected_count=2)
    update_rule(isolated_engine, rid, draft(world, category_id=world["fun"]), expected_count=2)
    delete_rule(isolated_engine, rid, expected_count=2)
    assert _entry_state(isolated_engine) == before


def test_settling_applies_a_new_rule_to_unconfirmed_entries_only(
    isolated_engine: Engine, world: dict[str, Any]
):
    with isolated_engine.begin() as conn:
        fresh = rs.new_entry(conn, world["acct"], counterparty_name="REWE")
        done = rs.confirmed_entry(conn, world["acct"], category=world["fun"], counterparty_name="REWE")
    before = {r.id: r for r in _entry_state(isolated_engine)}
    written = create_rule(isolated_engine, draft(world), expected_count=2)
    assert written.settle is not None and written.settle.error is None
    assert written.rule is not None
    rid = written.rule.id
    after = {r.id: r for r in _entry_state(isolated_engine)}
    assert after[done] == before[done]  # I20
    assert (after[fresh].type, after[fresh].category_id) == ("flow", world["food"])
    assert after[fresh].derivation["category"] == rs.key(rid)
    with isolated_engine.connect() as conn:
        flags = conn.execute(
            text("SELECT review_flags FROM ledger_entry WHERE id = :i"), {"i": fresh}
        ).scalar_one()
    assert "unconfirmed" not in flags  # the rule's keys are standing: it arrives confirmed


def test_deleting_a_rule_leaves_its_keys_on_confirmed_entries(isolated_engine: Engine, world: dict[str, Any]):
    with isolated_engine.begin() as conn:
        rid = rs.rule(conn, "rewe", "category", world["food"], conditions=(rs.name_is("REWE"),))
        e = rs.confirmed_entry(
            conn,
            world["acct"],
            category=world["food"],
            keys={"type": rs.key(rid), "category": rs.key(rid)},
            counterparty_name="REWE",
        )
    before = _entry_state(isolated_engine)
    result = delete_rule(isolated_engine, rid, expected_count=1)
    assert result.preview.lost_key.total == 1 and result.preview.lost_key.rows[0].entry_id == e
    assert _entry_state(isolated_engine) == before


# ---- locking and plumbing --------------------------------------------------------------------


def test_a_deadlock_victim_is_retried_once(
    isolated_engine: Engine, world: dict[str, Any], settles: list[int], monkeypatch
):
    import psycopg.errors

    real = rules_mod.previewable
    calls: list[int] = []

    def flaky(engine: Engine, dry_run: bool, work: Any) -> Any:
        calls.append(1)
        if len(calls) == 1:
            raise psycopg.errors.DeadlockDetected("victim")
        return real(engine, dry_run, work)

    monkeypatch.setattr(rules_mod, "previewable", flaky)
    assert create_rule(isolated_engine, draft(world), expected_count=0).rule is not None
    assert len(calls) == 2


def test_the_rule_row_is_locked_for_update(
    isolated_engine: Engine, world: dict[str, Any], settles: list[int]
):
    import threading
    import time

    rid = make(isolated_engine, draft(world))
    holder_ready, release = threading.Event(), threading.Event()

    def hold() -> None:
        with isolated_engine.begin() as conn:
            conn.execute(text("SELECT id FROM rule WHERE id = :i FOR UPDATE"), {"i": rid})
            holder_ready.set()
            release.wait(5)

    t = threading.Thread(target=hold)
    t.start()
    holder_ready.wait(5)
    done: list[float] = []

    def write() -> None:
        started = time.monotonic()
        update_rule(isolated_engine, rid, draft(world, name="x"), expected_count=0)
        done.append(time.monotonic() - started)

    w = threading.Thread(target=write)
    w.start()
    time.sleep(0.5)
    assert not done  # waiting on the row lock
    release.set()
    t.join()
    w.join()
    assert done


def test_unconfigured_rule_tools_fail_loudly(isolated_engine: Engine, world: dict[str, Any]):
    unconfigure_rule_tools()
    with pytest.raises(RuleToolsNotConfigured):
        create_rule(isolated_engine, draft(world), dry_run=True)
    with pytest.raises(RuleToolsNotConfigured), isolated_engine.connect() as conn:
        list_rules(conn)


# ---- payee conditions (D215) -----------------------------------------------------------------


def test_payee_conditions_are_stored_in_the_list_and_ids_are_canonical_digits(
    isolated_engine: Engine, world: dict[str, Any]
):
    with isolated_engine.begin() as conn:
        other = rs.payee(conn, "Other")
    d = draft(world, conditions=(rs.payee_is(f"00{world['rewe']}"), rs.payee_is(other), rs.name_is("REWE")))
    written = create_rule(isolated_engine, d, expected_count=0)
    assert written.rule is not None
    assert written.rule.conditions == (
        rs.payee_is(world["rewe"]),
        rs.payee_is(other),
        rs.name_is("REWE"),
    )
    only = draft(world, name="only", conditions=(rs.payee_is(world["rewe"]),))
    assert make(isolated_engine, only) > 0  # a payee condition alone is a condition


def test_the_preview_of_a_rule_with_payee_conditions_judges_the_stored_payee(
    isolated_engine: Engine, world: dict[str, Any]
):
    with isolated_engine.begin() as conn:
        hit = rs.confirmed_entry(
            conn, world["acct"], category=world["fun"], payee=world["rewe"], counterparty_name="REWE"
        )
        rs.confirmed_entry(conn, world["acct"], category=world["fun"], counterparty_name="REWE")
    d = draft(world, conditions=(rs.payee_is(world["rewe"]), rs.name_is("REWE")))
    p = create_rule(isolated_engine, d, dry_run=True).preview
    assert [r.entry_id for r in p.matches.rows] == [hit]


def test_a_payee_condition_on_a_rule_that_does_not_set_a_category_is_refused(
    isolated_engine: Engine, world: dict[str, Any]
):
    for kw in (
        {"sets": "payee", "category_id": None, "payee_id": world["rewe"]},
        {"sets": "counter_account", "category_id": None, "counter_account_id": world["cash"]},
    ):
        with pytest.raises(InvalidRule) as info:
            create_rule(
                isolated_engine,
                draft(world, conditions=(rs.name_is("x"), rs.payee_is(world["rewe"])), **kw),
                dry_run=True,
            )
        assert info.value.field == "conditions[1].field"
