"""The preview of transfer legs (spec §5.7): states, offers, proposals, and the simulation of settling
that pairs a leg of the unit with a leg outside it. Nothing is written by a preview; the preview equals
commit plus settle."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from app.core.units.plan import Plan, TransferView
from tests.core.units.equality import preview_then_commit
from tests.core.units.scene import D, DraftEntry, Scene, fixed
from tests.invariants.helpers import link_account, make_instance

USER_TYPE = json.dumps({"type": {"pass": "user"}})
USER_BOTH = json.dumps({"type": {"pass": "user"}, "counter_account": {"pass": "user"}})


def leg(
    scene: Scene,
    amount: int,
    account: int,
    *,
    on: date = D,
    counter: int | None = None,
    **kw: Any,
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


def sync(scene: Scene, account: int) -> None:
    def go(c: Any) -> None:
        link_account(c, account, make_instance(c))

    scene.tx(go)


def view(plan: Plan, entry_id: int) -> TransferView:
    return plan.transfers[entry_id]


# ---- states --------------------------------------------------------------------------------------


def test_flows_and_untyped_rows_carry_no_transfer_view(scene: Scene) -> None:
    _s, (flow,) = scene.movement(-500, type="flow", derivation=USER_TYPE)
    _s, (untyped,) = scene.movement(-400)
    assert scene.preview(flow).transfers == {} and scene.preview(untyped).transfers == {}


def test_an_unpaired_leg_on_an_unsynced_account_is_unmatched(scene: Scene) -> None:
    # a counter-leg with no amount to create it with (cross-currency, none instructed) is offered, not taken
    e = leg(scene, -1000, scene.checking, counter=scene.usd)
    plan = scene.preview(e)
    t = view(plan, e)
    assert (t.state, t.waiting_for, t.needs_account, t.partner) == ("unmatched", None, None, None)
    assert t.proposal is not None and t.proposal.kind == "counter_leg" and not t.proposed_counter_leg
    assert plan.anchor_unit.state.reasons == ("unmatched_transfer",)
    assert "unmatched_transfer" in plan.row(e).flags


def test_an_unpaired_leg_whose_counter_account_is_synced_waits_for_it(scene: Scene) -> None:
    sync(scene, scene.savings)
    e = leg(scene, -1000, scene.checking, counter=scene.savings)
    plan = scene.preview(e)
    t = view(plan, e)
    assert t.state == "waiting" and t.waiting_for is not None
    assert (t.waiting_for.account_id, t.waiting_for.synced_through) == (scene.savings, None)
    assert plan.anchor_unit.state.reasons == ("waiting_for_partner",)
    assert "waiting" in plan.row(e).flags
    assert [o.kind for o in t.offers] == []  # a synced account: no counter-leg (I40)


def test_a_leg_that_needs_an_account_says_in_which_currency(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, instructed=(-1100, "GBP"))
    t = view(scene.preview(e), e)
    assert t.state == "needs_account" and t.needs_account == "GBP" and t.partner is None


def test_a_leg_without_counter_account_and_instructed_currency_is_unmatched(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking)
    assert view(scene.preview(e), e).state == "unmatched"


def test_an_existing_account_in_the_currency_means_it_does_not_need_one(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, instructed=(-1100, "USD"))
    t = view(scene.preview(e), e)
    assert t.state == "unmatched" and t.needs_account is None


# ---- offers ------------------------------------------------------------------------------------------


def test_offers_of_a_leg_without_counter_account_in_their_groups(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking)
    _s, (untyped,) = scene.movement(1000, account=scene.savings, on=D + timedelta(days=1), authored=True)
    other = leg(scene, 900, scene.cash)
    (_sa, (pair_a,)), (_sb, (pair_b,)) = scene.transfer_pair(-1000)  # a pair elsewhere
    t = view(scene.preview(e), e)
    kinds = [(o.kind, o.entry_id) for o in t.offers]
    assert kinds == [("untyped_entry", untyped), ("open_leg", other), ("paired_elsewhere", pair_b)]
    first, second, third = t.offers
    assert first.exact and first.proposed and first.effect.types_as_transfer
    assert not second.exact and not second.proposed and second.effect.fee is not None
    assert (second.effect.fee.larger_entry_id, second.effect.fee.difference) == (e, 100)
    assert third.paired_with is not None and third.paired_with.entry_id == pair_a
    assert third.effect.breaks_pair_with == (pair_a,) and not third.proposed
    assert t.proposal is not None and (t.proposal.kind, t.proposal.entry_id) == ("entry", untyped)
    assert not t.has_more


def test_the_counter_leg_is_proposed_where_there_is_no_open_offer(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.cash)
    t = view(scene.preview(e), e)
    (offer,) = t.offers
    assert offer.kind == "counter_leg" and offer.proposed and offer.entry_id is None
    assert offer.counter_leg is not None and (offer.counter_leg.amount, offer.counter_leg.booked_on) == (
        1000,
        D,
    )
    assert t.proposal is not None and (t.proposal.kind, t.proposal.entry_id) == ("counter_leg", None)


def test_a_cross_currency_counter_leg_needs_the_amount_received_unless_instructed(scene: Scene) -> None:
    plain = leg(scene, -1000, scene.checking, counter=scene.usd)
    (offer,) = view(scene.preview(plain), plain).offers
    assert offer.amount is None and offer.counter_leg is not None and offer.counter_leg.needs_received_amount
    instructed = leg(scene, -2000, scene.checking, counter=scene.usd, instructed=(-2200, "USD"))
    (offer,) = view(scene.preview(instructed), instructed).offers
    assert offer.counter_leg is not None and offer.counter_leg.amount == 2200
    assert not offer.counter_leg.needs_received_amount and offer.currency == "USD"


def test_open_offers_of_another_amount_propose_nothing(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.cash)
    near = leg(
        scene, 900, scene.cash, counter=scene.checking
    )  # wants this account: not paired, no exact amount
    t = view(scene.preview(e), e)
    assert [(o.kind, o.entry_id) for o in t.offers] == [("open_leg", near), ("counter_leg", None)]
    assert t.proposal is None


def test_window_days_widens_the_offers_and_has_more_says_when_there_are_more(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.savings)
    far = leg(scene, 1000, scene.savings, on=D + timedelta(days=20), counter=scene.cash)  # wants the cash
    far2 = leg(scene, 1000, scene.savings, on=D + timedelta(days=20))
    narrow = scene.preview(e)
    assert far2 not in {o.entry_id for o in view(narrow, e).offers} and view(narrow, e).has_more
    wide = preview_with(scene, e, 30)
    assert far2 in {o.entry_id for o in view(wide, e).offers} and not view(wide, e).has_more
    assert far not in {o.entry_id for o in view(wide, e).offers}  # it wants another account


def preview_with(scene: Scene, anchor: int, window_days: int) -> Plan:
    from app.core.units.preview import preview_unit

    return preview_unit(scene.engine, scene.draft(anchor), window_days=window_days)


def test_a_paired_leg_gets_offers_but_no_proposal(scene: Scene) -> None:
    (_sa, (a,)), (_sb, (b,)) = scene.transfer_pair(-1000)
    spare = leg(scene, 1000, scene.savings, on=D + timedelta(days=1))
    plan = scene.preview(a)
    t = view(plan, a)
    assert t.state == "paired" and t.partner is not None and t.partner.entry_id == b
    assert [(o.kind, o.entry_id) for o in t.offers] == [("open_leg", spare)]
    assert t.proposal is None and not t.offers[0].proposed and t.offers[0].exact
    assert t.offers[0].effect.breaks_pair_with == (b,)
    assert view(plan, b).state == "paired"


def test_a_leg_the_draft_frees_is_offered_as_planned_not_as_stored(scene: Scene) -> None:
    (_sa, (a,)), (_sb, (b,)) = scene.transfer_pair(-1000)
    other = leg(scene, -1000, scene.checking)
    scene.sync(scene.cash)  # a synced counter-account has no counter-leg to pair `a` with
    # the draft sends `a` to the cash account: the pair breaks and `b` is an unpaired leg again
    plan = scene.preview(a, DraftEntry(a, counter_account=fixed(scene.cash)))
    assert not plan.problems or all(p.code != "pair_unequal" for p in plan.problems)
    t = view(plan, b)
    assert t.state == "unmatched" and t.partner is None
    by_id = {o.entry_id: o for o in t.offers}
    assert other in by_id  # a spare leg on checking
    assert a not in by_id  # `a` is a leg of the plan that wants the cash account, not the stored pair
    assert all(o.kind != "paired_elsewhere" for o in t.offers)


# ---- the simulation of settling is ledger-wide ---------------------------------------------------------


def test_settling_would_pair_a_leg_with_one_outside_the_unit_and_the_preview_says_so(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.savings)
    x = leg(scene, 1000, scene.savings, on=D + timedelta(days=2))  # another unit, no counter-account
    plan = scene.preview(e)
    assert x in {r.id for r in plan.rows} and plan.versions[x] == 1
    assert plan.row(e).counterpart_entry_id == x and plan.row(x).counterpart_entry_id == e
    assert plan.row(x).in_unit and plan.row(e).in_unit
    assert view(plan, e).state == "paired" and view(plan, x).partner is not None
    assert x in {c.entry_id for c in plan.consequences if c.kind == "changed"}
    # the pair set x's counter-account as its own and the key says so
    assert plan.row(x).fields["counter_account"].value == scene.checking
    assert plan.row(x).derivation["counter_account"] == {
        "pass": "matcher_decision",
        "basis": {"from": "counterpart"},
    }
    assert plan.anchor_unit.state.confirmed
    plan2, _ = preview_then_commit(scene, scene.draft(e))
    assert {r.id for r in plan2.rows} == {e, x}


def test_a_leg_outside_the_window_or_with_another_counter_account_is_not_pulled_in(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.savings)
    leg(scene, 1000, scene.savings, on=D + timedelta(days=60))
    leg(scene, 1000, scene.savings, counter=scene.cash)
    scene.sync(scene.savings)  # no open offer at all on an unsynced account would propose a counter-leg
    plan = scene.preview(e)
    assert {r.id for r in plan.rows} == {e} and set(plan.versions) == {e}


def test_the_draft_decides_the_pairing_the_preview_simulates(scene: Scene) -> None:
    """A draft that gives the counter-account is the user's decision: it pairs with an outside leg."""
    e = leg(scene, -1000, scene.checking)
    x = leg(scene, 1000, scene.savings)
    # neither knows its counter-account (I33): settling would not pair them, but the exact open offer is the
    # proposal, which the preview takes as the pick (a commit accepts it)
    assert scene.preview(e).transfers[e].proposed_pick == x
    draft = scene.draft(e, DraftEntry(e, counter_account=fixed(scene.savings)))
    plan = preview_then_commit(scene, draft)[0]
    assert {r.id for r in plan.rows} == {e, x}


def test_a_preview_writes_nothing_with_offers_and_pulled_units(scene: Scene) -> None:
    e = leg(scene, -1000, scene.checking, counter=scene.savings)
    leg(scene, 1000, scene.savings)
    leg(scene, 700, scene.savings)
    before = scene.fingerprint()
    scene.preview(e)
    assert scene.fingerprint() == before


def test_a_commit_of_a_draft_without_a_pull_is_unchanged(scene: Scene) -> None:
    """The commit's world holds no ledger legs: settling follows the commit, as before."""
    e = leg(scene, -1000, scene.checking, counter=scene.savings)
    x = leg(scene, 1000, scene.savings)
    result = scene.commit(e)
    assert x in {r.id for r in result.entries}
    assert scene.row(e).counterpart_entry_id == x  # settled right after the commit
