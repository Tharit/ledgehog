"""Counter-legs (spec §5.7): the other side of a transfer, created by a commit on an unsynced counter-account.

The `pairing` mode `counter_leg`, the proposal the preview takes (and a commit accepts) where the leg has no
open offer, the amount rule, the I40 checks, and a counter-leg following its partner's amount.
"""

from __future__ import annotations

import dataclasses
import json
import threading
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from app.core.balance.records import set_manual_record
from app.core.domain.errors import VersionConflict
from app.core.ledger.sources import delete_source, update_source
from app.core.units import commit as commit_module
from app.core.units.commit import CommitRefused, UnitMoved
from app.core.units.draft import CounterLegDraft, DraftEntry, DraftError, PairingDraft, UnitDraft
from app.core.units.plan import Plan
from app.core.units.preview import preview_unit
from app.core.units.transfers import proposed_temp_id
from app.utils.db import locks
from tests import lockwatch
from tests.core.units.equality import preview_then_commit
from tests.core.units.scene import D, Scene, fixed

USER_TYPE = json.dumps({"type": {"pass": "user"}})
USER_BOTH = json.dumps({"type": {"pass": "user"}, "counter_account": {"pass": "user"}})
PAIR_SET = {"pass": "user", "basis": {"from": "counterpart"}}
USER_PAIR = {"pass": "user", "basis": {}}


def cl(temp: int = -1, received: int | None = None) -> PairingDraft:
    return PairingDraft("counter_leg", counter_leg=CounterLegDraft(temp, received))


def leg(
    scene: Scene, amount: int, account: int, *, on: date = D, counter: int | None = None, **kw: Any
) -> int:
    """An unpaired transfer leg (user-authored on `account`), its type (and counter-account) the user's."""
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


def codes(plan: Plan) -> list[str]:
    return sorted(p.code for p in plan.problems)


def kinds(plan: Plan, entry_id: int) -> set[str]:
    return {c.kind for c in plan.consequences if c.entry_id == entry_id}


def counter_legs_of(scene: Scene, account: int) -> list[Any]:
    return scene.q("SELECT * FROM source_transaction WHERE account_id = :a ORDER BY id", a=account)


def committed(scene: Scene, e: int, *entries: DraftEntry) -> tuple[int, Plan]:
    """Commit the draft of `e` (counter-leg and all); returns the counter-leg's entry id."""
    plan, result = preview_then_commit(scene, scene.draft(e, *entries))
    (real,) = [v for k, v in result.created.items() if plan.row(k).counter_leg_for is not None]
    return real, plan


# ---- the draft record -----------------------------------------------------------------------------------


def test_the_draft_record_is_strict() -> None:
    assert PairingDraft("counter_leg", counter_leg=CounterLegDraft(-3, 500)).counter_leg is not None
    for bad in (
        lambda: PairingDraft("counter_leg"),  # names no counter-leg
        lambda: PairingDraft("pick", 5, counter_leg=CounterLegDraft(-3)),
        lambda: PairingDraft("keep", counter_leg=CounterLegDraft(-3)),
        lambda: CounterLegDraft(3),  # a temporary id is negative
        lambda: CounterLegDraft(0),
    ):
        with pytest.raises(DraftError) as exc:
            bad()
        assert exc.value.code == "invalid_pairing"
    for amount in (0, -5):
        with pytest.raises(DraftError) as exc:
            CounterLegDraft(-1, amount)
        assert exc.value.code == "received_amount_sign"
    with pytest.raises(DraftError) as exc:  # the temporary id is one of the draft's ids
        UnitDraft(5, [DraftEntry(5, pairing=cl(-1)), DraftEntry(-1, amount=-1, source_entry_id=5)])
    assert exc.value.code == "duplicate_entry"


# ---- the proposal is effective ----------------------------------------------------------------------------


