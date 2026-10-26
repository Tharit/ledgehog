"""Picking a partner (spec §5.7 "Offers", §5.9): the `pairing` field of a draft in preview and commit."""

from __future__ import annotations

import dataclasses
import json
from datetime import date, timedelta
from typing import Any

import pytest

from app.core.domain.errors import VersionConflict
from app.core.units import commit as commit_module
from app.core.units.commit import CommitRefused, UnitMoved
from app.core.units.draft import DraftEntry, DraftError, PairingDraft, UnitDraft
from app.core.units.plan import Plan
from app.core.units.preview import preview_unit
from tests.core.units.equality import preview_then_commit
from tests.core.units.scene import D, Scene
from tests.invariants.helpers import pair

USER_TYPE = json.dumps({"type": {"pass": "user"}})
USER_BOTH = json.dumps({"type": {"pass": "user"}, "counter_account": {"pass": "user"}})
PAIR_SET = {"pass": "user", "basis": {"from": "counterpart"}}
USER_PAIR = {"pass": "user", "basis": {}}


def pick(partner: int) -> PairingDraft:
    return PairingDraft("pick", partner)


def leg(
    scene: Scene, amount: int, account: int, *, on: date = D, counter: int | None = None, **kw: Any
) -> int:
    """An unpaired transfer leg, its type (and counter-account) the user's."""
    _src, (e,) = scene.movement(
        amount,
        account=account,
        on=on,
        type="transfer",
        counter_account_id=counter,
        derivation=USER_BOTH if counter is not None else USER_TYPE,
        authored=True,
        **kw,
    )
    return e


def pick_draft(scene: Scene, e: int, partner: int, *more: DraftEntry, **kw: Any) -> UnitDraft:
    """A draft of `e` that picks `partner`; versions cover the unit as drafted (what a preview returns)."""
    draft = scene.draft(e, DraftEntry(e, pairing=pick(partner)), *more)
    plan = preview_unit(scene.engine, draft, window_days=kw.pop("window_days", None))
    return dataclasses.replace(draft, versions=dict(plan.versions), **kw)


def codes(plan: Plan) -> list[str]:
    return sorted(p.code for p in plan.problems)


def kinds(plan: Plan, entry_id: int) -> set[str]:
    return {c.kind for c in plan.consequences if c.entry_id == entry_id}


# ---- the pick of an open leg -------------------------------------------------------------------------


def test_a_pick_of_an_open_leg_pairs_both_with_the_keys_of_the_user(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking)
    x = leg(scene, 1000, scene.savings, on=D + timedelta(days=2))
    leg(
        scene, 1000, scene.savings, on=D + timedelta(days=1)
    )  # a nearer exact one: the proposal, not the pick
    plan = scene.preview(e, DraftEntry(e, pairing=pick(x)))
    assert not plan.problems
    assert plan.row(e).counterpart_entry_id == x and plan.row(x).counterpart_entry_id == e
    assert plan.transfers[e].proposed_pick is None  # an explicit pick overrides the proposal
    for r, other in ((e, scene.savings), (x, scene.checking)):
        assert plan.row(r).derivation["counterpart"] == USER_PAIR
        assert plan.row(r).derivation["counter_account"] == PAIR_SET
        assert plan.row(r).fields["counter_account"].value == other
    assert plan.anchor_unit.state.confirmed and {r.id for r in plan.rows if r.in_unit} == {e, x}
    assert set(plan.versions) == {e, x}
    preview_then_commit(scene, scene.draft(e, DraftEntry(e, pairing=pick(x))))
    assert scene.row(e).counterpart_entry_id == x


def test_a_leg_keeps_its_own_counter_account_and_its_key(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.savings)
    x = leg(scene, 1000, scene.savings, on=D + timedelta(days=3))
    other = leg(scene, 1000, scene.savings, on=D + timedelta(days=1))  # the matcher would take this one
    plan, _ = preview_then_commit(scene, pick_draft(scene, e, x))
    assert plan.row(e).derivation["counter_account"] == {"pass": "user"}  # its own, as before
    assert plan.row(x).derivation["counter_account"] == PAIR_SET  # none before: the pair's
    assert scene.row(x).counterpart_entry_id == e and scene.row(other).counterpart_entry_id is None


