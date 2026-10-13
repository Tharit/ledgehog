"""Units (architecture §4.1, spec §6): `GET /api/units/{entry_id}` and the review queue.

A unit is the entries of one source transaction plus the other leg of a paired transfer (and that leg's
source transaction), reviewed and committed together. Reads only: no lock, no write, no settle.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.errors import ApiError, map_error
from app.api.ids import PathId
from app.api.routers.entries import EntryOut
from app.api.session import CurrentUser, EngineDep
from app.core.units.read import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    InvalidCursor,
    QueueSection,
    UnitView,
    new_unit_count,
    review_queue,
)
from app.core.units.read import get_unit as read_unit
from app.core.units.state import UnitState

router = APIRouter(prefix="/api/units", tags=["units"])

# a 422 in the same shape as a pydantic validation problem, located at the query parameter
map_error(
    InvalidCursor,
    422,
    "validation_error",
    details=lambda e: [{"location": ["query", e.parameter], "message": str(e), "type": "invalid_token"}],
)

UnitReason = Literal["incomplete", "unpaired_transfer", "non_standing_keys"]
SectionKind = Literal["pending_review", "needs_account", "waiting"]
Token = Annotated[str, Query(min_length=1, max_length=200)]


class UnitStateOut(BaseModel):
    confirmed: bool
    reasons: list[UnitReason]  # why not; empty when confirmed

    @staticmethod
    def of(state: UnitState) -> UnitStateOut:
        return UnitStateOut(confirmed=state.confirmed, reasons=list(state.reasons))


class UnitOut(BaseModel):
    anchor_entry_id: int  # the lowest entry id of the unit: what opens it (`?unit=`)
    unit_key: int
    state: UnitStateOut
    entries: list[EntryOut]  # ascending by id

    @staticmethod
    def of(view: UnitView) -> UnitOut:
        return UnitOut(
            anchor_entry_id=view.anchor_entry_id,
            unit_key=view.unit_key,
            state=UnitStateOut.of(view.state),
            entries=[EntryOut.of(e) for e in view.entries],
        )


class QueueSectionOut(BaseModel):
    kind: SectionKind
    total: int  # units in the section, whatever the page
    units: list[UnitOut]  # by the anchor's booked_on, then anchor id
    next_cursor: str | None

    @staticmethod
    def of(section: QueueSection) -> QueueSectionOut:
        return QueueSectionOut(
            kind=section.kind,
            total=section.total,
            units=[UnitOut.of(u) for u in section.units],
            next_cursor=section.next_cursor,
        )


class ReviewQueueOut(BaseModel):
    sections: list[QueueSectionOut]
    total: int  # units in all sections
    snapshot: str  # opaque: pass to /queue/new-count


class NewCountOut(BaseModel):
    new_count: int  # units that arrived in the queue since the snapshot
    snapshot: str  # a fresh one


@router.get("/queue")
def get_review_queue(
    user: CurrentUser,
    engine: EngineDep,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    section: SectionKind | None = None,
    cursor: Token | None = None,
) -> ReviewQueueOut:
    """The review queue: the first page of each section, or the page after `cursor` of one `section`."""
    if cursor is not None and section is None:
        raise ApiError(
            422,
            "validation_error",
            "A cursor continues one section: name it.",
            [{"location": ["query", "section"], "message": "required with cursor", "type": "missing"}],
        )
    with engine.connect() as conn:
        queue = review_queue(conn, limit=limit, section=section, cursor=cursor)
    return ReviewQueueOut(
        sections=[QueueSectionOut.of(s) for s in queue.sections], total=queue.total, snapshot=queue.snapshot
    )


@router.get("/queue/new-count")
def get_new_unit_count(user: CurrentUser, engine: EngineDep, since: Token) -> NewCountOut:
    """How many units entered the queue since `since` (a `snapshot` of the queue): one cheap pass."""
    with engine.connect() as conn:
        count, snapshot = new_unit_count(conn, since)
    return NewCountOut(new_count=count, snapshot=snapshot)


class UnitMissing(LookupError):
    def __init__(self, entry_id: int) -> None:
        self.entry_id = entry_id
        super().__init__(f"entry {entry_id} is in no unit (it does not exist, or it is derived)")


map_error(UnitMissing, 404, "not_found")


@router.get("/{entry_id}")
def get_unit(entry_id: PathId, user: CurrentUser, engine: EngineDep) -> UnitOut:
    """The unit holding the entry, as stored: its state and every entry with its derivation."""
    with engine.connect() as conn:
        view = read_unit(conn, entry_id)
    if view is None:
        raise UnitMissing(entry_id)
    return UnitOut.of(view)
