"""Empty is a value (spec §5.9, D228): a payee decided empty (NULL with the standing key `{"pass": "user"}`),
cleared or left so by a commit, against an undecided one (NULL, no key); an emptied type, category or
counter-account is no decision."""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import text

from app.core.plugins.classifier import EMPTY
from app.core.resolution import Decided, Resolved, resolve
from tests.core.resolution.helpers import Script, account, entry
from tests.core.units.equality import preview_then_commit
from tests.core.units.scene import RERESOLVE, DraftEntry, Scene, fixed

USER = json.dumps({"type": {"pass": "user"}})
NAME = [{"field": "counterparty_name", "op": "equals", "value": "RENT"}]


def _rule(scene: Scene, sets: str, target: int) -> None:
    col = {"payee": "payee_id", "category": "category_id", "counter_account": "counter_account_id"}[sets]

    def go(conn: Any) -> None:
        conn.execute(
            text(
                f"INSERT INTO rule (name, sets, {col}, conditions) VALUES (:n, :s, :t, CAST(:k AS jsonb))"  # noqa: S608
            ),
            {"n": f"r-{sets}", "s": sets, "t": target, "k": json.dumps(NAME)},
        )

    scene.tx(go)


def test_a_payee_fixed_none_is_the_users_decision_in_preview_and_after_commit(scene: Scene) -> None:
    landlord = scene.payee("Landlord")
    _rule(scene, "payee", landlord)
    _s, (e,) = scene.movement(-700, counterparty="RENT")
    plan, _ = preview_then_commit(scene, scene.draft(e, DraftEntry(e, type=fixed("flow"), payee=fixed(None))))
    f = plan.row(e).fields["payee"]
    assert f.value is None
    assert f.key == {"pass": "user"} and f.evidence is not None and f.evidence.pass_name == "user"
    row = scene.row(e)
    assert row.payee_id is None and row.derivation["payee"] == {"pass": "user"}
    assert plan.row(e).written.derivation["payee"] == {"pass": "user"}


def test_a_payee_rule_does_not_override_the_decision_and_the_unit_stays_confirmed(scene: Scene) -> None:
    landlord, rent = scene.payee("Landlord"), scene.category("Rent")
    _rule(scene, "category", rent)
    _s, (e,) = scene.movement(-700, counterparty="RENT")
    scene.settle()
    plan, _ = preview_then_commit(scene, scene.draft(e, DraftEntry(e, type=fixed("flow"), payee=fixed(None))))
    assert plan.anchor_unit.state.confirmed
    assert scene.row(e).category_id == rent
    _rule(scene, "payee", landlord)  # a payee rule appears later: settle leaves the decision alone
    assert scene.settle().touched_entry_ids == ()
    row = scene.row(e)
    assert row.payee_id is None and row.derivation["payee"] == {"pass": "user"}
    assert row.review_flags == []


def test_the_decision_survives_a_later_commit_that_keeps_the_payee(scene: Scene) -> None:
    landlord, rent = scene.payee("Landlord"), scene.category("Rent")
    _rule(scene, "payee", landlord)
    _s, (e,) = scene.movement(
        -700,
        counterparty="RENT",
        type="flow",
        category_id=rent,
        derivation=json.dumps(
            {"type": {"pass": "user"}, "payee": {"pass": "user"}, "category": {"pass": "user"}}
        ),
    )
    preview_then_commit(scene, scene.draft(e, DraftEntry(e, note="x")))
    row = scene.row(e)
    assert row.payee_id is None and row.derivation["payee"] == {"pass": "user"}


def test_choosing_a_payee_or_resolving_again_replaces_the_decision(scene: Scene) -> None:
    landlord = scene.payee("Landlord")
    _rule(scene, "payee", landlord)
    rent = scene.category("Rent")
    der = json.dumps({"type": {"pass": "user"}, "payee": {"pass": "user"}, "category": {"pass": "user"}})
    _s, (e,) = scene.movement(-700, counterparty="RENT", type="flow", category_id=rent, derivation=der)
    other = scene.payee("Other")
    preview_then_commit(scene, scene.draft(e, DraftEntry(e, payee=fixed(other))))
    assert scene.row(e).payee_id == other and scene.row(e).derivation["payee"] == {"pass": "user"}
    scene.tx(lambda c: c.execute(text("UPDATE ledger_entry SET payee_id = NULL WHERE id = :i"), {"i": e}))
    preview_then_commit(scene, scene.draft(e, DraftEntry(e, payee=RERESOLVE)))
    assert scene.row(e).payee_id == landlord