def test_a_picked_untyped_entry_is_typed_as_transfer_by_the_user(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking)
    _s, (u,) = scene.movement(1000, account=scene.savings, authored=True)
    plan, _ = preview_then_commit(scene, pick_draft(scene, e, u))
    assert plan.row(u).fields["type"].value == "transfer" and plan.row(u).derivation["type"] == {
        "pass": "user"
    }
    assert scene.row(u).type == "transfer" and scene.row(u).counterpart_entry_id == e
    assert plan.row(u).fields["payee"].value is None and plan.row(u).fields["category"].value is None


def test_an_untyped_entry_that_is_not_its_sources_original_cannot_become_a_transfer(scene: Scene) -> None:
    e = leg(scene, -400, scene.checking)
    _s, (first, second) = scene.movement(600, 400, account=scene.savings, authored=True)
    plan = scene.preview(e, DraftEntry(e, pairing=pick(second)))
    assert "second_transfer" in codes(plan)
    assert plan.row(e).counterpart_entry_id is None  # the pick changed nothing
    with pytest.raises(CommitRefused) as exc:
        scene.commit_draft(
            dataclasses.replace(scene.draft(e, DraftEntry(e, pairing=pick(second))), versions=plan.versions)
        )
    assert exc.value.problems[0].code == "second_transfer"
    # the original of that source is the one that can become a transfer (here the amounts differ)
    assert codes(scene.preview(e, DraftEntry(e, pairing=pick(first)))) == ["pair_unequal"]


# ---- a leg paired elsewhere ------------------------------------------------------------------------


def test_a_pick_of_a_leg_paired_elsewhere_breaks_both_pairs(scene: Scene) -> None:
    (_sa, (a,)), (_sb, (b,)) = scene.transfer_pair(-1000)
    e = leg(scene, -1000, scene.cash)
    plan = scene.preview(e, DraftEntry(e, pairing=pick(b)))
    assert not plan.problems and plan.row(e).counterpart_entry_id == b
    assert plan.row(a).counterpart_entry_id is None and not plan.row(a).in_unit
    assert kinds(plan, a) >= {"left_behind"} and "returns_to_review" in kinds(plan, a)
    assert kinds(plan, b) == {"changed"} and kinds(plan, e) == {"changed"}
    assert {a, b, e} <= set(plan.versions)
    plan2, result = preview_then_commit(scene, pick_draft(scene, e, b))
    assert scene.row(a).counterpart_entry_id is None and scene.row(b).counterpart_entry_id == e
    assert {(c.entry_id, c.kind) for c in result.consequences} >= {(a, "left_behind")}
    assert scene.row(a).counter_account_id is None  # the counter-account the pair set left with it
    assert plan2.row(b).fields["counter_account"].value == scene.cash


def two_pairs(scene: Scene) -> tuple[tuple[int, int], tuple[int, int]]:
    """Two wrong pairs a1-b1 and a2-b2, each leg with its own counter-account (so a freed leg pairs again)."""
    out = []
    for day in (0, 1):
        a = leg(scene, -1000, scene.checking, on=D + timedelta(days=day), counter=scene.savings)
        b = leg(scene, 1000, scene.savings, on=D + timedelta(days=day), counter=scene.checking)
        out.append((a, b))
    return out[0], out[1]


def test_a_swap_takes_one_pick(scene: Scene) -> None:
    (a1, b1), (a2, b2) = two_pairs(scene)
    scene.settle()
    assert scene.row(a1).counterpart_entry_id == b1 and scene.row(a2).counterpart_entry_id == b2
    # the pairs are right by date; the user decides they are crossed: a1 with b2
    draft = pick_draft(scene, a1, b2)
    plan, _ = preview_then_commit(scene, draft)
    assert plan.row(a1).counterpart_entry_id == b2 and plan.row(b2).counterpart_entry_id == a1
    # the freed legs a2 and b1 know their counter-accounts and pair again in the same settling
    assert scene.row(a2).counterpart_entry_id == b1 and scene.row(b1).counterpart_entry_id == a2
    assert plan.row(a2).counterpart_entry_id == b1  # the preview says so