def test_a_leg_with_no_open_offer_shows_its_counter_leg_as_the_proposal_taken(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.cash, purpose="GA-AUSZAHLUNG Sparkasse")
    plan = scene.preview(e)
    ghost = proposed_temp_id(e)
    t = plan.transfers[e]
    assert t.proposed_counter_leg and t.proposed_pick is None and t.state == "paired"
    assert t.partner is not None and t.partner.entry_id == ghost and t.partner.account_id == scene.cash
    assert t.proposal is not None and t.proposal.kind == "counter_leg"  # the proposal it had stays shown
    assert [o.kind for o in t.offers] == ["counter_leg"] and t.offers[0].proposed
    g = plan.row(ghost)
    assert g.version is None and g.stored is None and g.in_unit and g.original
    assert (g.account_id, g.amount, g.currency, g.booked_on) == (scene.cash, 1000, "EUR", D)
    assert (g.purpose, g.description, g.counter_leg_for, g.counterpart_entry_id) == (
        "GA-AUSZAHLUNG Sparkasse",
        None,
        e,
        e,
    )
    assert g.fields["type"].value == "transfer" and g.fields["counter_account"].value == scene.checking
    assert g.fields["payee"].value is None and g.fields["category"].value is None
    assert g.derivation == {
        "type": {"pass": "user"},
        "counter_account": PAIR_SET,
        "counterpart": USER_PAIR,
        "document": {"pass": "matcher_decision"},  # the unit is confirmed: settling records "none"
    }
    assert plan.row(e).derivation["counterpart"] == USER_PAIR
    assert plan.row(e).counterpart_entry_id == ghost and plan.transfers[ghost].state == "paired"
    assert (ghost, "created") in {(c.entry_id, c.kind) for c in plan.consequences}
    assert plan.anchor_unit.state.confirmed and plan.anchor_unit.entry_ids == (e, ghost)
    assert not plan.problems and set(plan.versions) == {e}
    assert plan.created_ids == (ghost,)


def test_a_commit_creates_the_counter_leg_as_the_users_decision(scene: Scene) -> None:
    set_manual_record_on(scene, scene.cash, 10_000)
    e = leg(scene, -1000, scene.checking, counter=scene.cash, purpose="GA-AUSZAHLUNG Sparkasse")
    plan, result = preview_then_commit(scene, scene.draft(e))
    ghost = proposed_temp_id(e)
    real = result.created[ghost]
    (source,) = counter_legs_of(scene, scene.cash)
    assert source.importer is None and source.import_run_id is None and source.source_format is None
    assert source.content_hash is None and source.source_id and source.duplicate_of is None
    assert (source.amount, source.currency, source.booked_on) == (1000, "EUR", D)
    assert source.purpose == "GA-AUSZAHLUNG Sparkasse" and source.raw == {"counter_leg_for": e}
    entry = scene.row(real)
    assert (entry.type, entry.counter_account_id, entry.counterpart_entry_id) == (
        "transfer",
        scene.checking,
        e,
    )
    assert (entry.amount, entry.account_id, entry.payee_id, entry.category_id) == (
        1000,
        scene.cash,
        None,
        None,
    )
    assert scene.row(e).counterpart_entry_id == real
    assert entry.derivation == plan.row(ghost).derivation
    for r in (e, real):
        assert scene.row(r).derivation["counterpart"] == USER_PAIR
    assert (real, "created") in {(c.entry_id, c.kind) for c in result.consequences}
    assert real in {r.id for r in result.entries} and real in result.versions
    assert result.units[0].state.confirmed and set(result.units[0].entry_ids) == {e, real}
    # the account's derived entries were recomputed: the record of 10 000 now holds the 1 000 received
    opening = scene.q(
        "SELECT amount FROM ledger_entry WHERE type = 'opening' AND account_id = :a", a=scene.cash
    )
    assert [r.amount for r in opening] == [9_000]


def set_manual_record_on(scene: Scene, account: int, balance: int) -> None:
    set_manual_record(scene.engine, account, D + timedelta(days=10), balance)


def test_the_explicit_counter_leg_uses_the_clients_temporary_id(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.cash)
    plan = scene.preview(e, DraftEntry(e, pairing=cl(-7)))
    assert plan.row(-7).counter_leg_for == e and plan.created_ids == (-7,)
    assert not plan.transfers[e].proposed_counter_leg
    real, _ = committed(scene, e, DraftEntry(e, pairing=cl(-7)))
    assert scene.row(real).counterpart_entry_id == e and len(counter_legs_of(scene, scene.cash)) == 1


