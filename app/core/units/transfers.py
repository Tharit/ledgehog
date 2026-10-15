"""What the preview says of each transfer leg of a plan (spec §5.7): its state, its partner and its offers.

Pure. `attach_transfers` runs after the plan (the walk and the simulation of settling): the pool offers are
made of is read for the legs the plan ended with, and the plan's own rows count in it as planned, not as
stored (a leg the draft has just freed is an unpaired leg, not the stored pair). Offers are computed, never
stored. A proposal (an exact open offer) is taken to be the pick it proposes (`new_proposals`, `with_picks`).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Collection, Mapping, Sequence

from app.core.matching import OfferWorld, PoolEntry, Summary, offers
from app.core.units.draft import CounterLegDraft, DraftEntry, PairingDraft, UnitDraft
from app.core.units.plan import (
    PartnerView,
    Plan,
    PlannedRow,
    TransferState,
    TransferView,
    WaitingFor,
    World,
)


def _is_transfer(row: PlannedRow) -> bool:
    return row.leg is not None and row.leg.type == "transfer"


def _needs_account(row: PlannedRow, world: World) -> str | None:
    """The currency a leg needs an account in (spec §5.7): unpaired, no counter-account, an instructed
    currency, and no account other than its own that is open on its date in that currency."""
    leg = row.leg
    if leg is None or row.counterpart_entry_id is not None or leg.counter_account_id is not None:
        return None
    currency = leg.instructed_currency
    if currency is None:
        return None
    for a in world.accounts:
        if (
            a.currency == currency
            and a.id != row.account_id
            and (a.closed_on is None or row.booked_on <= a.closed_on)
        ):
            return None
    return currency


def _summary(row: PlannedRow) -> Summary:
    return Summary(row.id, row.account_id, row.booked_on, row.amount, row.currency, row.description)


def _plan_pool(plan: Plan) -> list[PoolEntry]:
    """The plan's own rows as offers are made of them: their planned state."""
    rows = {r.id: r for r in plan.rows}
    out: list[PoolEntry] = []
    for r in plan.rows:
        leg = r.leg
        if leg is None or not (leg.type == "transfer" or (leg.type is None and r.original)):
            continue
        partner = rows.get(r.counterpart_entry_id) if r.counterpart_entry_id is not None else None
        out.append(PoolEntry(leg, r.original, r.description, None if partner is None else _summary(partner)))
    return out


def transfer_views(
    plan: Plan, world: World, window: int, proposed: Mapping[int, int] | None = None
) -> dict[int, TransferView]:
    """`proposed` maps a leg to the partner its proposal was taken to be (the leg then shows that pair)."""
    rows = {r.id: r for r in plan.rows}
    offer_world = OfferWorld(
        accounts={a.id: a for a in world.accounts},
        synced={account_id: synced for account_id, (synced, _through) in world.account_sync.items()},
    )
    pool: Sequence[PoolEntry] = [*world.pool, *_plan_pool(plan)]
    views: dict[int, TransferView] = {}
    for r in plan.rows:
        if not _is_transfer(r) or r.leg is None:
            continue
        found = offers(
            r.leg,
            pool,
            offer_world,
            window,
            partner_id=r.counterpart_entry_id,
            purpose=r.purpose,
        )
        partner_row = rows.get(r.counterpart_entry_id) if r.counterpart_entry_id is not None else None
        needs = _needs_account(r, world)
        state: TransferState
        waiting_for: WaitingFor | None = None
        if r.counterpart_entry_id is not None:
            state = "paired"
        elif needs is not None:
            state = "needs_account"
        elif "waiting" in r.flags and r.leg.counter_account_id is not None:
            state = "waiting"
            through = world.account_sync.get(r.leg.counter_account_id, (False, None))[1]
            waiting_for = WaitingFor(r.leg.counter_account_id, through)
        else:
            state = "unmatched"
        chosen = (proposed or {}).get(r.id)
        if chosen is not None and r.counterpart_entry_id != chosen:
            chosen = None  # the plan did not make the pair the proposal stood for
        views[r.id] = TransferView(
            state=state,
            waiting_for=waiting_for,
            needs_account=needs,
            partner=None
            if partner_row is None
            else PartnerView(
                partner_row.id,
                partner_row.account_id,
                partner_row.booked_on,
                partner_row.amount,
                partner_row.currency,
                partner_row.description,
            ),
            offers=found.offers,
            proposal=found.proposal,
            has_more=found.has_more,
            proposed_pick=chosen if chosen is not None and chosen > 0 else None,
            proposed_counter_leg=chosen is not None and chosen < 0,
        )
    return views