def test_a_cycle_of_three_wrong_pairs_takes_two_picks(scene: Scene) -> None:
    legs: list[tuple[int, int]] = []
    for day in (0, 1, 2):
        a = leg(scene, -1000, scene.checking, on=D + timedelta(days=day), counter=scene.savings)
        b = leg(scene, 1000, scene.savings, on=D + timedelta(days=day), counter=scene.checking)
        legs.append((a, b))
    (a1, b1), (a2, b2), (a3, b3) = legs
    # make the wrong cycle: a1-b2, a2-b3, a3-b1
    for x, y in ((a1, b2), (a2, b3), (a3, b1)):  # their own counter-accounts stay: a freed leg pairs again
        scene.tx(lambda c, x=x, y=y: pair(c, x, y))
    scene.settle()
    plan, _ = preview_then_commit(scene, pick_draft(scene, a1, b1))
    assert scene.row(a1).counterpart_entry_id == b1
    # one pick later a3 and b2 are paired (the only candidates left): one wrong pair remains besides a2-b3
    wrong = scene.row(a3).counterpart_entry_id == b2 and scene.row(a2).counterpart_entry_id == b3
    assert wrong and plan.row(a3).counterpart_entry_id == b2
    plan, _ = preview_then_commit(scene, pick_draft(scene, a2, b2))
    assert {scene.row(a).counterpart_entry_id for a in (a1, a2, a3)} == {b1, b2, b3}
    assert (scene.row(a2).counterpart_entry_id, scene.row(a3).counterpart_entry_id) == (b2, b3)
    assert plan.row(a3).counterpart_entry_id == b3


def test_picking_the_current_partner_again_is_a_no_op(scene: Scene) -> None:
    (_sa, (a,)), (_sb, (b,)) = scene.transfer_pair(-1000)
    plan = scene.preview(a, DraftEntry(a, pairing=pick(b)))
    assert not plan.problems and not plan.consequences and plan.row(a).counterpart_entry_id == b
    scene.settle()  # the seeded pair is confirmed
    before = scene.fingerprint()
    scene.commit_draft(
        dataclasses.replace(scene.draft(a, DraftEntry(a, pairing=pick(b))), versions=plan.versions)
    )
    assert scene.row(a).counterpart_entry_id == b and scene.fingerprint() == before  # nothing was written


# ---- what makes a partner an offer -----------------------------------------------------------------------


def test_a_partner_outside_the_window_is_refused_and_accepted_with_a_wider_one(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.savings)
    far = leg(scene, 1000, scene.savings, on=D + timedelta(days=20), counter=scene.checking)
    draft = scene.draft(e, DraftEntry(e, pairing=pick(far)))
    assert codes(preview_unit(scene.engine, draft)) == ["partner_not_offered"]
    wide = preview_unit(scene.engine, dataclasses.replace(draft, window_days=30), window_days=30)
    assert not wide.problems and wide.row(e).counterpart_entry_id == far
    # a commit checks a pick against the cap: the pick the widened preview accepted commits, whatever the
    # request says of the window
    versions = dict(wide.versions)
    scene.commit_draft(dataclasses.replace(draft, versions=versions))
    assert scene.row(e).counterpart_entry_id == far


def test_a_partner_beyond_the_cap_is_refused_in_preview_and_commit(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.savings)
    far = leg(scene, 1000, scene.savings, on=D + timedelta(days=91), counter=scene.checking)
    draft = scene.draft(e, DraftEntry(e, pairing=pick(far)))
    assert codes(preview_unit(scene.engine, draft, window_days=90)) == ["partner_not_offered"]
    with pytest.raises(CommitRefused) as exc:
        scene.commit_draft(dataclasses.replace(draft, versions={**scene.versions(e), **scene.versions(far)}))
    assert exc.value.problems[0].code == "partner_not_offered"
    assert scene.row(e).counterpart_entry_id is None


