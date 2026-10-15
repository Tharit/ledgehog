"""`preview` (architecture §4.1, §6.3): the stored unit with a draft laid over it, in memory; writes nothing.

One read-only transaction loads the closure of the anchor and the world around it (accounts, the rules, the
history snapshot, every unpaired transfer leg of the ledger) and `overlay.plan_unit` does the rest. The
simulation of settling pairs the unit's legs with legs outside it as settling will; a leg it takes a row to
brings its unit into the closure, and the plan is made again (a consequence of the draft, shown read-only).
Then the pool the offers are made of is read, AFTER the plan, around the legs it ends with. Every call
resolves fresh: a unit is previewed "fresh when it is opened" (spec §6).
"""

from __future__ import annotations

from sqlalchemy import Engine, text

from app.core.stale import StaleReference
from app.core.units.draft import UnitDraft
from app.core.units.overlay import plan_unit
from app.core.units.plan import Plan
from app.core.units.stored import (
    load_closure_of,
    load_pool,
    load_stored_entries,
    load_stored_unit,
    load_world,
    missing_tag,
)
from app.core.units.transfers import attach_transfers

MAX_PULLS = 10  # the closure grows by a unit per leg pulled in; a plan that keeps pulling is a bug


class UnitNotFound(LookupError):
    def __init__(self, entry_id: int) -> None:
        self.entry_id = entry_id
        super().__init__(f"entry {entry_id} is in no unit (it does not exist, or it is derived)")


def preview_unit(engine: Engine, draft: UnitDraft, *, window_days: int | None = None) -> Plan:
    """`window_days` is the window offers are shown for (spec §5.7: a pick may widen it, to at most 90);
    the default is the matching window. Pairing itself always keeps the matching window."""
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        stored = load_stored_unit(conn, draft.anchor_entry_id)
        if stored is None:
            raise UnitNotFound(draft.anchor_entry_id)
        world = load_world(conn, stored, draft, ledger_wide=True)
        plan = plan_unit(stored, draft, world)
        for _ in range(MAX_PULLS):
            if not plan.pulled_entry_ids:
                break
            ids = {e.id for e in stored.entries} | load_closure_of(conn, plan.pulled_entry_ids)
            stored = load_stored_entries(conn, draft.anchor_entry_id, ids)
            plan = plan_unit(stored, draft, world)
        else:
            raise RuntimeError("the preview kept pulling units in")
        legs = [r.leg for r in plan.rows if r.leg is not None and r.leg.type == "transfer"]
        world.pool = load_pool(conn, legs, {r.id for r in plan.rows if r.id > 0})
        missing = missing_tag(conn, draft)
    plan = attach_transfers(plan, world, world.matching_window if window_days is None else window_days)
    if missing is not None:  # after the plan: a draft that makes no sense is the 422 first
        raise StaleReference(f"entries[{missing[0]}].tags.add", "tag", missing[1])
    return plan