def test_an_incoming_leg_gets_the_negated_amount(scene: Scene) -> None:
    e = leg(scene, 2500, scene.checking, counter=scene.cash, on=D)
    real, _ = committed(scene, e)
    assert scene.row(real).amount == -2500


def test_a_leg_with_an_open_offer_gets_no_proposal_and_a_counter_leg_may_still_be_chosen(
    scene: Scene,
) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.cash)
    x = leg(scene, 700, scene.cash, on=D + timedelta(days=1))  # an open offer of another amount
    plan = scene.preview(e)
    assert plan.row(e).counterpart_entry_id is None and plan.transfers[e].proposal is None
    assert [o.kind for o in plan.transfers[e].offers] == ["open_leg", "counter_leg"]
    plan = scene.preview(e, DraftEntry(e, pairing=cl()))
    assert plan.row(-1).counter_leg_for == e and plan.row(e).counterpart_entry_id == -1
    # x stays an unpaired leg of its own
    assert x not in {r.id for r in plan.rows if r.in_unit}
    committed(scene, e, DraftEntry(e, pairing=cl()))
    assert scene.row(x).counterpart_entry_id is None


def test_an_explicit_pick_of_another_partner_overrides_the_proposal(scene: Scene) -> None:
    (_sa, (a,)), (_sb, (b,)) = scene.transfer_pair(-1000)  # b: a leg paired elsewhere, on savings
    e = leg(scene, -1000, scene.checking, counter=scene.savings)
    assert scene.preview(e).transfers[e].proposed_counter_leg  # paired elsewhere is no open offer
    plan = scene.preview(e, DraftEntry(e, pairing=PairingDraft("pick", b)))
    assert plan.row(e).counterpart_entry_id == b and not plan.transfers[e].proposed_counter_leg
    assert all(r.counter_leg_for is None for r in plan.rows)
    preview_then_commit(scene, scene.draft(e, DraftEntry(e, pairing=PairingDraft("pick", b))))
    assert len(counter_legs_of(scene, scene.savings)) == 1  # b's own source: nothing was created


def test_reresolve_takes_the_proposal_afresh_and_a_flow_has_none(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.cash)
    plan = scene.preview(e, DraftEntry(e, pairing=PairingDraft("reresolve")))
    assert plan.transfers[e].proposed_counter_leg
    flow = scene.preview(e, DraftEntry(e, type=fixed("flow")))
    assert flow.transfers == {} and all(r.counter_leg_for is None for r in flow.rows)
    scene.commit(e, DraftEntry(e, type=fixed("flow")))
    assert counter_legs_of(scene, scene.cash) == []


def test_a_proposal_that_needs_the_amount_received_is_not_taken(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.usd)
    plan = scene.preview(e)
    t = plan.transfers[e]
    assert t.proposal is not None and t.proposal.kind == "counter_leg" and not t.proposed_counter_leg
    assert t.state == "unmatched" and plan.row(e).counterpart_entry_id is None
    (offer,) = t.offers
    assert offer.counter_leg is not None and offer.counter_leg.needs_received_amount and offer.amount is None
    scene.commit(e)  # a commit without the amount creates nothing
    assert counter_legs_of(scene, scene.usd) == []


def test_a_unit_that_was_reviewed_before_is_not_given_a_counter_leg_it_does_not_need(scene: Scene) -> None:
    (_sa, (a,)), (_sb, _b) = scene.transfer_pair(-500)
    plan = scene.preview(a)
    assert all(r.counter_leg_for is None for r in plan.rows) and plan.transfers[a].proposal is None


# ---- cross-currency ---------------------------------------------------------------------------------------


