"""`preview` (architecture §4.1, §6.3): the stored unit with a draft laid over it, in memory; writes nothing.

One read-only transaction loads the closure of the anchor and the world around it (accounts, the rules, the
history snapshot) and `overlay.plan_unit` does the rest. Every call resolves fresh: a unit is previewed
"fresh when it is opened" (spec §6).
"""

from __future__ import annotations

from sqlalchemy import Engine, text

from app.core.stale import StaleReference
from app.core.units.draft import UnitDraft
from app.core.units.overlay import plan_unit
from app.core.units.plan import Plan
from app.core.units.stored import load_stored_unit, load_world, missing_tag


class UnitNotFound(LookupError):
    def __init__(self, entry_id: int) -> None:
        self.entry_id = entry_id
        super().__init__(f"entry {entry_id} is in no unit (it does not exist, or it is derived)")


def preview_unit(engine: Engine, draft: UnitDraft) -> Plan:
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        stored = load_stored_unit(conn, draft.anchor_entry_id)
        if stored is None:
            raise UnitNotFound(draft.anchor_entry_id)
        world = load_world(conn, stored, draft)
        missing = missing_tag(conn, draft)
    plan = plan_unit(stored, draft, world)
    if missing is not None:  # after the plan: a draft that makes no sense is the 422 first
        raise StaleReference(f"entries[{missing[0]}].tags.add", "tag", missing[1])
    return plan
