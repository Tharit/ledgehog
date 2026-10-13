"""The core promise: a preview equals the commit and the settle that follow it."""

from __future__ import annotations

from typing import Any

from app.core.units.commit import CommitResult
from app.core.units.draft import UnitDraft
from app.core.units.plan import Plan
from app.core.units.preview import preview_unit
from tests.core.units.scene import Scene


def settled_state(scene: Scene, plan: Plan, created: dict[int, int]) -> dict[int, dict[str, Any]]:
    real = {r.id: created.get(r.id, r.id) for r in plan.rows}
    stored = scene.rows(*real.values())
    return {r.id: stored[real[r.id]] for r in plan.rows}  # type: ignore[misc]


def previewed(plan: Plan) -> dict[int, dict[str, Any]]:
    return {
        r.id: {
            "type": r.fields["type"].value,
            "payee_id": r.fields["payee"].value,
            "category_id": r.fields["category"].value,
            "counter_account_id": r.fields["counter_account"].value,
            "amount": r.amount,
            "description": r.description,
            "note": r.note,
            "derivation": dict(r.derivation),
            "review_flags": list(r.flags),
        }
        for r in plan.rows
    }


def preview_then_commit(scene: Scene, draft: UnitDraft) -> tuple[Plan, CommitResult]:
    """Preview (and prove it wrote nothing), commit, and assert the stored result is the preview."""
    before = scene.fingerprint()
    plan = preview_unit(scene.engine, draft)
    assert scene.fingerprint() == before, "a preview wrote something"
    assert not plan.problems, plan.problems
    result = scene.commit_draft(draft)
    assert scene.settle().touched_entry_ids == (), "settling after a commit is not idempotent"
    scene.assert_checks_clean()  # I3, I9, I10, I11, I31 and the rest, as the integrity views judge them
    want = previewed(plan)
    got = settled_state(scene, plan, dict(result.created))
    for temp_or_id, expected in want.items():
        row = got[temp_or_id]
        actual = {
            "type": row.type,
            "payee_id": row.payee_id,
            "category_id": row.category_id,
            "counter_account_id": row.counter_account_id,
            "amount": row.amount,
            "description": row.description,
            "note": row.note,
            "derivation": dict(row.derivation),
            "review_flags": list(row.review_flags),
        }
        assert actual == expected, f"entry {temp_or_id}"
    assert {
        c.entry_id if c.entry_id > 0 else result.created[c.entry_id]: c.kind for c in plan.consequences
    } == {c.entry_id: c.kind for c in result.consequences} or sorted(
        (result.created.get(c.entry_id, c.entry_id), c.kind) for c in plan.consequences
    ) == sorted((c.entry_id, c.kind) for c in result.consequences)
    assert set(result.removed_entry_ids) == {e.id for e in plan.removed}
    return plan, result