def test_a_partner_on_another_account_than_the_known_counter_account_is_refused(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.savings)
    on_cash = leg(scene, 1000, scene.cash)
    plan = scene.preview(e, DraftEntry(e, pairing=pick(on_cash)))
    assert codes(plan) == ["partner_not_offered"] and plan.row(e).counterpart_entry_id is None


def test_other_refusals_of_a_pick(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking)
    same_sign = leg(scene, -1000, scene.savings)
    same_account = leg(scene, 1000, scene.checking)
    flow = scene.movement(1000, account=scene.savings, type="flow", derivation=USER_TYPE, authored=True)[1][0]
    wants_other = leg(scene, 1000, scene.savings, counter=scene.cash)
    for partner in (same_sign, same_account, flow, wants_other, 987_654):
        plan = scene.preview(e, DraftEntry(e, pairing=pick(partner)))
        assert codes(plan) == ["partner_not_offered"], partner


def test_a_partner_in_the_unit_already_is_refused(scene: Scene) -> None:
    (_sa, (a, a_extra)), (_sb, (b,)) = scene.transfer_pair(-1000, out_extra=[-100])
    for partner in (a, a_extra, b):
        plan = scene.preview(a, DraftEntry(a, pairing=pick(partner)))
        if partner == b:  # its own partner again: a no-op
            assert not plan.problems and not plan.consequences
        else:
            assert codes(plan) == ["partner_in_unit"], partner


def test_a_pairing_on_something_that_is_not_a_transfer_leg_is_a_draft_error(scene: Scene) -> None:
    _s, (flow,) = scene.movement(-1000, type="flow", derivation=USER_TYPE)
    x = leg(scene, 1000, scene.savings)
    with pytest.raises(DraftError) as exc:
        scene.preview(flow, DraftEntry(flow, pairing=pick(x)))
    assert exc.value.code == "pairing_not_transfer"
    with pytest.raises(DraftError):
        PairingDraft("pick", -3)
    with pytest.raises(DraftError):
        PairingDraft("pick")
    with pytest.raises(DraftError):
        PairingDraft("reresolve", 4)
    with pytest.raises(DraftError):
        DraftEntry(-1, amount=-5, source_entry_id=flow, pairing=pick(x))


# ---- the amounts -----------------------------------------------------------------------------------------


def test_an_unequal_same_currency_pick_suggests_the_split_that_fixes_it(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking)
    x = leg(scene, 900, scene.savings)
    plan = scene.preview(e, DraftEntry(e, pairing=pick(x)))
    (problem,) = plan.problems
    assert problem.code == "pair_unequal" and problem.detail["difference"] == -100
    assert problem.suggested_split is not None
    assert (problem.suggested_split.source_entry_id, problem.suggested_split.amount) == (e, -100)
    with pytest.raises(CommitRefused):
        scene.commit_draft(
            dataclasses.replace(scene.draft(e, DraftEntry(e, pairing=pick(x))), versions=plan.versions)
        )
    split = DraftEntry(
        -1, amount=problem.suggested_split.amount, source_entry_id=problem.suggested_split.source_entry_id
    )
    fixed_plan, _ = preview_then_commit(scene, pick_draft(scene, e, x, split))
    assert fixed_plan.row(e).amount == -900 and fixed_plan.row(-1).fields["type"].value == "flow"


def test_the_split_may_be_taken_off_the_partners_source_when_it_is_the_larger(scene: Scene) -> None:
    e = leg(scene, -900, scene.checking)
    x = leg(scene, 1000, scene.savings)
    plan = scene.preview(e, DraftEntry(e, pairing=pick(x)))
    (problem,) = plan.problems
    assert problem.suggested_split is not None
    assert (problem.suggested_split.source_entry_id, problem.suggested_split.amount) == (x, 100)
    split = DraftEntry(-1, amount=100, source_entry_id=x)
    fixed_plan, _ = preview_then_commit(scene, pick_draft(scene, e, x, split))
    assert fixed_plan.row(x).amount == 900


