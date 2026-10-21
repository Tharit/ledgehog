"""Units (architecture §4.1, spec §6): `GET /api/units/{entry_id}` and the review queue.

A unit is the entries of one source transaction plus the other leg of a paired transfer (and that leg's
source transaction), reviewed and committed together. Reads only: no lock, no write, no settle.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from app.api.errors import ApiError, map_error
from app.api.ids import PathId
from app.api.routers.changes import model_queue_of
from app.api.routers.entries import EntryOut
from app.api.routers.unit_drafts import (
    UnitCommitOut,
    UnitDraftIn,
    UnitPreviewOut,
    UnitProblemOut,
    UnitStateOut,
)
from app.api.session import CurrentUser, EngineDep
from app.core.matching import MAX_WINDOW as MAX_OFFER_WINDOW
from app.core.units.commit import CommitRefused, UnitMoved
from app.core.units.commit import commit_unit as write_unit
from app.core.units.draft import DraftError
from app.core.units.preview import UnitNotFound
from app.core.units.preview import preview_unit as read_preview
from app.core.units.read import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    InvalidCursor,
    QueueSection,
    UnitView,
    actionable_counts,
    review_queue,
)
from app.core.units.read import get_unit as read_unit

__all__ = ["UnitStateOut", "router"]  # UnitStateOut is shared with the entry form

router = APIRouter(prefix="/api/units", tags=["units"])

# a 422 in the same shape as a pydantic validation problem, located at the query parameter
map_error(
    InvalidCursor,
    422,
    "validation_error",
    details=lambda e: [{"location": ["query", e.parameter], "message": str(e), "type": "invalid_token"}],
)

SectionKind = Literal["pending_review", "needs_account", "waiting"]
Token = Annotated[str, Query(min_length=1, max_length=200)]


class NeedsAccountOut(BaseModel):
    currency: str  # the instructed currency of the unit's first (by entry id) leg that needs an account


class WaitingOut(BaseModel):
    account_id: int  # the counter-account of the unit's first (by entry id) waiting leg
    synced_through: date | None  # how far that account has been fetched; null = never


class WaitingDocumentOut(BaseModel):
    provider: str  # the document provider of the unit's first (by entry id) entry that waits for a document
    # how far the sources still holding it have covered (the earliest); null = one has never run
    covered_through: date | None


class CurrencyGroupOut(BaseModel):
    currency: str
    count: int  # units (not legs) that need an account in the currency, over the whole section


class UnitOut(BaseModel):
    anchor_entry_id: int  # the lowest entry id of the unit: what opens it (`?unit=`)
    unit_key: int
    state: UnitStateOut
    entries: list[EntryOut]  # ascending by id
    # queue only (null from `GET /{entry_id}` and in `pending_review`): set for a unit in `needs_account` ...
    needs_account: NeedsAccountOut | None = None
    # ... and for a unit in `waiting`
    waiting: WaitingOut | None = None
    # ... for a document instead of a partner: set instead of `waiting`
    waiting_document: WaitingDocumentOut | None = None
    # the model is still looking at one of its entries (read from its list when the response is built)
    model_pending: bool = False

    @staticmethod
    def of(view: UnitView, model_pending: frozenset[int] = frozenset()) -> UnitOut:
        return UnitOut(
            model_pending=any(e.id in model_pending for e in view.entries),
            anchor_entry_id=view.anchor_entry_id,
            unit_key=view.unit_key,
            state=UnitStateOut.of(view.state),
            entries=[EntryOut.of(e) for e in view.entries],
            needs_account=NeedsAccountOut(currency=view.needs_account) if view.needs_account else None,
            waiting=(
                WaitingOut(account_id=view.waiting.account_id, synced_through=view.waiting.synced_through)
                if view.waiting
                else None
            ),
            waiting_document=(
                WaitingDocumentOut(
                    provider=view.waiting_document.provider,
                    covered_through=view.waiting_document.covered_through,
                )
                if view.waiting_document
                else None
            ),
        )


class QueueSectionOut(BaseModel):
    kind: SectionKind
    total: int  # units in the section, whatever the page
    units: list[UnitOut]  # by the anchor's booked_on, then anchor id
    next_cursor: str | None
    groups: list[CurrencyGroupOut]  # `needs_account` only: units per required currency, by code; else []

    @staticmethod
    def of(section: QueueSection, model_pending: frozenset[int] = frozenset()) -> QueueSectionOut:
        return QueueSectionOut(
            kind=section.kind,
            total=section.total,
            units=[UnitOut.of(u, model_pending) for u in section.units],
            next_cursor=section.next_cursor,
            groups=[CurrencyGroupOut(currency=g.currency, count=g.count) for g in section.groups],
        )


class ReviewQueueOut(BaseModel):
    sections: list[QueueSectionOut]
    total: int  # units in all sections


class QueueCountOut(BaseModel):
    count: int  # units pending review or needing an account; not those waiting: the sum of the two below
    pending_review: int
    needs_account: int


def _model_pending(request: Request) -> frozenset[int]:
    """The entries the model is still looking at, now (empty without a model)."""
    queue = model_queue_of(request)
    return queue.entry_ids() if queue is not None else frozenset()


@router.get("/queue")
def get_review_queue(
    request: Request,
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
    pending = _model_pending(request)
    return ReviewQueueOut(
        sections=[QueueSectionOut.of(s, pending) for s in queue.sections], total=queue.total
    )


@router.get("/queue/count")
def get_queue_count(user: CurrentUser, engine: EngineDep) -> QueueCountOut:
    """How many units can be acted on now: pending review and needs an account, not waiting."""
    with engine.connect() as conn:
        counts = actionable_counts(conn)
    return QueueCountOut(
        count=counts.count, pending_review=counts.pending_review, needs_account=counts.needs_account
    )


class UnitMissing(LookupError):
    def __init__(self, entry_id: int) -> None:
        self.entry_id = entry_id
        super().__init__(f"entry {entry_id} is in no unit (it does not exist, or it is derived)")


map_error(UnitMissing, 404, "not_found")


@router.get("/{entry_id}")
def get_unit(request: Request, entry_id: PathId, user: CurrentUser, engine: EngineDep) -> UnitOut:
    """The unit holding the entry, as stored: its state and every entry with its derivation."""
    with engine.connect() as conn:
        view = read_unit(conn, entry_id)
    if view is None:
        raise UnitMissing(entry_id)
    return UnitOut.of(view, _model_pending(request))


# a draft that makes no sense against the stored unit: one 422 with the machine code in `details.code`
map_error(
    DraftError,
    422,
    "invalid_draft",
    details=lambda e: {"code": e.code, "entry_id": e.entry_id, "field": e.field},
)
map_error(UnitNotFound, 404, "not_found")
# the closure changed between reading the unit and holding its locks: reload it
# (or a picked document taken by another entry, or at another version: `reason` `taken` / `version`)
map_error(
    UnitMoved,
    409,
    "unit_moved",
    details=lambda e: {
        "anchor_entry_id": e.anchor_entry_id,
        "document_id": e.document_id,
        "reason": e.reason,
    },
)


@router.post("/preview")
def preview_unit(
    body: UnitDraftIn,
    user: CurrentUser,
    engine: EngineDep,
    window_days: Annotated[int | None, Query(ge=1, le=MAX_OFFER_WINDOW)] = None,
) -> UnitPreviewOut:
    """The unit as a commit of the draft would leave it, resolved fresh: rows, keys, flags, the state it leads
    to, the problems that would refuse the commit and the consequences. An in-memory overlay: nothing is
    written.

    Settling is simulated ledger-wide: a leg of the unit that settling would pair with a leg outside it brings
    that leg's unit into the rows. Each transfer row carries `transfer`: its state, partner and offers.
    `window_days` (1 to 90, default the matching window) is the window the offers are shown for."""
    return UnitPreviewOut.of(read_preview(engine, body.to_core(window_days), window_days=window_days))


@router.post("/commit")
def commit_unit(
    body: UnitDraftIn,
    user: CurrentUser,
    engine: EngineDep,
    window_days: Annotated[int | None, Query(ge=1, le=MAX_OFFER_WINDOW)] = None,
) -> UnitCommitOut:
    """Write the draft in one transaction, then settle. A commit does not confirm: settling does.

    409 `conflict` names the entries whose version moved (or that `versions` omitted); 409 `unit_moved` is a
    closure that changed under the locks, or a picked document that another entry carries (`details.reason`
    `taken`) or that is at another version (`version`), named in `details.document_id`; 409
    `stale_reference` a category, payee, account or picked document that no longer exists; 409 `try_again`
    a deadlock lost twice. 422 carries the code of the first problem the preview would
    list (all of them in `details.problems`), or `invalid_draft`. A pick is checked against the widest window
    (90 days), so one the widened preview accepted commits. `window_days` (1 to 90, default the matching
    window) is the window the proposals were shown for: send the one the preview used, so the proposals a
    commit accepts (as the user's decisions) are the ones shown."""
    try:
        return UnitCommitOut.of(write_unit(engine, body.to_core(window_days)))
    except CommitRefused as refused:
        first = refused.problems[0]
        raise ApiError(
            422,
            first.code,
            str(refused),
            {"problems": [UnitProblemOut.of(p).model_dump() for p in refused.problems]},
        ) from refused
