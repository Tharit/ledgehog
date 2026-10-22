"""The key a commit writes for a value depends on the FINAL decision alone (spec §5.9, D212)."""

from __future__ import annotations

import json

from app.core.resolution import Decided
from app.core.units.overlay import _commit_key
from tests.core.units.scene import Scene

BASIS = {"rule_id": 3}


def test_a_standing_pass_keeps_its_own_key_with_its_basis() -> None:
    for pass_name in ("own_account", "rule", "matcher_decision"):
        assert _commit_key(Decided("x", pass_name, BASIS), None) == {"pass": pass_name, "basis": BASIS}
    assert _commit_key(Decided("x", "user", BASIS), None) == {"pass": "user", "basis": BASIS}


def test_a_proposal_is_accepted_as_the_users_with_the_proposal_as_its_basis() -> None:
    for pass_name in ("history", "llm", "matcher_proposal"):
        assert _commit_key(Decided("x", pass_name, BASIS), None) == {
            "pass": "user",
            "basis": {"pass": pass_name, "basis": BASIS},
        }


def test_a_value_the_user_fixed_and_no_payee_are_the_users_and_an_empty_field_has_no_key() -> None:
    assert _commit_key(Decided("x", "user", {}), None) == {"pass": "user"}
    shown = {"pass": "history", "basis": {"matches": 2}}
    assert _commit_key(Decided("x", "user", {}), shown) == {"pass": "user", "basis": shown}
    assert _commit_key(Decided(None, "user", {}), None) == {"pass": "user"}
    assert _commit_key(None, shown) is None


def test_a_user_decided_value_untouched_by_re_resolution_stays_user(scene: Scene) -> None:
    food = scene.category("Food")
    _s, (e,) = scene.movement(
        -700,
        type="flow",
        category_id=food,
        derivation=json.dumps({"type": {"pass": "user"}, "category": {"pass": "user"}}),
    )
    before = scene.row(e)
    scene.commit(e)
    after = scene.row(e)
    assert after.derivation["category"] == {"pass": "user"} and after.derivation["type"] == {"pass": "user"}
    assert after.version == before.version