def test_a_cross_currency_pick_is_matched_by_the_instructed_amount(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, instructed=(-1100, "USD"))
    x = leg(scene, 1100, scene.usd, currency="USD")
    plan, _ = preview_then_commit(scene, pick_draft(scene, e, x))
    assert plan.row(e).fields["counter_account"].value == scene.usd
    assert plan.row(e).counterpart_entry_id == x
    # a leg that says the money arrived in dollars is not offered a euro account
    y = leg(scene, 1000, scene.savings)
    assert codes(scene.preview(e, DraftEntry(e, pairing=pick(y)))) == ["partner_not_offered"]


# ---- proposals and re-resolving ---------------------------------------------------------------------


def test_the_proposal_is_effective_in_the_preview_and_accepted_by_a_commit(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking)
    x = leg(scene, 1000, scene.savings)
    plan = scene.preview(e)
    t = plan.transfers[e]
    assert t.proposed_pick == x and t.state == "paired" and t.partner is not None and t.partner.entry_id == x
    assert t.proposal is not None and t.offers[0].entry_id == x and t.offers[0].proposed  # the picker's list
    assert plan.row(x).in_unit and plan.anchor_unit.state.confirmed and x in plan.versions
    preview_then_commit(scene, scene.draft(e))
    assert scene.row(e).counterpart_entry_id == x
    assert scene.row(e).derivation["counterpart"] == USER_PAIR  # the user's decision, not the matcher's
    assert scene.row(x).derivation["counter_account"] == PAIR_SET


def test_a_commit_takes_only_the_proposals_whose_entries_the_client_carries_versions_for(
    scene: Scene,
) -> None:
    e = leg(scene, -1000, scene.checking)
    x = leg(scene, 1000, scene.savings)
    scene.commit_draft(UnitDraft(e, [], versions=scene.versions(e)))  # the client did not see the partner
    assert scene.row(e).counterpart_entry_id is None and scene.row(x).counterpart_entry_id is None


def test_a_stale_version_of_a_proposed_partner_is_a_conflict(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking)
    x = leg(scene, 1000, scene.savings)
    versions = {**scene.versions(e), **scene.versions(x)}
    scene.commit_draft(UnitDraft(x, [DraftEntry(x, note="moved")], versions=scene.versions(x)))
    with pytest.raises(VersionConflict) as exc:
        scene.commit_draft(UnitDraft(e, [], versions=versions))
    assert x in exc.value.entry_ids


def test_an_explicit_pick_overrides_the_proposal(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking)
    exact = leg(scene, 1000, scene.savings)
    other = leg(scene, 900, scene.savings, on=D + timedelta(days=1))
    plan = scene.preview(e, DraftEntry(e, pairing=pick(other)))
    assert plan.row(e).counterpart_entry_id == other and exact not in {r.id for r in plan.rows}
    assert exact not in plan.versions and plan.transfers[e].proposed_pick is None


def test_reresolve_takes_the_proposal_afresh_and_drops_a_stored_pair(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking)
    nearest = leg(scene, 1000, scene.savings)
    later = leg(scene, 1000, scene.savings, on=D + timedelta(days=1))
    chosen = pick_draft(scene, e, later)
    scene.commit_draft(chosen)
    assert scene.row(e).counterpart_entry_id == later
    # re-resolving drops the stored pair; the closest exact open offer is the proposal again
    again = DraftEntry(e, pairing=PairingDraft("reresolve"))
    plan = scene.preview(e, again)
    assert plan.transfers[e].proposed_pick == nearest and plan.row(e).counterpart_entry_id == nearest
    assert "left_behind" in kinds(plan, later)
    preview_then_commit(scene, scene.draft(e, again))
    assert scene.row(e).counterpart_entry_id == nearest and scene.row(later).counterpart_entry_id is None


