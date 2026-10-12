"""Category writes (spec §3.5, architecture §4.1): create, update, delete, merge.

Every write answers with what it touched and the `settle` result; a settling failure is a notice
inside a 200 response, never an HTTP error (architecture §5.2). Delete and merge are previewed
(`dry_run`); the real merge carries the dry run's `entry_count` as `expected_count`, and a moved
number is 409 `filter_result_changed` (the tags convention). A write that names a parent or merge
target that no longer exists is 409 `stale_reference`. The list is `GET /api/ledger/categories`
(`lookups.py`).
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.api.errors import map_error
from app.api.ids import MAX_ID, EntityId, PathId
from app.api.routers.lookups import CategoryOut
from app.api.routers.maintenance import SettleOut
from app.api.session import CurrentUser, EngineDep
from app.core.ledger.categories import (
    CategoryCycle,
    CategoryDeleteResult,
    CategoryInUse,
    CategoryMergeResult,
    CategoryMissing,
    MergeRefused,
    create_category,
    delete_category,
    merge_category,
    update_category,
)
from app.core.ledger.dimensions import DuplicateName, ExpectedCountRequired, InvalidValue

router = APIRouter(prefix="/api/ledger/categories", tags=["categories"])

map_error(CategoryMissing, 404, "not_found")
map_error(DuplicateName, 409, "conflict", details=lambda e: {"reason": "duplicate_name"})
map_error(CategoryCycle, 409, "conflict", details=lambda e: {"reason": "cycle"})
map_error(CategoryInUse, 409, "conflict", details=lambda e: {"reason": "category_in_use", "held": e.held})
map_error(MergeRefused, 409, "conflict", details=lambda e: {"reason": e.reason})
map_error(
    InvalidValue,
    422,
    "validation_error",
    details=lambda e: [{"location": ["body", e.parameter], "message": str(e), "type": "invalid_value"}],
)
map_error(
    ExpectedCountRequired,
    422,
    "validation_error",
    details=lambda e: [{"location": ["body", "expected_count"], "message": str(e), "type": "missing"}],
)

CategoryName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
PresentationName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
SortOrder = Annotated[int, Field(strict=True, ge=-(2**31), le=2**31 - 1)]
Count = Annotated[int, Field(ge=0, le=MAX_ID)]


class CategoryWriteOut(BaseModel):
    category: CategoryOut
    settle: SettleOut


class CategoryCreateBody(BaseModel):
    """A top-level category takes `kind`; a child (`parent_id`) takes its parent's."""

    model_config = ConfigDict(extra="forbid")

    name: CategoryName
    kind: Literal["income", "expense"] | None = None
    parent_id: EntityId | None = None
    sort_order: SortOrder = 0
    icon: PresentationName | None = None  # null: inherit the parent's
    color: PresentationName | None = None


class CategoryUpdateBody(BaseModel):
    """Absent fields stay; `null` clears `icon` and `color`, and `parent_id: null` makes it top-level.

    No `kind`: it is fixed at creation.
    """

    model_config = ConfigDict(extra="forbid")

    name: CategoryName | None = None
    parent_id: EntityId | None = None
    sort_order: SortOrder | None = None
    icon: PresentationName | None = None
    color: PresentationName | None = None


class HeldOut(BaseModel):
    entries: int
    rules: int
    children: int


class CategoryDeleteOut(BaseModel):
    dry_run: bool
    category: CategoryOut
    deletable: bool  # nothing references it and it has no children
    held: HeldOut  # what stands in the way
    deleted: bool  # real run only
    settle: SettleOut | None  # null on a dry run

    @classmethod
    def of(cls, result: CategoryDeleteResult, *, dry_run: bool) -> CategoryDeleteOut:
        return cls(
            dry_run=dry_run,
            category=CategoryOut(**vars(result.category)),
            deletable=not result.held,
            held=HeldOut(
                entries=result.held.get("entries", 0),
                rules=result.held.get("rules", 0),
                children=result.held.get("children", 0),
            ),
            deleted=result.deleted,
            settle=None if result.settle is None else SettleOut.of(result.settle),
        )


class CategoryMergeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    into: EntityId
    dry_run: bool = False
    expected_count: Count | None = None  # the dry run's entry_count; required for a real run


class MergedPairOut(BaseModel):
    source_id: int
    source_name: str
    target_id: int
    target_name: str
    entries: int  # repointed
    rules: int


class MovedChildOut(BaseModel):
    id: int
    name: str
    from_id: int
    to_id: int


class CategoryMergeOut(BaseModel):
    dry_run: bool
    source_id: int
    target_id: int
    pairs: list[MergedPairOut]  # every merge, deepest first, the requested one last
    moved_children: list[MovedChildOut]
    entry_count: int  # entries repointed in all
    entry_ids: list[int]  # ascending; empty on a dry run
    rule_ids: list[int]  # the rules repointed
    settle: SettleOut | None  # null on a dry run

    @classmethod
    def of(cls, result: CategoryMergeResult, *, dry_run: bool) -> CategoryMergeOut:
        return cls(
            dry_run=dry_run,
            source_id=result.source_id,
            target_id=result.target_id,
            pairs=[MergedPairOut(**vars(p)) for p in result.pairs],
            moved_children=[MovedChildOut(**vars(m)) for m in result.moved_children],
            entry_count=result.entry_count,
            entry_ids=list(result.entry_ids),
            rule_ids=list(result.rule_ids),
            settle=None if result.settle is None else SettleOut.of(result.settle),
        )


@router.post("", status_code=201)
def create_ledger_category(
    body: CategoryCreateBody, user: CurrentUser, engine: EngineDep
) -> CategoryWriteOut:
    made = create_category(
        engine,
        name=body.name,
        kind=body.kind,
        parent_id=body.parent_id,
        sort_order=body.sort_order,
        icon=body.icon,
        color=body.color,
    )
    return CategoryWriteOut(category=CategoryOut(**vars(made.category)), settle=SettleOut.of(made.settle))


@router.put("/{category_id}")
def update_ledger_category(
    category_id: PathId, body: CategoryUpdateBody, user: CurrentUser, engine: EngineDep
) -> CategoryWriteOut:
    given = body.model_fields_set
    done = update_category(
        engine,
        category_id,
        name=body.name if body.name is not None else ...,
        parent_id=body.parent_id if "parent_id" in given else ...,
        sort_order=body.sort_order if body.sort_order is not None else ...,
        icon=body.icon if "icon" in given else ...,
        color=body.color if "color" in given else ...,
    )
    return CategoryWriteOut(category=CategoryOut(**vars(done.category)), settle=SettleOut.of(done.settle))


@router.delete("/{category_id}")
def delete_ledger_category(
    category_id: PathId, user: CurrentUser, engine: EngineDep, dry_run: bool = False
) -> CategoryDeleteOut:
    """Delete a category nothing references and without children (else 409 `category_in_use`).

    `dry_run=true` reports what stands in the way and writes nothing.
    """
    return CategoryDeleteOut.of(delete_category(engine, category_id, dry_run=dry_run), dry_run=dry_run)


@router.post("/{category_id}/merge")
def merge_ledger_category(
    category_id: PathId, body: CategoryMergeBody, user: CurrentUser, engine: EngineDep
) -> CategoryMergeOut:
    """Merge into another category of the same kind (never into its own descendant); `dry_run` previews."""
    result = merge_category(
        engine, category_id, body.into, dry_run=body.dry_run, expected_count=body.expected_count
    )
    return CategoryMergeOut.of(result, dry_run=body.dry_run)