def test_cross_currency_with_an_instructed_amount_needs_no_received_amount(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.usd, instructed=(-1100, "USD"))
    plan = scene.preview(e)  # taken as the proposal
    g = plan.row(proposed_temp_id(e))
    assert (g.amount, g.currency, g.account_id) == (1100, "USD", scene.usd)
    assert plan.transfers[e].proposed_counter_leg and not plan.problems
    real, _ = committed(scene, e)
    assert (scene.row(real).amount, scene.row(real).currency) == (1100, "USD")
    assert (
        scene.q("SELECT currency FROM source_transaction WHERE account_id = :a", a=scene.usd)[0].currency
        == "USD"
    )
    # an amount received where the instructed one is known is refused
    other = leg(scene, -500, scene.checking, counter=scene.usd, instructed=(-550, "USD"))
    assert codes(scene.preview(other, DraftEntry(other, pairing=cl(-1, 560)))) == [
        "received_amount_not_needed"
    ]


def test_cross_currency_without_an_instructed_amount_takes_the_amount_received(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.usd)
    plan = scene.preview(e, DraftEntry(e, pairing=cl(-1)))
    assert codes(plan) == ["received_amount_required"] and plan.row(e).counterpart_entry_id is None
    assert not any(r.counter_leg_for for r in plan.rows)
    with pytest.raises(CommitRefused) as exc:
        scene.commit_draft(
            dataclasses.replace(scene.draft(e, DraftEntry(e, pairing=cl(-1))), versions=plan.versions)
        )
    assert [p.code for p in exc.value.problems] == ["received_amount_required"]
    plan = scene.preview(e, DraftEntry(e, pairing=cl(-1, 1234)))
    assert plan.row(-1).amount == 1234 and plan.row(-1).currency == "USD" and not plan.problems
    real, _ = committed(scene, e, DraftEntry(e, pairing=cl(-1, 1234)))
    assert scene.row(real).amount == 1234 and scene.row(real).counterpart_entry_id == e
    # the leg fixes the sign: an incoming leg receives a negative amount
    inc = leg(scene, 800, scene.checking, counter=scene.usd)
    assert scene.preview(inc, DraftEntry(inc, pairing=cl(-1, 900))).row(-1).amount == -900


def test_a_received_amount_in_one_currency_is_refused(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.cash)
    assert codes(scene.preview(e, DraftEntry(e, pairing=cl(-1, 1000)))) == ["received_amount_not_needed"]


# ---- what is not offered ----------------------------------------------------------------------------------


def test_a_counter_leg_that_is_not_offered_is_refused(scene: Scene) -> None:
    (_sa, (a,)), (_sb, _b) = scene.transfer_pair(-500)
    assert codes(scene.preview(a, DraftEntry(a, pairing=cl()))) == [
        "counter_leg_not_offered"
    ]  # has a partner
    nowhere = leg(scene, -1000, scene.checking)  # no counter-account
    plan = scene.preview(nowhere, DraftEntry(nowhere, pairing=cl()))
    assert codes(plan) == ["counter_leg_not_offered"] and plan.problems[0].entry_id == nowhere
    gbp = leg(scene, -1000, scene.checking, counter=scene.usd, instructed=(-900, "GBP"))
    assert "counter_leg_not_offered" in codes(scene.preview(gbp, DraftEntry(gbp, pairing=cl(-1, 5))))
    flow = leg(scene, -400, scene.checking, counter=scene.cash)
    with pytest.raises(DraftError) as exc:  # only a transfer leg has a partner
        scene.preview(flow, DraftEntry(flow, type=fixed("flow"), pairing=cl()))
    assert exc.value.code == "pairing_not_transfer"


def test_a_proposal_the_plan_cannot_make_is_a_problem_like_a_chosen_counter_leg(scene: Scene) -> None:
    # committing accepts the proposal, so it is refused, never dropped silently
    (_sa, (a,)), (_sb, _b) = scene.transfer_pair(-500)  # has a partner: no counter-leg is offered
    proposal = PairingDraft("counter_leg", is_proposal=True, counter_leg=CounterLegDraft(-1))
    plan = scene.preview(a, DraftEntry(a, pairing=proposal))
    assert codes(plan) == ["counter_leg_not_offered"] and plan.problems[0].entry_id == a


def test_a_closed_counter_account_is_not_offered_after_its_closing(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.cash)
    scene.tx(
        lambda c: c.execute(
            text("UPDATE account SET closed_on = :d WHERE id = :a"),
            {"d": D - timedelta(days=1), "a": scene.cash},
        )
    )
    assert codes(scene.preview(e, DraftEntry(e, pairing=cl()))) == ["counter_leg_not_offered"]
    assert not scene.preview(e).transfers[e].proposed_counter_leg


