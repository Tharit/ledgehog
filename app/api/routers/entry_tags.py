"""Tag or untag one entry (spec §3.7, architecture §4.1).

Idempotent: a repeat answers 200 with `changed: false`. A derived entry takes no tags (409,
reason `derived_entry`). Tags move no version, so no `expected_versions`. The error mapping for
the tag errors lives in `app.api.routers.tags`.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.ids import PathId
from app.api.routers import tags as _tags  # noqa: F401  (registers the tag error mapping)
from app.api.routers.maintenance import SettleOut
from app.api.routers.tags import EntryTagIdsOut
from app.api.session import CurrentUser, EngineDep
from app.core.ledger.tags import EntryTagged, tag_entry, untag_entry

router = APIRouter(prefix="/api/ledger/entries/{entry_id}/tags", tags=["tags"])


class EntryTagsOut(BaseModel):
    entry: EntryTagIdsOut
    changed: bool  # False when the tag was already there (put) or was not there (delete)
    settle: SettleOut

    @classmethod
    def of(cls, result: EntryTagged) -> EntryTagsOut:
        return cls(
            entry=EntryTagIdsOut(id=result.entry_id, tag_ids=list(result.tag_ids)),
            changed=result.changed,
            settle=SettleOut.of(result.settle),
        )


@router.put("/{tag_id}")
def tag_ledger_entry(entry_id: PathId, tag_id: PathId, user: CurrentUser, engine: EngineDep) -> EntryTagsOut:
    return EntryTagsOut.of(tag_entry(engine, entry_id, tag_id))


@router.delete("/{tag_id}")
def untag_ledger_entry(
    entry_id: PathId, tag_id: PathId, user: CurrentUser, engine: EngineDep
) -> EntryTagsOut:
    return EntryTagsOut.of(untag_entry(engine, entry_id, tag_id))
