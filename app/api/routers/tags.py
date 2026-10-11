"""Tags (spec §3.7, architecture §4.1): CRUD and tagging a ledger filter's result.

Every write answers with what it touched and the `settle` result; a settling failure is a notice
inside a 200 response, never an HTTP error (architecture §5.2). `POST /{tag_id}/apply` takes the
same filter vocabulary as `GET /api/ledger/entries`, as a JSON body, validated by the same
`LedgerFilter`. It is previewed (`dry_run`), and the confirming request carries the preview's
`newly_tagged` as `expected_count`: tags move no version, so a changed result set is caught by
the count (409 `filter_result_changed`).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.api.errors import ApiError, map_error
from app.api.ids import MAX_ID, EntityId, PathId
from app.api.routers.accounts import CurrencyCode
from app.api.routers.entries import EntryType, ReviewFlag
from app.api.routers.maintenance import SettleOut
from app.api.session import CurrentUser, EngineDep
from app.core.ledger import InvalidFilter, LedgerFilter
from app.core.ledger.tags import (
    ApplyResult,
    DerivedEntryRefused,
    DuplicateTagName,
    EmptyFilter,
    EntryMissing,
    FilterResultChanged,
    InvalidTagValue,
    TagMissing,
    TagView,
    apply_tag,
    create_tag,
    delete_tag,
    list_tags,
    update_tag,
)

router = APIRouter(prefix="/api/ledger/tags", tags=["tags"])

map_error(TagMissing, 404, "not_found")
map_error(EntryMissing, 404, "not_found")
map_error(DuplicateTagName, 409, "conflict", details=lambda e: {"reason": "duplicate_name"})
map_error(DerivedEntryRefused, 409, "conflict", details=lambda e: {"reason": "derived_entry"})
map_error(
    FilterResultChanged,
    409,
    "conflict",
    details=lambda e: {"reason": "filter_result_changed", "expected": e.expected, "actual": e.actual},
)
map_error(
    InvalidTagValue,
    422,
    "validation_error",
    details=lambda e: [{"location": ["body", e.parameter], "message": str(e), "type": "invalid_tag"}],
)
# an apply with no filter dimension tags the whole ledger: refused unless `all` says so
map_error(
    EmptyFilter,
    422,
    "validation_error",
    details=lambda e: [{"location": ["body", "all"], "message": str(e), "type": "empty_filter"}],
)

TagName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ColorName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
SearchText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Amount = Annotated[int, Field(ge=0, le=2**63 - 1)]


class TagOut(BaseModel):
    id: int
    name: str
    color: str | None
    starts_on: date | None  # the earliest booked_on among the tagged entries
    ends_on: date | None
    entry_count: int

    @classmethod
    def of(cls, view: TagView) -> TagOut:
        return cls(**vars(view))


class TagsOut(BaseModel):
    tags: list[TagOut]


class TagWriteOut(BaseModel):
    tag: TagOut
    settle: SettleOut


class TagDeleteOut(BaseModel):
    removed_memberships: int
    settle: SettleOut


class TagCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: TagName
    color: ColorName | None = None


class TagUpdateBody(BaseModel):
    """Absent fields stay; `color: null` clears the colour."""

    model_config = ConfigDict(extra="forbid")

    name: TagName | None = None
    color: ColorName | None = None


class TagApplyBody(BaseModel):
    """The list's filter vocabulary (`GET /api/ledger/entries`) as JSON, plus the apply controls."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: Annotated[date | None, Field(alias="from")] = None
    to: date | None = None
    account_id: list[EntityId] = []
    category_id: list[EntityId] = []
    category_descendants: bool = True
    uncategorised: bool = False
    payee_id: list[EntityId] = []
    tag_id: list[EntityId] = []
    amount_min: Amount | None = None
    amount_max: Amount | None = None
    currency: CurrencyCode | None = None
    direction: Literal["in", "out"] | None = None
    q: SearchText | None = None
    type: list[EntryType] = []
    flag: list[ReviewFlag] = []
    all: bool = False  # tag the whole ledger when no filter dimension is given
    dry_run: bool = False  # count and report; write nothing
    expected_count: Annotated[int, Field(ge=0, le=MAX_ID)] | None = None  # the preview's newly_tagged


