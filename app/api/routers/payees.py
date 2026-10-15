"""Payee writes (spec §3.6, architecture §4.1): create, update, delete, merge.

Same conventions as categories: every write answers with what it touched and the `settle` result;
delete and merge are previewed (`dry_run`), the real merge carries the dry run's `entry_count` as
`expected_count` (409 `filter_result_changed` when it moved). The list is `GET /api/ledger/payees`
(`lookups.py`). `POST /payees/suggest-name` (AI-assisted naming) is not built.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.api.errors import map_error
from app.api.ids import MAX_ID, EntityId, PathId
from app.api.routers.lookups import PayeeOut
from app.api.routers.maintenance import SettleOut
from app.api.session import CurrentUser, EngineDep
from app.core.ledger.dimensions import DuplicateName, ExpectedCountRequired, InvalidValue
from app.core.ledger.payees import (
    PayeeDeleteResult,
    PayeeInUse,
    PayeeMergeResult,
    PayeeMissing,
    create_payee,
    delete_payee,
    merge_payee,
    update_payee,
)

router = APIRouter(prefix="/api/ledger/payees", tags=["payees"])

map_error(PayeeMissing, 404, "not_found")
map_error(DuplicateName, 409, "conflict", details=lambda e: {"reason": "duplicate_name"})
map_error(PayeeInUse, 409, "conflict", details=lambda e: {"reason": "payee_in_use", "held": e.held})
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

PayeeName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
PresentationName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
Count = Annotated[int, Field(ge=0, le=MAX_ID)]


class PayeeWriteOut(BaseModel):
    payee: PayeeOut
    settle: SettleOut


class PayeeCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: PayeeName
    note: str | None = None
    icon: PresentationName | None = None
    color: PresentationName | None = None
    document_provider: str | None = None  # free text; blank means none


class PayeeUpdateBody(BaseModel):
    """Absent fields stay; `null` clears `note`, `icon`, `color` and `document_provider`."""

    model_config = ConfigDict(extra="forbid")

    name: PayeeName | None = None
    note: str | None = None
    icon: PresentationName | None = None
    color: PresentationName | None = None
    document_provider: str | None = None


class RuleRefOut(BaseModel):
    id: int
    name: str
    sets: str  # what the rule sets: counter_account, payee or category
    role: str  # "sets": it sets this payee; "condition": its condition names it (left dangling)


class PayeeHeldOut(BaseModel):
    entries: int


class PayeeDeleteOut(BaseModel):
    dry_run: bool
    payee: PayeeOut
    deletable: bool  # no entry references it
    held: PayeeHeldOut
    rules: list[RuleRefOut]  # the rules that go with it: those setting it
    dangling_rules: list[RuleRefOut]  # rules whose payee condition names it: they stay and never match
    deleted_rule_ids: list[int]  # real run only
    deleted: bool
    settle: SettleOut | None  # null on a dry run

    @classmethod
    def of(cls, result: PayeeDeleteResult, *, dry_run: bool) -> PayeeDeleteOut:
        return cls(
            dry_run=dry_run,
            payee=PayeeOut(**vars(result.payee)),
            deletable=not result.held,
            held=PayeeHeldOut(entries=result.held.get("entries", 0)),
            rules=[RuleRefOut(**vars(r)) for r in result.rules],
            dangling_rules=[RuleRefOut(**vars(r)) for r in result.dangling_rules],
            deleted_rule_ids=list(result.deleted_rule_ids),
            deleted=result.deleted,
            settle=None if result.settle is None else SettleOut.of(result.settle),
        )


class PayeeMergeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    into: EntityId
    dry_run: bool = False
    expected_count: Count | None = None  # the dry run's entry_count; required for a real run


class PayeeMergeOut(BaseModel):
    dry_run: bool
    source_id: int  # the payee that goes
    target: PayeeOut  # the payee that stays, with its own attributes
    entry_count: int
    entry_ids: list[int]  # ascending; empty on a dry run
    setting_rule_ids: list[int]  # rules repointed whose payee it was
    condition_rule_ids: list[int]  # rules whose payee condition it was, rewritten to the target
    source_document_provider: str | None
    document_provider_lost: bool  # the source names a provider the target does not
    settle: SettleOut | None  # null on a dry run

    @classmethod
    def of(cls, result: PayeeMergeResult, *, dry_run: bool) -> PayeeMergeOut:
        return cls(
            dry_run=dry_run,
            source_id=result.source_id,
            target=PayeeOut(**vars(result.target)),
            entry_count=result.entry_count,
            entry_ids=list(result.entry_ids),
            setting_rule_ids=list(result.setting_rule_ids),
            condition_rule_ids=list(result.condition_rule_ids),
            source_document_provider=result.source_document_provider,
            document_provider_lost=result.document_provider_lost,
            settle=None if result.settle is None else SettleOut.of(result.settle),
        )


@router.post("", status_code=201)
def create_ledger_payee(body: PayeeCreateBody, user: CurrentUser, engine: EngineDep) -> PayeeWriteOut:
    made = create_payee(
        engine,
        name=body.name,
        note=body.note,
        icon=body.icon,
        color=body.color,
        document_provider=body.document_provider,
    )
    return PayeeWriteOut(payee=PayeeOut(**vars(made.payee)), settle=SettleOut.of(made.settle))


@router.put("/{payee_id}")
def update_ledger_payee(
    payee_id: PathId, body: PayeeUpdateBody, user: CurrentUser, engine: EngineDep
) -> PayeeWriteOut:
    given = body.model_fields_set
    done = update_payee(
        engine,
        payee_id,
        name=body.name if body.name is not None else ...,
        note=body.note if "note" in given else ...,
        icon=body.icon if "icon" in given else ...,
        color=body.color if "color" in given else ...,
        document_provider=body.document_provider if "document_provider" in given else ...,
    )
    return PayeeWriteOut(payee=PayeeOut(**vars(done.payee)), settle=SettleOut.of(done.settle))


@router.delete("/{payee_id}")
def delete_ledger_payee(
    payee_id: PathId, user: CurrentUser, engine: EngineDep, dry_run: bool = False
) -> PayeeDeleteOut:
    """Delete a payee no entry references, with its rules (else 409 `payee_in_use`).

    `dry_run=true` lists the rules it would take and writes nothing.
    """
    return PayeeDeleteOut.of(delete_payee(engine, payee_id, dry_run=dry_run), dry_run=dry_run)


@router.post("/{payee_id}/merge")
def merge_ledger_payee(
    payee_id: PathId, body: PayeeMergeBody, user: CurrentUser, engine: EngineDep
) -> PayeeMergeOut:
    """Merge into another payee, whose attributes win; `dry_run` previews and warns about the provider."""
    result = merge_payee(
        engine, payee_id, body.into, dry_run=body.dry_run, expected_count=body.expected_count
    )
    return PayeeMergeOut.of(result, dry_run=body.dry_run)
