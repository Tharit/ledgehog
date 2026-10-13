"""Rules (spec §5.9, architecture §4.1): list, get, create, update, delete, each write previewed.

A rule write answers with the rule, the preview (the entries it matches with the rule that takes
precedence over each, the entries it would confirm, and the two lists of entries to check by hand)
and the `settle` result; a settling failure is a notice inside a 200 response, never an HTTP error
(architecture §5.2). `dry_run` runs the same code and writes nothing; the real run carries the
preview's `matches.total` as `expected_count`, and a moved number is 409 `filter_result_changed`
(the tags convention). A rule that cannot be saved is 422 `invalid_rule`, its details naming the
field; a target or payee condition that no longer exists is 409 `stale_reference`. `limit` and
`offset` page every row list of the preview alike. A rule write changes no entry (I20).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.api.errors import map_error
from app.api.ids import MAX_ID, EntityId, PathId
from app.api.routers.accounts import Money
from app.api.routers.entries import SourceTransactionOut
from app.api.routers.maintenance import SettleOut
from app.api.session import CurrentUser, EngineDep
from app.core.ledger.dimensions import DuplicateName, ExpectedCountRequired, InvalidValue
from app.core.ledger.rule_preview import DEFAULT_LIMIT, MAX_LIMIT, PreviewList, PreviewRow, RulePreview
from app.core.ledger.rules import (
    InvalidRule,
    RuleDraft,
    RuleMissing,
    RuleRow,
    RuleWritten,
    create_rule,
    delete_rule,
    get_rule,
    list_rules,
    update_rule,
)
from app.core.plugins.classifier import Condition

router = APIRouter(prefix="/api/ledger/rules", tags=["rules"])

map_error(RuleMissing, 404, "not_found")
map_error(DuplicateName, 409, "conflict", details=lambda e: {"reason": "duplicate_name"})
map_error(
    InvalidValue,
    422,
    "validation_error",
    details=lambda e: [{"location": ["body", e.parameter], "message": str(e), "type": "invalid_value"}],
)
map_error(
    InvalidRule,
    422,
    "invalid_rule",
    details=lambda e: [{"location": ["body", e.field], "message": str(e), "type": "invalid_rule"}],
)
map_error(
    ExpectedCountRequired,
    422,
    "validation_error",
    details=lambda e: [{"location": ["body", "expected_count"], "message": str(e), "type": "missing"}],
)

Sets = Literal["counter_account", "payee", "category"]
RuleName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
# a condition's value as typed; the plugin judges blankness and a regex (422 `invalid_rule`), so only
# an absurd size stops here
ConditionValue = Annotated[str, StringConstraints(max_length=2000)]
ConditionFieldName = Literal[
    "counterparty_name", "counterparty_ref", "purpose", "booking_text", "mandate_ref"
]
ConditionOpName = Literal["equals", "starts_with", "contains", "regex"]
Priority = Annotated[int, Field(strict=True, ge=-(2**31), le=2**31 - 1)]
Count = Annotated[int, Field(ge=0, le=MAX_ID)]
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
Offset = Annotated[int, Query(ge=0, le=MAX_ID)]


class ConditionOut(BaseModel):
    """One condition of a rule; all of a rule's conditions must hold."""

    field: ConditionFieldName
    op: ConditionOpName
    value: str


