"""Drafts laid over stored units: what a preview shows and a commit writes (spec §5.9, §6)."""

from __future__ import annotations

import pytest

from app.core.units.draft import DraftError
from tests.core.units.equality import preview_then_commit
from tests.core.units.scene import RERESOLVE, DraftEntry, Scene, fixed


def codes(plan) -> list[str]:  # noqa: ANN001
    return [p.code for p in plan.problems]


# ---- splits -------------------------------------------------------------------------------------


def test_a_split_creates_a_flow_and_the_original_absorbs_the_remainder(scene: Scene) -> None:
    food = scene.category("Food")
    _src, (e,) = scene.movement(-1000, counterparty="SHOP", description="weekly")
    tag = scene.tx(
        lambda c: c.execute(
            __import__("sqlalchemy").text("INSERT INTO tag (name) VALUES ('t') RETURNING id")
        ).scalar_one()
    )
    scene.tx(
        lambda c: c.execute(
            __import__("sqlalchemy").text("INSERT INTO ledger_entry_tag VALUES (:e, :t)"), {"e": e, "t": tag}
        )
    )
    scene.settle()
    draft = scene.draft(
        e,
        DraftEntry(e, category=fixed(food)),
        DraftEntry(-1, amount=-300, source_entry_id=e, category=fixed(scene.category("Fun"))),
    )
    plan, result = preview_then_commit(scene, draft)
    assert [s.residual_amount for s in plan.splits] == [-700]
    new = result.created[-1]
    rows = scene.rows(e, new)
    assert (rows[e].amount, rows[new].amount) == (-700, -300)
    assert rows[new].type == "flow" and rows[new].description == "weekly"
    assert scene.q("SELECT tag_id FROM ledger_entry_tag WHERE ledger_entry_id = :i", i=new)[0].tag_id == tag
    assert rows[e].version == 2 and rows[new].version == 1
    assert plan.row(-1).version is None
    assert {(c.entry_id, c.kind) for c in plan.consequences} >= {(-1, "created"), (e, "changed")}


def test_removing_a_split_entry_returns_its_amount_to_the_residual(scene: Scene) -> None:
    _src, (a, b) = scene.movement(-600, -400)
    scene.settle()
    plan, result = preview_then_commit(scene, scene.draft(a, removed_entry_ids=[b]))
    assert plan.splits[0].residual_amount == -1000
    assert result.removed_entry_ids == (b,)
    assert scene.rows(b) == {} and scene.row(a).amount == -1000
    assert {(c.entry_id, c.kind) for c in plan.consequences} == {(b, "deleted"), (a, "changed")}


def test_adjusting_an_allocation_moves_the_residual(scene: Scene) -> None:
    _src, (a, b) = scene.movement(-600, -400)
    scene.settle()
    plan, _ = preview_then_commit(scene, scene.draft(a, DraftEntry(b, amount=-100)))
    assert plan.splits[0].residual_amount == -900


@pytest.mark.parametrize(
    ("amount", "code"),
    [(-1000, "residual_zero"), (-1500, "residual_sign_flip"), (-1001, "residual_sign_flip")],
)
def test_the_residual_is_never_zero_and_never_flips_sign(scene: Scene, amount: int, code: str) -> None:
    _src, (e,) = scene.movement(-1000)
    plan = scene.preview(e, DraftEntry(-1, amount=amount, source_entry_id=e))
    assert codes(plan) == [code]
    assert plan.problems[0].entry_id == e


def test_the_original_cannot_be_removed(scene: Scene) -> None:
    _src, (a, b) = scene.movement(-600, -400)
    with pytest.raises(DraftError) as exc:
        scene.preview(a, removed_entry_ids=[a])
    assert exc.value.code == "anchor_removed"
    with pytest.raises(DraftError) as exc:
        scene.preview(b, removed_entry_ids=[a])
    assert exc.value.code == "original_removed"


# ---- conversion ---------------------------------------------------------------------------------


def test_a_flow_converted_to_a_transfer_drops_payee_and_category(scene: Scene) -> None:
    scene.sync(scene.savings)  # synced: no counter-leg is proposed, the leg waits (spec §5.7)
    pay, food = scene.payee("Shop"), scene.category("Food")
    _src, (e,) = scene.movement(-1000, type="flow", category_id=food, payee_id=pay)
    plan, _ = preview_then_commit(
        scene, scene.draft(e, DraftEntry(e, type=fixed("transfer"), counter_account=fixed(scene.savings)))
    )
    row = plan.row(e)
    assert row.fields["payee"].value is None and row.fields["category"].value is None
    assert row.fields["counter_account"].value == scene.savings
    stored = scene.row(e)
    assert stored.type == "transfer" and stored.category_id is None and stored.payee_id is None
    assert stored.counter_account_id == scene.savings
    assert set(stored.derivation) == {"type", "counter_account"}
    assert plan.anchor_unit.state.reasons == ("waiting_for_partner",)
    assert not plan.anchor_unit.state.confirmed


