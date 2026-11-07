"""`preview` (architecture §4.1, §6.3): the stored unit with a draft laid over it, in memory; writes nothing.

One read-only transaction loads the closure of the anchor and the world around it (accounts, the rules, the
history snapshot, every unpaired transfer leg of the ledger) and `overlay.plan_unit` does the rest. The
simulation of settling pairs the unit's legs with legs outside it as settling will; a leg it takes a row to
brings its unit into the closure, and the plan is made again (a consequence of the draft, shown read-only).
Then the pool the offers are made of is read, AFTER the plan, around the legs it ends with. Every call
resolves fresh: a unit is previewed "fresh when it is opened" (spec §6).

A partner the draft picks brings its own closure into the unit (`stored.load_drafted_unit`). The proposal of
an unpaired transfer leg (an exact open offer) is taken as the pick it proposes (`resolve_draft`), so the
unit shows the pair and the state it would lead to; a commit takes the same proposals as the user's decisions.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, text

from app.core.ledger.entries import entries_by_ids
from app.core.stale import StaleReference
from app.core.units.draft import DraftError, UnitDraft
from app.core.units.overlay import plan_unit
from app.core.units.plan import Plan, StoredUnit, TransferView, World
from app.core.units.stored import (
    load_closure_of,
    load_drafted_unit,
    load_pool,
    load_stored_entries,
    load_world,
    missing_tag,
)
from app.core.units.transfers import new_proposals, transfer_views, with_picks

MAX_PULLS = 10  # the closure grows by a unit per leg pulled in; a plan that keeps pulling is a bug
MAX_PROPOSAL_ROUNDS = 3  # a proposal taken as a pick changes the unit; the next round may offer another


class UnitNotFound(LookupError):
    def __init__(self, entry_id: int) -> None:
        self.entry_id = entry_id
        super().__init__(f"entry {entry_id} is in no unit (it does not exist, or it is derived)")


@dataclass(frozen=True, slots=True)
class Resolved:
    """The draft with the proposals it shows taken as picks, and the plan made of it."""

    draft: UnitDraft
    stored: StoredUnit
    world: World
    plan: Plan
    views: Mapping[int, TransferView]
    proposed: Mapping[int, int]  # leg -> the partner its proposal was taken to be


def _plan_pulling(
    conn: Connection, draft: UnitDraft, stored: StoredUnit, world: World
) -> tuple[StoredUnit, Plan]:
    plan = plan_unit(stored, draft, world)
    for _ in range(MAX_PULLS):
        if not plan.pulled_entry_ids:
            return stored, plan
        ids = {e.id for e in stored.entries} | load_closure_of(conn, plan.pulled_entry_ids)
        stored = load_stored_entries(conn, draft.anchor_entry_id, ids)
        plan = plan_unit(stored, draft, world)
    raise RuntimeError("the preview kept pulling units in")


def resolve_draft(conn: Connection, draft: UnitDraft, *, seen: Mapping[int, int] | None = None) -> Resolved:
    """Plan `draft` as the preview shows it: the proposals of its legs taken as picks (spec §5.9: every
    proposal shown is accepted), each round planned ledger-wide. `seen` (a commit's versions) limits the
    proposals taken to those whose partner's whole closure the client carries versions for."""
    picks: dict[int, int] = {}
    before: dict[int, TransferView] = {}  # a leg's view as it was before its proposal was taken
    window = draft.window_days
    for round_no in range(MAX_PROPOSAL_ROUNDS):
        loaded = load_drafted_unit(conn, draft)
        if loaded is None:
            raise UnitNotFound(draft.anchor_entry_id)
        stored, base_ids = loaded
        for d in draft.entries:  # a leg is re-paired from the side the panel was opened on (spec §6)
            if d.pairing.mode != "keep" and d.id not in base_ids:
                raise DraftError(
                    "pairing_outside_unit",
                    "only a leg of the unit as opened is re-paired: a partner the draft joined is not",
                    entry_id=d.id,
                    field="pairing",
                )
        world = load_world(conn, stored, draft, ledger_wide=True)
        stored, plan = _plan_pulling(conn, draft, stored, world)
        legs = [r.leg for r in plan.rows if r.leg is not None and r.leg.type == "transfer"]
        world.pool = load_pool(conn, legs, {r.id for r in plan.rows if r.id > 0})
        shown = world.matching_window if window is None else window
        views = transfer_views(plan, world, shown, picks)
        # a leg paired by its proposal still lists the offers it had, the proposal first (the picker's list)
        views = {
            i: dataclasses.replace(
                v, offers=before[i].offers, proposal=before[i].proposal, has_more=before[i].has_more
            )
            if i in before
            else v
            for i, v in views.items()
        }
        carried = seen

        def allowed(partner: int, carried: Mapping[int, int] | None = carried) -> bool:
            return carried is None or load_closure_of(conn, [partner]) <= carried.keys()

        new = new_proposals(plan, views, draft, base_ids, allowed)
        if not new or round_no == MAX_PROPOSAL_ROUNDS - 1:
            return Resolved(draft, stored, world, plan, views, picks)
        picks = {**picks, **new}
        before = {**before, **{i: views[i] for i in new}}
        draft = with_picks(draft, new)
    raise AssertionError("unreachable")


def preview_unit(engine: Engine, draft: UnitDraft, *, window_days: int | None = None) -> Plan:
    """`window_days` is the window offers are shown for and a pick is checked against (spec §5.7: a pick may
    widen it, to at most 90); the default is the matching window. Pairing itself always keeps the matching
    window."""
    draft = dataclasses.replace(
        draft, window_days=window_days if window_days is not None else draft.window_days
    )
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        resolved = resolve_draft(conn, draft)
        missing = missing_tag(conn, resolved.draft)
        entries = entries_by_ids(conn, sorted(resolved.plan.versions))
    if missing is not None:  # after the plan: a draft that makes no sense is the 422 first
        raise StaleReference(f"entries[{missing[0]}].tags.add", "tag", missing[1])
    return dataclasses.replace(resolved.plan, transfers=dict(resolved.views), entries=entries)