class ConditionBody(BaseModel):
    """A condition as written. The field and operator are not narrowed here: an unknown one is the
    plugin's 422 `invalid_rule`, located at `conditions[i].field`, like a blank value."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(max_length=100)
    op: str = Field(max_length=100)
    value: ConditionValue


class RuleOut(BaseModel):
    """A rule; exactly the target id `sets` names is set."""

    id: int
    name: str
    sets: Sets
    counter_account_id: int | None
    payee_id: int | None
    category_id: int | None
    condition_payee_id: int | None  # category rules only
    conditions: list[ConditionOut]  # all must hold; may be empty only with a payee condition
    priority: int

    @staticmethod
    def of(row: RuleRow) -> RuleOut:
        return RuleOut(
            id=row.id,
            name=row.name,
            sets=cast(Sets, row.sets),
            counter_account_id=row.counter_account_id,
            payee_id=row.payee_id,
            category_id=row.category_id,
            condition_payee_id=row.condition_payee_id,
            conditions=[ConditionOut(field=c.field, op=c.op, value=c.value) for c in row.conditions],
            priority=row.priority,
        )


class RuleBody(BaseModel):
    """A rule's name, target (the one id its `sets` names), conditions and priority."""

    model_config = ConfigDict(extra="forbid")

    name: RuleName
    counter_account_id: EntityId | None = None
    payee_id: EntityId | None = None
    category_id: EntityId | None = None
    condition_payee_id: EntityId | None = None  # category rules only
    conditions: list[ConditionBody] = Field(default_factory=list, max_length=50)  # all must hold
    priority: Priority = 100
    dry_run: bool = False
    expected_count: Count | None = None  # the dry run's `matches.total`; required for a real run

    def draft(self, sets: str | None) -> RuleDraft:
        return RuleDraft(
            name=self.name,
            sets=sets,
            counter_account_id=self.counter_account_id,
            payee_id=self.payee_id,
            category_id=self.category_id,
            condition_payee_id=self.condition_payee_id,
            conditions=tuple(
                Condition(c.field, c.op, c.value)  # type: ignore[arg-type]  # the plugin validates them
                for c in self.conditions
            ),
            priority=self.priority,
        )


class RuleCreateBody(RuleBody):
    sets: Sets  # what the rule sets: fixed from now on


class RuleUpdateBody(RuleBody):
    """The rule as it should be: every condition is stated (absent means none).

    `sets` may be restated but never changed (422 `invalid_rule`).
    """

    sets: Sets | None = None


class PreviewRowOut(BaseModel):
    entry_id: int
    account_id: int
    booked_on: date
    amount: Money
    description: str | None
    confirmed: bool
    current_value: int | None  # the id the entry holds for what the rule sets
    current_key: dict[str, Any] | None  # and the key explaining it: {"pass", "basis"}
    shadowed_by_rule_id: int | None  # matches only: the earlier rule that wins this entry
    keyed_fields: list[str]  # lost-key list only: the fields carrying the rule's key
    source: SourceTransactionOut | None  # as in the ledger list; null for a user-authored row

    @staticmethod
    def of(row: PreviewRow) -> PreviewRowOut:
        return PreviewRowOut(
            entry_id=row.entry_id,
            account_id=row.account_id,
            booked_on=row.booked_on,
            amount=Money(amount=row.amount, currency=row.currency),
            description=row.description,
            confirmed=row.confirmed,
            current_value=row.current_value,
            current_key=None if row.current_key is None else dict(row.current_key),
            shadowed_by_rule_id=row.shadowed_by_rule_id,
            keyed_fields=list(row.keyed_fields),
            source=SourceTransactionOut.of(row.source),
        )


class PreviewListOut(BaseModel):
    total: int  # exact
    rows: list[PreviewRowOut]  # one page: newest first

    @staticmethod
    def of(lst: PreviewList) -> PreviewListOut:
        return PreviewListOut(total=lst.total, rows=[PreviewRowOut.of(r) for r in lst.rows])


class RulePreviewOut(BaseModel):
    matches: PreviewListOut  # (a) every entry the rule matches, confirmed or not
    would_confirm: int  # (b) matched unconfirmed entries that settling would confirm
    stay_in_review: int  # matched unconfirmed entries that would not be
    different_value: PreviewListOut  # list A: matched, holding another value of what the rule sets
    lost_key: PreviewListOut  # list B: carrying the rule's key, no longer matched

    @staticmethod
    def of(p: RulePreview) -> RulePreviewOut:
        return RulePreviewOut(
            matches=PreviewListOut.of(p.matches),
            would_confirm=p.would_confirm,
            stay_in_review=p.stay_in_review,
            different_value=PreviewListOut.of(p.different_value),
            lost_key=PreviewListOut.of(p.lost_key),
        )