def test_a_second_transfer_in_a_source_is_refused(scene: Scene) -> None:
    _src, (a, b) = scene.movement(-600, -400, type="flow")
    plan = scene.preview(
        a,
        DraftEntry(a, type=fixed("transfer"), counter_account=fixed(scene.savings)),
        DraftEntry(b, type=fixed("transfer"), counter_account=fixed(scene.cash)),
    )
    assert "second_transfer" in codes(plan)


def test_a_new_entry_is_a_flow(scene: Scene) -> None:
    _src, (e,) = scene.movement(-1000)
    plan = scene.preview(
        e,
        DraftEntry(
            -1, amount=-100, source_entry_id=e, type=fixed("transfer"), counter_account=fixed(scene.cash)
        ),
    )
    assert "new_entry_not_flow" in codes(plan)


def test_the_currency_rule_binds_a_transfer_with_an_instructed_amount(scene: Scene) -> None:
    _src, (e,) = scene.movement(-1000, instructed=(-1100, "USD"))
    ok = scene.preview(e, DraftEntry(e, type=fixed("transfer"), counter_account=fixed(scene.usd)))
    assert ok.problems == ()
    bad = scene.preview(e, DraftEntry(e, type=fixed("transfer"), counter_account=fixed(scene.savings)))
    assert codes(bad) == ["currency_rule"]
    own = scene.preview(e, DraftEntry(e, type=fixed("transfer"), counter_account=fixed(scene.checking)))
    assert "own_counter_account" in codes(own)


# ---- pairs --------------------------------------------------------------------------------------


def test_converting_a_paired_leg_to_a_flow_leaves_its_partner_behind(scene: Scene) -> None:
    (_sa, (a,)), (_sb, (b,)) = scene.transfer_pair()
    scene.settle()
    food = scene.category("Food")
    before = scene.versions(a)
    plan, result = preview_then_commit(
        scene, scene.draft(a, DraftEntry(a, type=fixed("flow"), category=fixed(food)))
    )
    kinds = {(c.entry_id, c.kind) for c in plan.consequences}
    assert (a, "unpaired") in kinds and (b, "left_behind") in kinds and (b, "returns_to_review") in kinds
    partner = scene.row(b)
    assert partner.counterpart_entry_id is None and partner.type == "transfer"
    assert partner.counter_account_id is None  # the pair set it
    assert not plan.row(b).in_unit and plan.row(a).in_unit
    assert plan.versions == before and set(before) == {a, b}
    assert scene.row(b).version == before[b] + 1  # the partner is written: the link is structural
    assert [u.anchor_entry_id for u in result.units] == [a, b]


def test_redirecting_a_paired_leg_breaks_the_pair(scene: Scene) -> None:
    scene.sync(scene.cash)  # a synced counter-account: no counter-leg takes the place of the pair
    (_sa, (a,)), (_sb, (b,)) = scene.transfer_pair()
    plan, _ = preview_then_commit(scene, scene.draft(a, DraftEntry(a, counter_account=fixed(scene.cash))))
    assert (b, "left_behind") in {(c.entry_id, c.kind) for c in plan.consequences}
    assert scene.row(a).counter_account_id == scene.cash and scene.row(a).counterpart_entry_id is None


def test_splitting_a_paired_leg_shows_the_pair_invalid_and_the_commit_is_refused(scene: Scene) -> None:
    (_sa, (a,)), (_sb, (b,)) = scene.transfer_pair(-500)
    scene.sync(scene.savings)  # b's account is synced now: b no longer follows its partner (spec §5.7)
    plan = scene.preview(a, DraftEntry(-1, amount=-20, source_entry_id=a))
    assert codes(plan) == ["pair_unequal"]
    assert plan.problems[0].detail["difference"] == 20
    from app.core.units.commit import CommitRefused

    with pytest.raises(CommitRefused) as exc:
        scene.commit(a, DraftEntry(-1, amount=-20, source_entry_id=a))
    assert exc.value.problems[0].code == "pair_unequal"
    assert scene.row(a).amount == -500  # nothing written