def test_a_synced_counter_account_takes_no_counter_leg(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.cash)
    scene.sync(scene.cash)
    plan = scene.preview(e, DraftEntry(e, pairing=cl()))
    assert codes(plan) == ["counter_leg_account_synced"] and plan.row(e).counterpart_entry_id is None
    assert scene.preview(e).transfers[e].offers == ()  # nothing offered (I40)
    before = scene.fingerprint()
    with pytest.raises(CommitRefused) as exc:
        scene.commit_draft(scene.draft(e, DraftEntry(e, pairing=cl())))
    assert [p.code for p in exc.value.problems] == ["counter_leg_account_synced"]
    assert scene.fingerprint() == before and counter_legs_of(scene, scene.cash) == []


def test_the_trigger_is_the_net_when_the_account_became_synced_under_the_commit(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.cash)
    draft = scene.draft(e, DraftEntry(e, pairing=cl()))
    real = commit_module.plan_unit

    def late(stored: Any, d: Any, world: Any) -> Any:
        world.account_sync = {**world.account_sync, scene.cash: (False, None)}  # the plan saw it unsynced
        scene.sync(scene.cash)  # and then the account was linked: only the trigger remains
        return real(stored, d, world)

    monkeypatch.setattr(commit_module, "plan_unit", late)
    before = scene.fingerprint()
    with pytest.raises(CommitRefused) as exc:
        scene.commit_draft(draft)
    assert exc.value.problems[0].code == "invariant_violated"
    assert scene.fingerprint()["source_transaction"] == before["source_transaction"]  # nothing written
    assert counter_legs_of(scene, scene.cash) == []


# ---- settling creates nothing -----------------------------------------------------------------------------


def test_a_deleted_counter_leg_is_not_recreated_by_settling(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.cash)
    committed(scene, e)
    (source,) = counter_legs_of(scene, scene.cash)
    probe = delete_source(scene.engine, source.id, dry_run=True)
    done = delete_source(
        scene.engine,
        source.id,
        expected_versions={r.id: r.version for r in (*probe.removed, *probe.partners)},
    )
    assert done.settle is not None and counter_legs_of(scene, scene.cash) == []
    assert scene.row(e).counterpart_entry_id is None
    assert scene.settle().touched_entry_ids == () and counter_legs_of(scene, scene.cash) == []
    # a REVIEW proposes it again: that is the user's to take or to leave
    assert scene.preview(e).transfers[e].proposed_counter_leg


def test_settling_alone_never_creates_one(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.cash)
    scene.settle()
    assert counter_legs_of(scene, scene.cash) == [] and scene.row(e).counterpart_entry_id is None


# ---- following the partner --------------------------------------------------------------------------------


def with_counter_leg(scene: Scene, amount: int = -1000) -> tuple[int, int]:
    """A leg on checking, user-authored, with the counter-leg a commit created on the cash account."""
    set_manual_record_on(scene, scene.cash, 10_000)
    e = leg(scene, amount, scene.checking, counter=scene.cash)
    real, _ = committed(scene, e)
    return e, real


def test_a_split_of_the_leg_makes_the_counter_leg_follow_the_residual(scene: Scene) -> None:
    e, c = with_counter_leg(scene)
    before = scene.row(c)
    split = DraftEntry(-1, amount=-100, source_entry_id=e)
    plan = scene.preview(e, split)
    assert not plan.problems
    assert plan.row(e).amount == -900 and plan.row(c).amount == 900 and plan.row(c).stored is not None
    assert (c, "changed") in {(x.entry_id, x.kind) for x in plan.consequences}
    assert plan.versions[c] == before.version and c in plan.versions
    assert plan.row(c).derivation == dict(before.derivation)  # keys stay: following is no input
    assert plan.row(c).counterpart_entry_id == e and plan.row(e).counterpart_entry_id == c
    assert dict(plan.followed_sources) == {plan.row(c).source_transaction_id: 900}
    plan, result = preview_then_commit(scene, scene.draft(e, split))
    assert scene.row(c).amount == 900 and scene.row(c).version > before.version
    (source,) = counter_legs_of(scene, scene.cash)
    assert source.amount == 900 and source.raw["counter_leg_for"] == e
    assert scene.row(e).amount == -900 and scene.row(c).counterpart_entry_id == e
    assert dict(scene.row(c).derivation) == dict(before.derivation)
    opening = scene.q(
        "SELECT amount FROM ledger_entry WHERE type = 'opening' AND account_id = :a", a=scene.cash
    )
    assert [r.amount for r in opening] == [9_100]  # the account's derived entries follow
    assert (c, "changed") in {(x.entry_id, x.kind) for x in result.consequences}