def test_converting_to_a_transfer_drops_the_payee_decision(scene: Scene) -> None:
    rent = scene.category("Rent")
    der = json.dumps({"type": {"pass": "user"}, "payee": {"pass": "user"}, "category": {"pass": "user"}})
    _s, (e,) = scene.movement(-700, type="flow", category_id=rent, derivation=der)
    plan, _ = preview_then_commit(
        scene, scene.draft(e, DraftEntry(e, type=fixed("transfer"), counter_account=fixed(scene.cash)))
    )
    row = scene.row(e)
    assert row.type == "transfer" and row.payee_id is None
    assert "payee" not in row.derivation and "category" not in row.derivation
    assert plan.row(e).fields["payee"].key is None


def test_emptied_category_is_reresolved_not_a_decision(scene: Scene) -> None:
    rent = scene.category("Rent")
    _rule(scene, "category", rent)
    fun = scene.category("Fun")
    _s, (e,) = scene.movement(
        -700,
        counterparty="RENT",
        type="flow",
        category_id=fun,
        derivation=json.dumps({"type": {"pass": "user"}, "category": {"pass": "user"}}),
    )
    plan = scene.preview(e, DraftEntry(e, category=fixed(None)))
    assert plan.row(e).fields["category"].value == rent
    preview_then_commit(scene, scene.draft(e, DraftEntry(e, category=fixed(None))))
    assert scene.row(e).category_id == rent


def test_an_emptied_counter_account_is_reresolved(scene: Scene) -> None:
    _rule(scene, "counter_account", scene.cash)
    _s, (e,) = scene.movement(-700, counterparty="RENT", authored=True)
    preview_then_commit(
        scene, scene.draft(e, DraftEntry(e, type=fixed("transfer"), counter_account=fixed(scene.savings)))
    )
    assert scene.row(e).counter_account_id == scene.savings
    preview_then_commit(scene, scene.draft(e, DraftEntry(e, counter_account=fixed(None))))
    assert scene.row(e).counter_account_id == scene.cash


def test_a_payee_none_alone_on_an_untyped_entry_implies_a_flow(scene: Scene) -> None:
    _s, (e,) = scene.movement(-700, counterparty="NOBODY")
    assert scene.row(e).type is None
    plan, _ = preview_then_commit(scene, scene.draft(e, DraftEntry(e, payee=fixed(None))))
    row = plan.row(e)
    assert row.fields["type"].value == "flow" and row.fields["type"].key == {"pass": "user"}
    assert row.fields["payee"].value is None and row.fields["payee"].key == {"pass": "user"}
    assert row.fields["payee"].evidence is not None and row.fields["payee"].evidence.pass_name == "user"
    stored = scene.row(e)
    assert stored.type == "flow" and stored.payee_id is None
    assert stored.derivation["type"] == {"pass": "user"} and stored.derivation["payee"] == {"pass": "user"}
    assert scene.settle().touched_entry_ids == ()


def test_a_payee_none_with_a_drafted_transfer_is_dropped_without_error(scene: Scene) -> None:
    _s, (e,) = scene.movement(-700, counterparty="NOBODY", authored=True)
    plan, _ = preview_then_commit(
        scene,
        scene.draft(
            e,
            DraftEntry(e, type=fixed("transfer"), payee=fixed(None), counter_account=fixed(scene.savings)),
        ),
    )
    stored = scene.row(e)
    assert stored.type == "transfer" and stored.payee_id is None
    assert "payee" not in stored.derivation
    assert plan.row(e).fields["payee"].key is None


# ---- empty is a value: cleared or left empty, a commit decides it (spec §5.9, §6) ---------------------


def _history_of_payee(scene: Scene, payee: int, category: int, *, times: int = 2) -> None:
    der = json.dumps({"type": {"pass": "user"}, "payee": {"pass": "user"}, "category": {"pass": "user"}})
    for _ in range(times):
        scene.movement(
            -500, counterparty="RENT", type="flow", payee_id=payee, category_id=category, derivation=der
        )