def test_reresolving_an_unpaired_leg_changes_nothing_but_the_proposal_it_takes(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking)
    plan = scene.preview(e, DraftEntry(e, pairing=PairingDraft("reresolve")))
    assert not plan.problems and not plan.consequences and plan.transfers[e].proposed_pick is None


# ---- commit: versions, locks, races -----------------------------------------------------------------


def test_a_pick_needs_the_versions_of_the_partners_entries(scene: Scene) -> None:
    (_sa, (a,)), (_sb, (b,)) = scene.transfer_pair(-1000)
    e = leg(scene, -1000, scene.cash)
    draft = scene.draft(e, DraftEntry(e, pairing=pick(b)))  # versions of e only
    with pytest.raises(VersionConflict) as exc:
        scene.commit_draft(draft)
    assert set(exc.value.entry_ids) == {a, b}
    assert scene.row(e).counterpart_entry_id is None
    moved = pick_draft(scene, e, b)
    scene.commit_draft(UnitDraft(a, [DraftEntry(a, note="elsewhere")], versions=scene.versions(a)))
    with pytest.raises(VersionConflict) as exc:
        scene.commit_draft(moved)
    assert a in exc.value.entry_ids


def test_a_partner_taken_in_the_meantime_is_a_conflict(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking)
    x = leg(scene, 1000, scene.savings)
    mine = pick_draft(scene, e, x)
    rival = leg(scene, -1000, scene.cash)
    scene.commit_draft(
        dataclasses.replace(
            scene.draft(rival, DraftEntry(rival, pairing=pick(x))),
            versions={**scene.versions(rival), **scene.versions(x)},
        )
    )
    with pytest.raises(VersionConflict) as exc:
        scene.commit_draft(mine)
    assert x in exc.value.entry_ids


def test_a_closure_that_moved_under_the_locks_is_unit_moved(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    e = leg(scene, -1000, scene.checking)
    x = leg(scene, 1000, scene.savings)
    draft = pick_draft(scene, e, x)
    real = commit_module._read_drafted_closure
    calls: list[int] = []

    def stale(conn: Any, d: Any) -> tuple[int, ...] | None:
        calls.append(1)
        found = real(conn, d)
        return (e,) if len(calls) == 1 and found else found  # the first read missed the partner

    monkeypatch.setattr(commit_module, "_read_drafted_closure", stale)
    with pytest.raises(UnitMoved):
        scene.commit_draft(draft)
    assert scene.row(e).counterpart_entry_id is None


def test_a_commit_locks_the_partners_account(scene: Scene) -> None:
    import threading

    from app.utils.db import locks
    from tests import lockwatch

    e = leg(scene, -1000, scene.checking)
    x = leg(scene, 1000, scene.savings)
    draft = pick_draft(scene, e, x)
    done = threading.Event()
    errors: list[BaseException] = []

    def run() -> None:
        try:
            scene.commit_draft(draft)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            done.set()

    with scene.engine.connect() as holder:
        locks.lock_accounts(holder, [scene.savings])
        t = threading.Thread(target=run)
        t.start()
        lockwatch.wait_until_waiting(scene.engine, "the commit to wait for the partner's account")
        assert not done.is_set()
        holder.rollback()
    t.join(10)
    assert done.is_set() and not errors
    assert scene.row(e).counterpart_entry_id == x


def test_a_confirmed_units_leg_that_picks_returns_the_former_partner_to_review(scene: Scene) -> None:
    (_sa, (a,)), (_sb, (b,)) = scene.transfer_pair(-1000)
    assert scene.preview(a).anchor_unit.state.confirmed
    x = leg(scene, -1000, scene.cash)
    plan = scene.preview(b, DraftEntry(b, pairing=pick(x)))
    assert not plan.problems and plan.row(b).counterpart_entry_id == x
    assert {"left_behind", "returns_to_review"} <= kinds(plan, a)
    _plan, result = preview_then_commit(scene, pick_draft(scene, b, x))
    assert (a, "left_behind") in {(c.entry_id, c.kind) for c in result.consequences}
    assert {r.id for r in result.entries} >= {a, b, x}