def test_the_follower_is_part_of_the_versions_a_commit_must_carry(scene: Scene) -> None:
    e, c = with_counter_leg(scene)
    draft = UnitDraft(e, [DraftEntry(-1, amount=-100, source_entry_id=e)], versions={e: scene.row(e).version})
    with pytest.raises(VersionConflict) as exc:
        scene.commit_draft(draft)
    assert c in exc.value.entry_ids and scene.row(c).amount == 1000
    moved = scene.draft(e, DraftEntry(-1, amount=-100, source_entry_id=e))
    scene.commit_draft(UnitDraft(c, [DraftEntry(c, note="elsewhere")], versions=scene.versions(c)))
    with pytest.raises(VersionConflict) as exc:
        scene.commit_draft(moved)
    assert c in exc.value.entry_ids


def test_removing_the_split_makes_it_follow_back(scene: Scene) -> None:
    e, c = with_counter_leg(scene)
    scene.commit(e, DraftEntry(-1, amount=-100, source_entry_id=e))
    (split_id,) = [i for i in scene.unit_ids(e) if i not in (e, c)]
    assert scene.row(c).amount == 900
    plan, _ = preview_then_commit(scene, scene.draft(e, removed_entry_ids=[split_id]))
    assert scene.row(e).amount == -1000 and scene.row(c).amount == 1000
    assert plan.row(c).amount == 1000


def test_a_partner_that_is_not_a_follower_keeps_the_unequal_pair_refused(scene: Scene) -> None:
    e, c = with_counter_leg(scene)
    scene.sync(scene.cash)  # the counter-leg's account is synced since: it keeps what it has (spec §5.7)
    plan = scene.preview(e, DraftEntry(-1, amount=-100, source_entry_id=e))
    assert codes(plan) == ["pair_unequal"] and plan.row(c).amount == 1000
    with pytest.raises(CommitRefused):
        scene.commit_draft(
            dataclasses.replace(
                scene.draft(e, DraftEntry(-1, amount=-100, source_entry_id=e)), versions=plan.versions
            )
        )
    assert scene.row(c).amount == 1000 and scene.row(e).amount == -1000


def test_a_multi_entry_follower_and_a_cross_currency_pair_do_not_follow(scene: Scene) -> None:
    # a user-authored partner of two entries (a split) cannot follow
    e = leg(scene, -600, scene.checking, counter=scene.cash)
    _s, (p1, _p2) = scene.movement(
        600,
        400,
        account=scene.cash,
        authored=True,
        lead={"type": "transfer", "derivation": USER_TYPE},
        type="flow",
    )
    scene.pair_up(e, p1)
    plan = scene.preview(e, DraftEntry(-1, amount=-100, source_entry_id=e))
    assert "pair_unequal" in codes(plan)
    # cross-currency: the unequal amounts are the point, nothing follows and nothing is unequal
    x = leg(scene, -1000, scene.checking, counter=scene.usd, instructed=(-1100, "USD"))
    _s, (u,) = scene.movement(
        1100, account=scene.usd, currency="USD", authored=True, type="transfer", derivation=USER_TYPE
    )
    scene.pair_up(x, u)
    plan = scene.preview(x, DraftEntry(-1, amount=-100, source_entry_id=x))
    assert codes(plan) == [] and plan.row(u).amount == 1100 and dict(plan.followed_sources) == {}