def test_auto_confirm_is_unchanged_history_majority_for_no_payee_stores_no_key(scene: Scene) -> None:
    rent = scene.category("Rent")
    _rule(scene, "category", rent)
    for _ in range(3):
        scene.movement(
            -500,
            counterparty="RENT",
            type="flow",
            category_id=rent,
            derivation=json.dumps({"type": {"pass": "user"}, "category": {"pass": "user"}}),
        )
    _s, (e,) = scene.movement(-700, counterparty="RENT")
    scene.settle()
    row = scene.row(e)
    assert row.payee_id is None and "payee" not in row.derivation
    assert row.category_id == rent and row.derivation["category"]["pass"] == "rule"
    assert row.review_flags == []  # the empty result stores nothing, so nothing is left to review


def test_clearing_a_proposed_payee_then_committing_decides_it_empty(scene: Scene) -> None:
    landlord, rent = scene.payee("Landlord"), scene.category("Rent")
    _history_of_payee(scene, landlord, rent)
    _s, (e,) = scene.movement(-700, counterparty="RENT")
    scene.settle()
    row = scene.row(e)
    assert row.payee_id == landlord and row.derivation["payee"]["pass"] == "history"
    plan, _ = preview_then_commit(
        scene, scene.draft(e, DraftEntry(e, payee=fixed(None), category=fixed(rent, ("history", {}))))
    )
    payee = plan.row(e).fields["payee"]
    assert payee.value is None and payee.key == {"pass": "user"}  # nothing proposes over it
    assert payee.stored_value == landlord  # what "Reset to proposal" shows again
    row = scene.row(e)
    assert row.payee_id is None and row.derivation["payee"] == {"pass": "user"}
    assert plan.anchor_unit.state.confirmed and row.review_flags == []


def test_a_decided_empty_payee_on_an_incomplete_unit_is_kept_by_settling(scene: Scene) -> None:
    landlord = scene.payee("Landlord")
    _s, (e,) = scene.movement(-700, counterparty="RENT")
    scene.commit(e, DraftEntry(e, type=fixed("flow"), payee=fixed(None)))
    scene.settle()
    row = scene.row(e)
    assert row.payee_id is None and row.derivation["payee"] == {"pass": "user"}
    assert row.category_id is None and row.review_flags != []  # incomplete: in review, the payee stays
    _rule(scene, "payee", landlord)
    assert scene.settle().touched_entry_ids == ()
    assert scene.row(e).derivation["payee"] == {"pass": "user"}


def test_an_empty_payee_left_as_it_is_is_decided_empty_by_the_commit(scene: Scene) -> None:
    rent = scene.category("Rent")
    _s, (e,) = scene.movement(-700, counterparty="NOBODY")
    assert scene.row(e).payee_id is None and "payee" not in scene.row(e).derivation
    plan, _ = preview_then_commit(
        scene, scene.draft(e, DraftEntry(e, type=fixed("flow"), category=fixed(rent)))
    )
    assert plan.row(e).fields["payee"].value is None
    row = scene.row(e)
    assert row.payee_id is None and row.derivation["payee"] == {"pass": "user"}
    assert plan.anchor_unit.state.confirmed
    # an empty category is not: it carries no key, and an entry without a type has no payee to decide
    _s, (u,) = scene.movement(-300, counterparty="UNKNOWN")
    scene.commit(u, DraftEntry(u, note="x"))
    assert "payee" not in scene.row(u).derivation


def test_a_decided_empty_is_refused_on_a_field_that_may_not_be_empty() -> None:
    for field in ("type", "category", "counter_account"):
        with pytest.raises(ValueError):
            Resolved({field: Decided(None, "user", {})})  # type: ignore[misc]
    assert Resolved({"payee": Decided(None, "user", {})})


def test_an_empty_result_is_valid_only_where_a_field_may_be_empty() -> None:
    assert "category" not in resolve(
        entry(), accounts=[account(1)], classifiers=[Script("history", {"type": "flow", "payee": EMPTY})]
    )
    with pytest.raises(ValueError):
        resolve(
            entry(),
            accounts=[account(1)],
            classifiers=[Script("history", {"type": "flow", "category": EMPTY})],
        )
