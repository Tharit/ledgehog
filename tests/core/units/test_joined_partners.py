"""A partner the preview shows in the unit, whether the draft picked it or a proposal / settling joined it,
is edited like any entry of the unit (spec §6): pinned as a pick, it is committed as the proposal would be.
The draft's membership is the anchor's closure plus the closures of the picked partners; the server stays
strict about anything else."""

from __future__ import annotations

import dataclasses
import json
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text

from app.core.domain.errors import VersionConflict
from app.core.units.commit import UnitMoved
from app.core.units.draft import DraftEntry, DraftError, PairingDraft, UnitDraft
from app.core.units.plan import Plan
from app.core.units.preview import preview_unit
from tests.core.units.equality import preview_then_commit
from tests.core.units.scene import D, Scene, fixed
from tests.core.units.test_picks import leg, pick

USER_TYPE = json.dumps({"type": {"pass": "user"}})


def pinned(scene: Scene, e: int, partner: int, *more: DraftEntry) -> UnitDraft:
    """The draft the client sends once a proposal's partner is edited: the pick of the proposal, pinned."""
    return scene.draft(e, DraftEntry(e, pairing=pick(partner)), *more)


def with_versions(draft: UnitDraft, plan: Plan) -> UnitDraft:
    return dataclasses.replace(draft, versions=dict(plan.versions))


# ---- the pinned pick of a proposal ----------------------------------------------------------------------


def test_a_proposed_partner_edited_under_a_pinned_pick_is_previewed_and_committed(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking)
    x = leg(scene, 1000, scene.savings)
    tag = scene.tag("trip")
    plain = scene.preview(e)
    assert plain.transfers[e].proposed_pick == x and plain.row(x).in_unit
    draft = pinned(scene, e, x, DraftEntry(x, description="mine", note="n", tags_add=(tag,)))
    plan, _ = preview_then_commit(scene, draft)
    assert plan.row(x).in_unit and plan.row(x).description == "mine"
    row = scene.row(x)
    assert (row.description, row.note, row.counterpart_entry_id) == ("mine", "n", e)
    assert scene.tags_of(x) == (tag,)


def test_a_pinned_pick_commits_the_keys_of_accepting_the_proposal(scene: Scene) -> None:
    e1 = leg(scene, -1000, scene.checking)
    x1 = leg(scene, 1000, scene.savings)
    e2 = leg(scene, -2000, scene.checking, on=D + timedelta(days=20))
    x2 = leg(scene, 2000, scene.savings, on=D + timedelta(days=20))
    tag = scene.tag("trip")
    plan, _ = preview_then_commit(scene, pinned(scene, e1, x1, DraftEntry(x1, tags_add=(tag,))))
    preview_then_commit(scene, scene.draft(e2))  # accepted as proposed
    assert plan.row(x1).in_unit
    for pinned_id, proposed_id in ((e1, e2), (x1, x2)):
        a, b = scene.row(pinned_id), scene.row(proposed_id)
        assert (a.type, a.derivation, a.review_flags) == (b.type, b.derivation, b.review_flags)
        assert (a.payee_id, a.category_id, a.counter_account_id) == (
            b.payee_id,
            b.category_id,
            b.counter_account_id,
        )


def test_a_pinned_partner_with_a_new_split_and_a_removed_one_commits(scene: Scene) -> None:
    e = leg(scene, -700, scene.checking)
    # the partner's source holds three entries: the original (the transfer leg) and two others
    _s, (x, y, z) = scene.movement(
        700,
        200,
        100,
        account=scene.savings,
        authored=True,
        lead={"type": "transfer", "derivation": USER_TYPE},
    )
    drop, add = z, -1
    draft = pinned(
        scene,
        e,
        x,
        DraftEntry(y, note="kept"),
        DraftEntry(add, amount=100, source_entry_id=y),
    )
    draft = dataclasses.replace(draft, removed_entry_ids=[drop])
    plan = preview_unit(scene.engine, draft)
    assert not plan.problems, plan.problems
    assert {r.id for r in plan.rows if r.in_unit} >= {e, x, y, add}
    assert z in {c.entry_id for c in plan.consequences if c.kind == "deleted"}
    result = scene.commit_draft(with_versions(draft, plan))
    assert z in result.removed_entry_ids and add in result.created
    assert scene.row(y).note == "kept" and scene.row(x).counterpart_entry_id == e


def test_a_settling_pulled_partner_pinned_has_its_edits_written(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.savings)
    x = leg(scene, 1000, scene.savings)
    plain = scene.preview(e)
    assert x in plain.versions and plain.transfers[e].partner is not None  # settling joins x
    assert not plain.transfers[e].proposed_pick  # no proposal: settling pairs it
    draft = pinned(scene, e, x, DraftEntry(x, note="mine"))
    preview_then_commit(scene, draft)
    assert scene.row(x).note == "mine" and scene.row(x).counterpart_entry_id == e


def test_a_commit_without_the_version_of_a_pinned_partner_is_a_conflict(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking)
    x = leg(scene, 1000, scene.savings)
    draft = pinned(scene, e, x, DraftEntry(x, note="mine"))  # versions of e only
    with pytest.raises(VersionConflict) as exc:
        scene.commit_draft(draft)
    assert x in exc.value.entry_ids
    assert scene.row(x).note is None


