"""Pins what "no payee" stores and shows, whatever represents it inside: the user's decision (NULL with the
standing key `{"pass": "user"}`) and history's majority for none (NULL, no key, nothing asked after it); and
that only the payee may hold a standing empty."""

from __future__ import annotations

import json

import pytest

from app.api.routers.unit_drafts import UnitFieldOut
from app.core.resolution.types import Decided, Resolved
from tests.core.units.equality import preview_then_commit
from tests.core.units.scene import DraftEntry, Scene, fixed


def test_the_users_no_payee_stores_and_reads_as_a_standing_user_key(scene: Scene) -> None:
    rent = scene.category("Rent")
    der = json.dumps({"type": {"pass": "user"}, "payee": {"pass": "user"}, "category": {"pass": "user"}})
    _s, (e,) = scene.movement(-700, counterparty="RENT", type="flow", category_id=rent, derivation=der)
    plan = scene.preview(e)
    payee = UnitFieldOut.of(plan.row(e).fields["payee"], stored=True).model_dump(by_alias=True)
    assert payee == {
        "value": None,
        "key": {"pass": "user", "basis": {}},
        "is_proposal": False,
        "commit_key": {"pass": "user", "basis": {}},
        "stored": {"value": None, "key": {"pass": "user", "basis": {}}},
    }
    row = scene.row(e)
    assert row.payee_id is None and row.derivation["payee"] == {"pass": "user"}
    assert plan.anchor_unit.state.confirmed


def test_historys_majority_for_no_payee_stores_nothing_and_ends_the_search(scene: Scene) -> None:
    for _ in range(3):
        scene.confirmed("REWE", "Food")
    _s, (e,) = scene.movement(-700, counterparty="REWE")
    scene.settle()
    row = scene.row(e)
    assert row.payee_id is None and "payee" not in row.derivation
    assert row.category_id == scene.cats["Food"]
    plan = scene.preview(e)
    payee = UnitFieldOut.of(plan.row(e).fields["payee"], stored=True).model_dump(by_alias=True)
    # nothing is proposed or shown as decided; a commit would decide the empty payee the user saw (spec §5.9)
    assert payee["value"] is None and payee["key"] is None
    assert payee["commit_key"] == {"pass": "user", "basis": {}}
    scene.commit(e)
    assert scene.row(e).derivation["payee"] == {"pass": "user"}
    assert scene.row(e).category_id == scene.cats["Food"]


def test_only_a_field_that_may_be_empty_may_hold_a_decided_empty() -> None:
    standing = Decided(None, "user", {})
    assert Resolved({"payee": standing})["payee"] == standing
    for field in ("category", "counter_account", "type"):
        with pytest.raises(ValueError):
            Resolved({field: standing})  # type: ignore[misc]
    explained = Decided(None, "llm", {"none": True})
    assert Resolved({"category": explained})["category"] == explained


def test_a_category_draft_left_empty_withdraws_the_decision(scene: Scene) -> None:
    rent = scene.category("Rent")
    _s, (e,) = scene.movement(
        -700,
        type="flow",
        category_id=rent,
        derivation=json.dumps({"type": {"pass": "user"}, "category": {"pass": "user"}}),
    )
    preview_then_commit(scene, scene.draft(e, DraftEntry(e, category=fixed(None))))
    row = scene.row(e)
    assert row.category_id is None and "category" not in row.derivation