class RuleWriteOut(BaseModel):
    dry_run: bool
    rule: RuleOut | None  # as it stands (would stand, on a dry run); null for the dry run of a create
    preview: RulePreviewOut
    settle: SettleOut | None  # null on a dry run

    @staticmethod
    def of(written: RuleWritten, *, dry_run: bool) -> RuleWriteOut:
        return RuleWriteOut(
            dry_run=dry_run,
            rule=None if written.rule is None else RuleOut.of(written.rule),
            preview=RulePreviewOut.of(written.preview),
            settle=None if written.settle is None else SettleOut.of(written.settle),
        )


class RuleDeleteOut(BaseModel):
    dry_run: bool
    rule: RuleOut  # as it was
    deleted: bool  # real run only
    preview: RulePreviewOut  # `lost_key` lists every entry carrying the rule's key
    settle: SettleOut | None

    @staticmethod
    def of(written: RuleWritten, *, dry_run: bool) -> RuleDeleteOut:
        assert written.rule is not None
        return RuleDeleteOut(
            dry_run=dry_run,
            rule=RuleOut.of(written.rule),
            deleted=written.deleted,
            preview=RulePreviewOut.of(written.preview),
            settle=None if written.settle is None else SettleOut.of(written.settle),
        )


@router.get("")
def list_ledger_rules(user: CurrentUser, engine: EngineDep) -> list[RuleOut]:
    """Every rule in evaluation order: counter-account, payee, category; priority, then id."""
    with engine.connect() as conn:
        return [RuleOut.of(r) for r in list_rules(conn)]


@router.get("/{rule_id}")
def get_ledger_rule(rule_id: PathId, user: CurrentUser, engine: EngineDep) -> RuleOut:
    with engine.connect() as conn:
        row = get_rule(conn, rule_id)
    if row is None:
        raise RuleMissing(rule_id)
    return RuleOut.of(row)


@router.post("", status_code=201)
def create_ledger_rule(
    body: RuleCreateBody,
    user: CurrentUser,
    engine: EngineDep,
    response: Response,
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> RuleWriteOut:
    """Create a rule. `dry_run=true` previews it (200, nothing written); a real run needs the
    preview's `matches.total` as `expected_count`. What it sets is fixed from now on."""
    written = create_rule(
        engine,
        body.draft(body.sets),
        dry_run=body.dry_run,
        expected_count=body.expected_count,
        limit=limit,
        offset=offset,
    )
    if body.dry_run:
        response.status_code = 200
    return RuleWriteOut.of(written, dry_run=body.dry_run)


@router.put("/{rule_id}")
def update_ledger_rule(
    rule_id: PathId,
    body: RuleUpdateBody,
    user: CurrentUser,
    engine: EngineDep,
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> RuleWriteOut:
    """Replace name, target value, conditions and priority; `dry_run` previews. Never changes `sets`."""
    written = update_rule(
        engine,
        rule_id,
        body.draft(body.sets),
        dry_run=body.dry_run,
        expected_count=body.expected_count,
        limit=limit,
        offset=offset,
    )
    return RuleWriteOut.of(written, dry_run=body.dry_run)


@router.delete("/{rule_id}")
def delete_ledger_rule(
    rule_id: PathId,
    user: CurrentUser,
    engine: EngineDep,
    dry_run: bool = False,
    expected_count: Annotated[int | None, Query(ge=0, le=MAX_ID)] = None,
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> RuleDeleteOut:
    """Delete a rule; keys naming it stay on the entries. `dry_run` previews; a real run needs
    `expected_count`, the number of entries the rule matched in the preview."""
    written = delete_rule(
        engine, rule_id, dry_run=dry_run, expected_count=expected_count, limit=limit, offset=offset
    )
    return RuleDeleteOut.of(written, dry_run=dry_run)