PROPOSED_TEMP_BASE = 2**52  # the temporary id of a counter-leg the server proposes: -(base + the leg's id)


def proposed_temp_id(leg_id: int) -> int:
    """The temporary id the preview gives the counter-leg it proposes for `leg_id` (stable per leg, and far
    from the small negative ids a client issues)."""
    return -(PROPOSED_TEMP_BASE + leg_id)


def new_proposals(
    plan: Plan,
    views: Mapping[int, TransferView],
    draft: UnitDraft,
    base_ids: Collection[int],
    allowed: Callable[[int], bool] = lambda _partner: True,
) -> dict[int, int]:
    """The proposals the preview takes to be the pairing (spec §5.9: every proposal shown is accepted): for
    each unpaired transfer leg of the unit, stored in its own closure, that the draft does not pick or
    counter-leg for, leg -> partner. An exact open offer outside that closure (kind `entry`) is that
    partner; a counter-leg proposal whose amount is known is a negative temporary id
    (`proposed_temp_id`). `allowed` says whether a partner may be taken (a commit takes only partners whose
    entries the client carries versions for)."""
    out: dict[int, int] = {}
    for r in plan.rows:
        v = views.get(r.id)
        if v is None or r.id not in base_ids or not r.in_unit or r.counterpart_entry_id is not None:
            continue
        if v.proposal is None:
            continue
        d = draft.entry(r.id)
        if d is not None and d.pairing.mode in ("pick", "counter_leg"):
            continue
        if v.proposal.kind == "counter_leg":
            # no amount to create it with (cross-currency, none instructed): the user types it
            offer = next((o for o in v.offers if o.kind == "counter_leg"), None)
            cl = None if offer is None else offer.counter_leg
            if cl is not None and not cl.needs_received_amount:
                out[r.id] = proposed_temp_id(r.id)
            continue
        if v.proposal.entry_id is None:
            continue
        partner = v.proposal.entry_id
        if partner in base_ids or partner in out.values():
            continue
        if allowed(partner):
            out[r.id] = partner
    return out


def with_picks(draft: UnitDraft, picks: Mapping[int, int]) -> UnitDraft:
    """`draft` with each leg of `picks` picking its partner, or creating the counter-leg a negative partner
    stands for, as a proposal (the server's, not a client's)."""

    def pairing(partner: int) -> PairingDraft:
        if partner < 0:
            return PairingDraft("counter_leg", is_proposal=True, counter_leg=CounterLegDraft(partner))
        return PairingDraft("pick", partner, True)

    listed = {e.id for e in draft.entries}
    entries = [
        dataclasses.replace(e, pairing=pairing(picks[e.id])) if e.id in picks else e for e in draft.entries
    ]
    entries += [DraftEntry(i, pairing=pairing(p)) for i, p in picks.items() if i not in listed]
    return dataclasses.replace(draft, entries=entries)


def attach_transfers(
    plan: Plan, world: World, window: int, proposed: Mapping[int, int] | None = None
) -> Plan:
    """The plan with the transfer view of each of its transfer rows."""
    return dataclasses.replace(plan, transfers=transfer_views(plan, world, window, proposed))
