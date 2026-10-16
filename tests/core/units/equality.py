"""The core promise: a preview equals the commit and the settle that follow it."""

from __future__ import annotations

import dataclasses
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
            "tag_ids": tuple(r.tag_ids),
            "document_id": r.document_id,
            "document_line": r.document_line,  # (document, line number), None: no line (spec §5.8)
        }
        for r in plan.rows
    }


def stored_lines(scene: Scene, entry_ids: list[int]) -> dict[int, tuple[int, int]]:
    """The line each of `entry_ids` references: (the line's document, its number), by entry id."""
    return {
        int(r.id): (int(r.document_id), int(r.line_no))
        for r in scene.q(
            "SELECT e.id, l.document_id, l.line_no FROM ledger_entry AS e"
            " JOIN external_document_line AS l ON l.id = e.document_line_id WHERE e.id = ANY(:i)",
            i=entry_ids,
        )
    }


def created_or_id(created: dict[int, int] | Any, entry_id: int) -> int:
    return int(created.get(entry_id, entry_id))


def preview_then_commit(scene: Scene, draft: UnitDraft) -> tuple[Plan, CommitResult]:
    """Preview (and prove it wrote nothing), commit, and assert the stored result is the preview."""
    before = scene.fingerprint()
    plan = preview_unit(scene.engine, draft)
    assert scene.fingerprint() == before, "a preview wrote something"
    assert not plan.problems, plan.problems
    pulled = set(plan.versions) != set(draft.versions)
    # a commit carries the versions of everything the preview shows (the proposals it took as picks included)
    draft = dataclasses.replace(draft, versions={**draft.versions, **plan.versions})
    result = scene.commit_draft(draft)
    assert scene.settle().touched_entry_ids == (), "settling after a commit is not idempotent"
    scene.assert_checks_clean()  # I3, I9, I10, I11, I31 and the rest, as the integrity views judge them
    want = previewed(plan)
    got = settled_state(scene, plan, dict(result.created))
    lines = stored_lines(scene, [created_or_id(result.created, i) for i in want])
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
            "tag_ids": scene.tags_of(created_or_id(result.created, temp_or_id)),
            "document_id": row.document_id,
            "document_line": lines.get(created_or_id(result.created, temp_or_id)),
        }
        assert actual == expected, f"entry {temp_or_id}"
    previewed_consequences = sorted(
        (result.created.get(c.entry_id, c.entry_id), c.kind) for c in plan.consequences
    )
    committed_consequences = sorted((c.entry_id, c.kind) for c in result.consequences)
    if pulled:
        # settling paired a leg of the unit with a leg outside it (the preview brought its unit in): the
        # preview shows what that changes (the leg `changed`, a unit that returns to review or does not, a
        # leg `unpaired` into the unit rather than `left_behind` it) and the commit's own plan, which holds
        # no leg of the ledger, cannot know: the entries agree, the kinds may differ in those ways
        both = set(previewed_consequences) ^ set(committed_consequences)
        assert all(
            kind in ("changed", "returns_to_review", "unpaired", "left_behind") for _id, kind in both
        ), both
        # the commit's own plan, which holds no leg of the ledger, may also return an entry to review that
        # the preview shows paired and confirmed again (settling re-pairs it after the commit)
        extra = {i for i, _k in committed_consequences} - {i for i, _k in previewed_consequences}
        assert all(k == "returns_to_review" for i, k in committed_consequences if i in extra), (
            previewed_consequences,
            committed_consequences,
        )
    else:
        assert previewed_consequences == committed_consequences
    assert set(result.removed_entry_ids) == {e.id for e in plan.removed}
    return plan, result
