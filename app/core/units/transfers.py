"""What the preview says of each transfer leg of a plan (spec §5.7): its state, its partner and its offers.

Pure. `attach_transfers` runs after the plan (the walk and the simulation of settling): the pool offers are
made of is read for the legs the plan ended with, and the plan's own rows count in it as planned, not as
stored (a leg the draft has just freed is an unpaired leg, not the stored pair). Offers are computed, never
stored, and a proposal is only a preselection of the preview.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

from app.core.matching import OfferWorld, PoolEntry, Summary, offers
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


def transfer_views(plan: Plan, world: World, window: int) -> dict[int, TransferView]:
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
        )
    return views


def attach_transfers(plan: Plan, world: World, window: int) -> Plan:
    """The plan with the transfer view of each of its transfer rows."""
    return dataclasses.replace(plan, transfers=transfer_views(plan, world, window))