def test_a_leg_that_picks_a_new_partner_is_not_followed_by_the_old_one(scene: Scene) -> None:
    e, c = with_counter_leg(scene)
    x = leg(scene, 800, scene.cash, on=D + timedelta(days=1))
    plan = scene.preview(
        e, DraftEntry(e, pairing=PairingDraft("pick", x)), DraftEntry(-1, amount=-200, source_entry_id=e)
    )
    assert plan.row(c).amount == 1000 and dict(plan.followed_sources) == {}
    assert plan.row(e).counterpart_entry_id == x and not plan.problems


# ---- the entry form follows too ---------------------------------------------------------------------------


def edit(scene: Scene, source_id: int, **kw: Any) -> Any:
    probe = update_source(scene.engine, source_id, dry_run=True, **kw)
    return update_source(scene.engine, source_id, expected_versions=dict(probe.effects.versions), **kw)


def test_an_entry_form_edit_of_the_leg_keeps_the_pair_and_the_counter_leg_follows(scene: Scene) -> None:
    e, c = with_counter_leg(scene)
    source = scene.row(e).source_transaction_id
    probe = update_source(scene.engine, source, amount=-800, dry_run=True)
    assert probe.effects.followed_entry_ids == (c,) and probe.effects.unpaired_entry_ids == ()
    assert c in dict(probe.effects.versions)
    before = scene.row(c)
    done = edit(scene, source, amount=-800)
    assert done.effects.followed_entry_ids == (c,) and done.effects.unpaired_entry_ids == ()
    assert scene.row(e).amount == -800 and scene.row(c).amount == 800
    assert scene.row(e).counterpart_entry_id == c and scene.row(c).counterpart_entry_id == e
    assert dict(scene.row(c).derivation) == dict(before.derivation)
    (cl_source,) = counter_legs_of(scene, scene.cash)
    assert cl_source.amount == 800
    opening = scene.q(
        "SELECT amount FROM ledger_entry WHERE type = 'opening' AND account_id = :a", a=scene.cash
    )
    assert [r.amount for r in opening] == [9_200]
    assert scene.settle().touched_entry_ids == ()
    scene.assert_checks_clean()
    assert c in {x.id for x in done.units.entries}


def test_an_edit_of_the_counter_leg_is_followed_by_the_leg(scene: Scene) -> None:
    e, c = with_counter_leg(scene)
    (source,) = counter_legs_of(scene, scene.cash)
    done = edit(scene, source.id, amount=700)
    assert done.effects.followed_entry_ids == (e,) and done.effects.unpaired_entry_ids == ()
    assert scene.row(c).amount == 700 and scene.row(e).amount == -700
    scene.assert_checks_clean()


def test_an_edit_that_flips_the_sign_or_a_since_synced_follower_breaks_the_pair_as_before(
    scene: Scene,
) -> None:
    e, c = with_counter_leg(scene)
    source = scene.row(e).source_transaction_id
    probe = update_source(scene.engine, source, amount=900, dry_run=True)  # a changed sign breaks any pair
    assert probe.effects.followed_entry_ids == () and set(probe.effects.unpaired_entry_ids) == {e, c}
    scene.sync(scene.cash)
    probe = update_source(scene.engine, source, amount=-900, dry_run=True)
    assert probe.effects.followed_entry_ids == () and set(probe.effects.unpaired_entry_ids) == {e, c}
    done = edit(scene, source, amount=-900)
    assert scene.row(e).counterpart_entry_id is None and scene.row(c).amount == 1000
    assert done.effects.followed_entry_ids == ()


# ---- a confirmed unit -------------------------------------------------------------------------------------