def test_a_split_on_the_partner_side_makes_the_pair_equal_again(scene: Scene) -> None:
    (_sa, (a,)), (_sb, (b,)) = scene.transfer_pair(-500)
    plan, result = preview_then_commit(
        scene,
        scene.draft(
            a,
            DraftEntry(-1, amount=-20, source_entry_id=a),
            DraftEntry(-2, amount=20, source_entry_id=b),
        ),
    )
    assert plan.anchor_unit.entry_ids == (a, b, -1, -2)
    assert (scene.row(a).amount, scene.row(b).amount) == (-480, 480)


# ---- re-resolving -------------------------------------------------------------------------------


def test_reresolving_the_unit_takes_the_passes_view_again(scene: Scene) -> None:
    scene.confirmed("REWE", "Food")
    rent = scene.category("Rent")
    _src, (e,) = scene.movement(
        -700,
        counterparty="REWE",
        type="flow",
        category_id=rent,
        derivation='{"type": {"pass": "user"}, "category": {"pass": "user"}}',
    )
    scene.settle()
    kept = scene.preview(e)
    assert kept.row(e).fields["category"].value == rent  # decided, so kept
    afresh = scene.preview(e, reresolve_all=True)
    cat = afresh.row(e).fields["category"]
    assert cat.value == scene.cats["Food"] and cat.evidence.pass_name == "history"  # type: ignore[union-attr]
    one = scene.preview(e, DraftEntry(e, category=RERESOLVE))
    assert one.row(e).fields["category"].value == scene.cats["Food"]
    preview_then_commit(scene, scene.draft(e, reresolve_all=True))
    assert scene.row(e).category_id == scene.cats["Food"]


# ---- keys ---------------------------------------------------------------------------------------


def test_forged_bases_are_refused() -> None:
    from app.core.units.draft import ShownBasis

    for forged in ("rule", "own_account", "matcher_decision", "user"):
        with pytest.raises(DraftError) as exc:
            ShownBasis(forged, {})
        assert exc.value.code == "invalid_basis"


# ---- reviewed units -----------------------------------------------------------------------------


def test_opening_a_reviewed_unit_shows_it_as_stored_and_confirmed(scene: Scene) -> None:
    scene.confirmed("REWE", "Food")
    food = scene.category("Food")
    _src, (e,) = scene.movement(
        -700,
        counterparty="REWE",
        type="flow",
        category_id=food,
        derivation='{"type": {"pass": "user"}, "category": {"pass": "user"}}',
    )
    scene.settle()
    plan = scene.preview(e)
    assert plan.anchor_unit.state.confirmed and plan.consequences == ()
    cat = plan.row(e).fields["category"]
    assert cat.value == food and not cat.evidence.pass_name == "history"  # type: ignore[union-attr]
    # as stored, but for the empty payee, which a commit would decide as it is (spec §5.9)
    assert plan.row(e).derivation == {**scene.row(e).derivation, "payee": {"pass": "user"}}


def test_emptying_a_reviewed_entrys_category_returns_its_unit_to_review(scene: Scene) -> None:
    food = scene.category("Food")
    _src, (e,) = scene.movement(
        -700,
        type="flow",
        category_id=food,
        derivation='{"type": {"pass": "user"}, "category": {"pass": "user"}}',
    )
    scene.settle()
    plan, _ = preview_then_commit(scene, scene.draft(e, DraftEntry(e, category=fixed(None))))
    assert (e, "returns_to_review") in {(c.entry_id, c.kind) for c in plan.consequences}
    assert plan.anchor_unit.state.reasons == ("incomplete",)
    assert scene.row(e).review_flags == ["unclassified"]


def test_an_emptied_category_is_not_a_decision_the_passes_propose_it_again(scene: Scene) -> None:
    """Emptying type, category or counter-account is `reresolve`: history proposes Food again, and the
    commit accepts what the draft shows (as for an untouched proposal), so the unit is confirmed."""
    scene.confirmed("REWE", "Food")
    _src, (a, b) = scene.movement(-600, -400, counterparty="REWE")
    scene.settle()
    plan, _ = preview_then_commit(scene, scene.draft(a, DraftEntry(b, category=fixed(None))))
    food = scene.cats["Food"]
    assert plan.row(b).fields["category"].value == food
    assert scene.row(b).category_id == food
    assert scene.row(b).derivation["category"]["pass"] == "user"
    assert plan.anchor_unit.state.reasons == ()
