"""The payee's three states: a payee; undecided (NULL, no key); no payee by the user's decision (NULL with the
standing key `{"pass": "user"}`), and an emptied type, category or counter-account that is no decision."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

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