def test_a_counter_leg_for_a_leg_of_a_confirmed_unit_is_the_users_operation(scene: Scene) -> None:
    (_sa, (a,)), (_sb, (b,)) = scene.transfer_pair(-1000)
    assert scene.preview(a).anchor_unit.state.confirmed
    # the leg is sent to the cash account: the pair breaks, the cash account gets the counter-leg
    draft = [DraftEntry(a, counter_account=fixed(scene.cash), pairing=cl(-4))]
    plan = scene.preview(a, *draft)
    assert not plan.problems and plan.row(a).counterpart_entry_id == -4
    assert {"left_behind", "returns_to_review"} <= kinds(plan, b)
    assert (-4, "created") in {(c.entry_id, c.kind) for c in plan.consequences}
    assert "changed" in kinds(plan, a) and plan.anchor_unit.state.confirmed
    assert set(plan.versions) == {a, b}
    _p, result = preview_then_commit(scene, scene.draft(a, *draft))
    real = result.created[-4]
    assert scene.row(b).counterpart_entry_id is None and scene.row(a).counterpart_entry_id == real
    assert (b, "left_behind") in {(c.entry_id, c.kind) for c in result.consequences}
    assert scene.row(a).counter_account_id == scene.cash


# ---- locks, moved units, retries ---------------------------------------------------------------------------


def test_a_commit_locks_the_counter_legs_account_ascending_with_the_units(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.cash)
    taken: list[list[int]] = []
    real = commit_module.lock_accounts
    monkeypatch.setattr(
        commit_module, "lock_accounts", lambda conn, ids: taken.append(list(ids)) or real(conn, ids)
    )
    scene.commit(e)
    assert len(taken) == 1 and sorted(set(taken[0])) == sorted({scene.checking, scene.cash})


def test_the_commit_waits_for_the_counter_legs_account(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.cash)
    draft = scene.draft(e)
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
        locks.lock_accounts(holder, [scene.cash])  # the counter-leg's account: no entry of the unit is on it
        t = threading.Thread(target=run)
        t.start()
        lockwatch.wait_until_waiting(scene.engine, "the commit to wait for the counter-leg's account")
        assert not done.is_set()
        holder.rollback()
    t.join(10)
    assert done.is_set() and not errors and len(counter_legs_of(scene, scene.cash)) == 1


def test_an_account_the_plan_only_found_under_the_locks_extends_the_lock_set(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.cash)
    taken: list[list[int]] = []
    real_lock = commit_module.lock_accounts
    monkeypatch.setattr(
        commit_module, "lock_accounts", lambda conn, ids: taken.append(sorted(ids)) or real_lock(conn, ids)
    )
    real = commit_module.counter_leg_accounts
    calls: list[int] = []

    def blind(plan: Plan) -> set[int]:  # the first look (before the locks) saw no counter-leg
        calls.append(1)
        return set() if len(calls) == 1 else real(plan)

    monkeypatch.setattr(commit_module, "counter_leg_accounts", blind)
    scene.commit(e)
    assert len(taken) == 2 and scene.cash not in taken[0] and scene.cash in taken[1]
    assert len(counter_legs_of(scene, scene.cash)) == 1


def test_a_closure_that_moved_under_the_locks_is_unit_moved(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.cash)
    x = leg(scene, 1000, scene.savings, counter=scene.checking)
    draft = scene.draft(e)
    real = commit_module._read_drafted_closure
    calls: list[int] = []

    def stale(conn: Any, d: Any) -> tuple[int, ...] | None:
        calls.append(1)
        found = real(conn, d)
        return (*found, x) if len(calls) == 1 and found else found

    monkeypatch.setattr(commit_module, "_read_drafted_closure", stale)
    with pytest.raises(UnitMoved):
        scene.commit_draft(draft)
    assert counter_legs_of(scene, scene.cash) == []


def test_a_stale_version_of_the_leg_is_a_conflict_and_creates_nothing(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.cash)
    draft = scene.draft(e, DraftEntry(e, pairing=cl()))
    scene.commit_draft(UnitDraft(e, [DraftEntry(e, note="moved")], versions=scene.versions(e)))
    with pytest.raises(VersionConflict) as exc:
        scene.commit_draft(draft)
    assert e in exc.value.entry_ids
    # the commit above took the proposal: the counter-leg exists once, never twice
    assert len(counter_legs_of(scene, scene.cash)) == 1


def test_a_commit_twice_creates_it_once(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.cash)
    scene.commit(e)
    scene.commit(e)  # the unit now holds the pair: nothing more is proposed
    assert len(counter_legs_of(scene, scene.cash)) == 1
    assert preview_unit(scene.engine, scene.draft(e)).transfers[e].proposal is None
