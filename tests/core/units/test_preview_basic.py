from __future__ import annotations

from tests.core.units.scene import DraftEntry, Scene, fixed


def test_a_unit_with_a_history_proposal_previews_as_what_a_commit_leads_to(scene: Scene) -> None:
    scene.confirmed("REWE", "Food")
    _src, (e,) = scene.movement(-700, counterparty="REWE")
    scene.settle()
    stored = scene.row(e)
    assert stored.derivation["category"]["pass"] == "history"
    plan = scene.preview(e)
    row = plan.row(e)
    cat = row.fields["category"]
    assert (
        cat.value == scene.cats["Food"] and cat.evidence is not None and cat.evidence.pass_name == "history"
    )
    assert cat.stored_value == scene.cats["Food"]
    assert cat.key is not None and cat.key["pass"] == "user" and cat.key["basis"]["pass"] == "history"
    assert plan.anchor_unit.state.confirmed  # accepting the proposal is what the commit does
    assert plan.problems == () and plan.consequences == ()
    assert plan.versions == {e: stored.version}


def test_commit_accepts_the_proposal_and_settling_confirms(scene: Scene) -> None:
    scene.confirmed("REWE", "Food")
    _src, (e,) = scene.movement(-700, counterparty="REWE")
    scene.settle()
    result = scene.commit(e)
    row = scene.row(e)
    assert row.derivation["category"]["pass"] == "user"
    assert row.derivation["category"]["basis"]["pass"] == "history"
    assert row.review_flags == []
    assert result.units[0].state.confirmed
    assert [r.id for r in result.entries] == [e]


def test_a_changed_category_is_a_user_value_without_basis(scene: Scene) -> None:
    scene.confirmed("REWE", "Food")
    rent = scene.category("Rent")
    _src, (e,) = scene.movement(-700, counterparty="REWE")
    scene.settle()
    scene.commit(e, DraftEntry(e, category=fixed(rent)))
    row = scene.row(e)
    assert row.category_id == rent
    assert row.derivation["category"] == {"pass": "user"}
    assert row.version == 2