# ---- the unit's structure moved since the preview ---------------------------------------------------------


def test_a_proposal_that_vanished_without_a_version_change_is_unit_moved(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking)
    x = leg(scene, 1000, scene.savings)
    seen = scene.preview(e)
    assert x in seen.versions and seen.transfers[e].proposed_pick == x

    # x stops being an offer (settling rederived it as a flow: no version moves for that)
    def rederive(c: Any) -> None:
        c.execute(text("SELECT set_config('ledger.settling', 'on', true)"))
        c.execute(text("UPDATE ledger_entry SET type = 'flow' WHERE id = :x"), {"x": x})

    scene.tx(rederive)
    assert scene.versions(x)[x] == seen.versions[x]
    with pytest.raises(UnitMoved):
        scene.commit_draft(UnitDraft(e, [], versions=dict(seen.versions)))
    assert scene.row(e).counterpart_entry_id is None


def test_a_leg_settling_now_pulls_in_that_the_client_has_no_version_for_is_unit_moved(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.savings)
    x = leg(scene, 1000, scene.savings)
    with pytest.raises(UnitMoved):
        scene.commit_draft(UnitDraft(e, [], versions=scene.versions(e)))
    assert scene.row(e).counterpart_entry_id is None and scene.row(x).counterpart_entry_id is None
    scene.commit_draft(UnitDraft(e, [], versions={**scene.versions(e), **scene.versions(x)}))  # seen: fine
    assert scene.row(e).counterpart_entry_id == x


# ---- a stored pair re-picked: the partner leaves, its drafts stay ------------------------------


def test_a_stored_pair_repicked_commits_the_edits_and_split_of_the_partner_that_leaves(scene: Scene) -> None:
    (_sa, (a,)), (_sb, (b,)) = scene.transfer_pair(-1000)
    q = leg(scene, 1000, scene.savings, on=D + timedelta(days=2))
    tag = scene.tag("trip")
    new = -1
    draft = scene.draft(
        a,
        DraftEntry(a, pairing=pick(q)),
        DraftEntry(b, note="b's", tags_add=(tag,)),
        DraftEntry(new, amount=300, source_entry_id=b),
    )
    plan = preview_unit(scene.engine, draft)
    assert not plan.problems, plan.problems
    assert not plan.row(b).in_unit and plan.row(q).in_unit
    assert any(c.entry_id == b for c in plan.consequences)
    result = scene.commit_draft(with_versions(draft, plan))
    assert result.created[new] > 0
    assert scene.row(b).note == "b's" and scene.row(b).counterpart_entry_id is None
    assert scene.tags_of(b) == (tag,) and scene.row(a).counterpart_entry_id == q


# ---- what stays refused -----------------------------------------------------------------------------------


def test_an_edit_outside_the_membership_is_still_unknown_entry(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking)
    x = leg(scene, 1000, scene.savings)
    plain = scene.preview(e)
    assert x in plain.versions  # the proposal joins x in the preview
    with pytest.raises(DraftError) as exc:  # but an edit on it, without the pick, is a client bug
        scene.preview(e, DraftEntry(x, note="mine"))
    assert exc.value.code == "unknown_entry"
    with pytest.raises(DraftError) as exc:
        scene.preview(e, DraftEntry(-5, amount=100, source_entry_id=x))
    assert exc.value.code == "unknown_entry"


def test_a_pairing_edit_on_a_partner_the_draft_joined_is_refused(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking)
    x = leg(scene, 1000, scene.savings)
    other = leg(scene, -1000, scene.cash)
    with pytest.raises(DraftError) as exc:
        scene.preview(e, DraftEntry(e, pairing=pick(x)), DraftEntry(x, pairing=pick(other)))
    assert (exc.value.code, exc.value.entry_id, exc.value.field) == ("pairing_outside_unit", x, "pairing")
    with pytest.raises(DraftError) as exc:
        scene.preview(e, DraftEntry(e, pairing=pick(x)), DraftEntry(x, pairing=PairingDraft("reresolve")))
    assert exc.value.code == "pairing_outside_unit"


@pytest.mark.parametrize(
    ("field", "kwargs"),
    [
        ("type", lambda scene: {"type": fixed("flow")}),
        ("counter_account", lambda scene: {"counter_account": fixed(scene.cash)}),
    ],
)
def test_a_fixed_type_or_counter_account_on_a_picked_partner_is_pair_fixed(
    scene: Scene, field: str, kwargs: Any
) -> None:
    e = leg(scene, -1000, scene.checking)
    x = leg(scene, 1000, scene.savings)
    with pytest.raises(DraftError) as exc:
        scene.preview(e, DraftEntry(e, pairing=pick(x)), DraftEntry(x, **kwargs(scene)))
    assert (exc.value.code, exc.value.entry_id, exc.value.field) == ("pair_fixed", x, field)
    # the pair's own value is no change at all
    ok = scene.preview(
        e,
        DraftEntry(e, pairing=pick(x)),
        DraftEntry(x, type=fixed("transfer"), counter_account=fixed(scene.checking)),
    )
    assert not ok.problems