class SpanOut(BaseModel):
    starts_on: date | None
    ends_on: date | None
    entry_count: int


class AccountCountOut(BaseModel):
    account_id: int
    newly_tagged: int


class EntryTagIdsOut(BaseModel):
    id: int
    tag_ids: list[int]  # sorted


class TagApplyOut(BaseModel):
    dry_run: bool
    selected: int  # entries the filter matches
    newly_tagged: int
    already_tagged: int
    skipped_derived: int  # derived entries take no tags
    per_account: list[AccountCountOut]  # ascending account id; accounts with newly tagged entries only
    span_before: SpanOut
    span_after: SpanOut
    entries: list[EntryTagIdsOut]  # the newly tagged entries as they now stand; empty on a dry run
    settle: SettleOut | None  # null on a dry run

    @classmethod
    def of(cls, result: ApplyResult, *, dry_run: bool) -> TagApplyOut:
        return cls(
            dry_run=dry_run,
            selected=result.selected,
            newly_tagged=result.newly_tagged,
            already_tagged=result.already_tagged,
            skipped_derived=result.skipped_derived,
            per_account=[
                AccountCountOut(account_id=a, newly_tagged=n) for a, n in sorted(result.per_account.items())
            ],
            span_before=SpanOut(**vars(result.span_before)),
            span_after=SpanOut(**vars(result.span_after)),
            entries=[EntryTagIdsOut(id=i, tag_ids=list(t)) for i, t in result.entries],
            settle=None if result.settle is None else SettleOut.of(result.settle),
        )


@router.get("")
def list_ledger_tags(user: CurrentUser, engine: EngineDep) -> TagsOut:
    """Every tag by name with its derived span; a tag no entry uses has a null span and a count of 0."""
    with engine.connect() as conn:
        return TagsOut(tags=[TagOut.of(v) for v in list_tags(conn)])


@router.post("", status_code=201)
def create_ledger_tag(body: TagCreateBody, user: CurrentUser, engine: EngineDep) -> TagWriteOut:
    made = create_tag(engine, name=body.name, color=body.color)
    return TagWriteOut(tag=TagOut.of(made.tag), settle=SettleOut.of(made.settle))


@router.put("/{tag_id}")
def update_ledger_tag(
    tag_id: PathId, body: TagUpdateBody, user: CurrentUser, engine: EngineDep
) -> TagWriteOut:
    done = update_tag(
        engine,
        tag_id,
        name=body.name if body.name is not None else ...,
        color=body.color if "color" in body.model_fields_set else ...,
    )
    return TagWriteOut(tag=TagOut.of(done.tag), settle=SettleOut.of(done.settle))


@router.delete("/{tag_id}")
def delete_ledger_tag(tag_id: PathId, user: CurrentUser, engine: EngineDep) -> TagDeleteOut:
    gone = delete_tag(engine, tag_id)
    return TagDeleteOut(removed_memberships=gone.removed_memberships, settle=SettleOut.of(gone.settle))


@router.post("/{tag_id}/apply")
def apply_ledger_tag(tag_id: PathId, body: TagApplyBody, user: CurrentUser, engine: EngineDep) -> TagApplyOut:
    """Tag every entry the filter selects (derived entries are skipped). `dry_run` previews it."""
    try:
        flt = LedgerFilter(
            date_from=body.from_,
            date_to=body.to,
            account_ids=tuple(body.account_id),
            category_ids=tuple(body.category_id),
            category_descendants=body.category_descendants,
            uncategorised=body.uncategorised,
            payee_ids=tuple(body.payee_id),
            tag_ids=tuple(body.tag_id),
            amount_min=body.amount_min,
            amount_max=body.amount_max,
            currency=body.currency,
            direction=body.direction,
            text=body.q,
            types=tuple(body.type),
            flags=tuple(body.flag),
        )
    except InvalidFilter as exc:
        raise ApiError(
            422,
            "validation_error",
            "The request is not valid.",
            [{"location": ["body", exc.parameter], "message": str(exc), "type": "invalid_filter"}],
        ) from exc
    result = apply_tag(
        engine, tag_id, flt, dry_run=body.dry_run, expected_count=body.expected_count, all_=body.all
    )
    return TagApplyOut.of(result, dry_run=body.dry_run)
