"""The shapes of `POST /api/units/preview` and `POST /api/units/commit` (architecture §4.1, spec §6).

The request is a `UnitDraftIn`: the anchor, the entries the user changed (stored ids, or negative
temporary ids for rows a split creates), the entries removed and the versions the client saw. Every request
model forbids unknown fields. The preview answers with `UnitPreviewOut` (the unit as a commit would leave it,
field by field, the problems that would refuse the commit, the consequences), the commit with `UnitCommitOut`
(rows, not ids).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.api.ids import MAX_ID, EntityId, EntityVersion
from app.api.routers.accounts import Money
from app.api.routers.entries import EntryOut
from app.api.routers.maintenance import SettleOut
from app.core.units.commit import CommitResult
from app.core.units.draft import UNSET, DraftEntry, FieldDraft, ShownBasis, UnitDraft
from app.core.units.plan import (
    Consequence,
    FieldResult,
    Plan,
    PlannedRow,
    PlannedUnit,
    Problem,
    Split,
    Stored,
    StoredUnit,
)
from app.core.units.state import UnitState

UnitReason = Literal["incomplete", "unpaired_transfer", "non_standing_keys"]
FieldName = Literal["type", "payee", "category", "counter_account"]
ConsequenceKind = Literal["created", "changed", "returns_to_review", "deleted", "unpaired", "left_behind"]
TempOrStoredId = Annotated[int, Field(ge=-MAX_ID, le=MAX_ID)]


# ---- the request --------------------------------------------------------------------------------


class UnitShownBasisIn(BaseModel):
    """The key of the proposal the client showed for a value (`pass` is history, llm or matcher_proposal)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    pass_: str = Field(alias="pass")
    basis: dict[str, Any] = Field(default_factory=dict)


class UnitFieldDraftIn(BaseModel):
    """`keep`: untouched (a commit accepts what resolution makes of it). `fixed`: the user's `value` (null
    leaves the field empty). `reresolve`: the passes decide this field again."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["keep", "fixed", "reresolve"] = "keep"
    value: int | str | None = None
    shown_basis: UnitShownBasisIn | None = None

    def to_core(self) -> FieldDraft:
        shown = (
            None if self.shown_basis is None else ShownBasis(self.shown_basis.pass_, self.shown_basis.basis)
        )
        return FieldDraft(self.mode, self.value, shown)


class UnitTagChangeIn(BaseModel):
    """A change of an entry's tags relative to its stored tags (a new entry's: the original's). A tag in both
    lists is 422 `invalid_draft` (`tag_conflict`); duplicates are tolerated."""

    model_config = ConfigDict(extra="forbid")

    add: list[EntityId] = Field(default_factory=list, max_length=500)
    remove: list[EntityId] = Field(default_factory=list, max_length=500)


class UnitDraftEntryIn(BaseModel):
    """One entry the draft changes. `description` and `note` are left as stored when absent and emptied when
    null. A new entry (negative `id`) names `source_entry_id`, a stored entry of the source it splits, and
    carries its `amount`; the source's original entry is the residual and takes no amount of its own. `tags`
    is a tag change on top of the stored (or inherited) tags; absent leaves them untouched."""

    model_config = ConfigDict(extra="forbid")

    id: TempOrStoredId
    amount: int | None = Field(default=None, ge=-(2**62), le=2**62)
    description: str | None = None
    note: str | None = None
    type: UnitFieldDraftIn = Field(default_factory=UnitFieldDraftIn)
    payee: UnitFieldDraftIn = Field(default_factory=UnitFieldDraftIn)
    category: UnitFieldDraftIn = Field(default_factory=UnitFieldDraftIn)
    counter_account: UnitFieldDraftIn = Field(default_factory=UnitFieldDraftIn)
    source_entry_id: EntityId | None = None
    tags: UnitTagChangeIn | None = None

    def to_core(self) -> DraftEntry:
        given = self.model_fields_set
        return DraftEntry(
            id=self.id,
            amount=self.amount,
            description=self.description if "description" in given else UNSET,
            note=self.note if "note" in given else UNSET,
            type=self.type.to_core(),
            payee=self.payee.to_core(),
            category=self.category.to_core(),
            counter_account=self.counter_account.to_core(),
            source_entry_id=self.source_entry_id,
            tags_add=tuple(sorted(set(self.tags.add))) if self.tags else (),
            tags_remove=tuple(sorted(set(self.tags.remove))) if self.tags else (),
        )


class UnitDraftIn(BaseModel):
    """The draft of the unit anchored on `anchor_entry_id`. `versions` map an entry id to the version the
    client saw, for every entry of the unit (a commit carries them; a preview ignores them)."""

    model_config = ConfigDict(extra="forbid")

    anchor_entry_id: EntityId
    entries: list[UnitDraftEntryIn] = Field(default_factory=list, max_length=500)
    removed_entry_ids: list[EntityId] = Field(default_factory=list, max_length=500)
    reresolve_all: bool = False
    versions: dict[EntityId, EntityVersion] = Field(default_factory=dict)

    def to_core(self) -> UnitDraft:
        return UnitDraft(
            anchor_entry_id=self.anchor_entry_id,
            entries=[e.to_core() for e in self.entries],
            removed_entry_ids=list(self.removed_entry_ids),
            reresolve_all=self.reresolve_all,
            versions=dict(self.versions),
        )


# ---- the answer ---------------------------------------------------------------------------------


class UnitKeyOut(BaseModel):
    """A derivation key: the pass and its basis (a `user` key's basis is the proposal it accepted)."""

    model_config = ConfigDict(populate_by_name=True)

    pass_: str = Field(alias="pass")
    basis: dict[str, Any]

    @staticmethod
    def of(key: Any) -> UnitKeyOut | None:
        if not isinstance(key, dict):
            return None
        basis = key.get("basis")
        return UnitKeyOut.model_validate(
            {"pass": str(key.get("pass", "")), "basis": dict(basis) if isinstance(basis, dict) else {}}
        )


class UnitStoredFieldOut(BaseModel):
    value: int | str | None
    key: UnitKeyOut | None


class UnitFieldOut(BaseModel):
    """One derived field of a row as the draft leaves it."""

    value: int | str | None
    key: UnitKeyOut | None  # how resolution arrived at it: a proposal while no human has accepted it
    is_proposal: bool  # `key` is a proposal (history, llm, matcher_proposal)
    commit_key: UnitKeyOut | None  # the key stored once the draft is committed and settled
    stored: UnitStoredFieldOut | None  # the stored value beside the draft's; null for a row the draft creates

    @staticmethod
    def of(f: FieldResult, *, stored: bool) -> UnitFieldOut:
        from app.core.plugins.classifier import STANDING_PASSES

        key = None
        if f.evidence is not None:
            key = UnitKeyOut.model_validate({"pass": f.evidence.pass_name, "basis": dict(f.evidence.basis)})
        return UnitFieldOut(
            value=f.value,
            key=key,
            is_proposal=f.evidence is not None and f.evidence.pass_name not in STANDING_PASSES,
            commit_key=UnitKeyOut.of(f.key),
            stored=UnitStoredFieldOut(value=f.stored_value, key=UnitKeyOut.of(f.stored_key))
            if stored
            else None,
        )


class UnitStoredRowOut(BaseModel):
    amount: Money
    description: str | None
    note: str | None


class UnitPreviewRowOut(BaseModel):
    id: int  # stored, or the client's temporary (negative) id
    version: int | None  # null for a row the draft creates
    source_transaction_id: int
    unit_key: int
    in_unit: bool  # in the anchor's unit once the draft is applied
    original: bool  # the residual of its source transaction
    account_id: int
    booked_on: date
    value_on: date | None
    amount: Money
    description: str | None
    note: str | None
    tag_ids: list[int]
    counterpart_entry_id: int | None
    fields: dict[FieldName, UnitFieldOut]
    review_flags: list[str]
    derivation: dict[str, Any]  # as stored once committed and settled
    stored: UnitStoredRowOut | None

    @staticmethod
    def of(r: PlannedRow) -> UnitPreviewRowOut:
        s = r.stored
        return UnitPreviewRowOut(
            id=r.id,
            version=r.version,
            source_transaction_id=r.source_transaction_id,
            unit_key=r.unit_key,
            in_unit=r.in_unit,
            original=r.original,
            account_id=r.account_id,
            booked_on=r.booked_on,
            value_on=r.value_on,
            amount=Money(amount=r.amount, currency=r.currency),
            description=r.description,
            note=r.note,
            tag_ids=list(r.tag_ids),
            counterpart_entry_id=r.counterpart_entry_id,
            fields={n: UnitFieldOut.of(f, stored=s is not None) for n, f in r.fields.items()},
            review_flags=list(r.flags),
            derivation=dict(r.derivation),
            stored=None
            if s is None
            else UnitStoredRowOut(
                amount=Money(amount=s.amount, currency=s.currency), description=s.description, note=s.note
            ),
        )

    @staticmethod
    def of_stored(s: Stored, unit_key: int) -> UnitPreviewRowOut:
        """A stored entry the draft removes: the row as it was."""
        fields = {
            "type": s.type,
            "payee": s.payee_id,
            "category": s.category_id,
            "counter_account": s.counter_account_id,
        }
        return UnitPreviewRowOut(
            id=s.id,
            version=s.version,
            source_transaction_id=s.source_transaction_id,
            unit_key=unit_key,
            in_unit=False,
            original=False,
            account_id=s.account_id,
            booked_on=s.booked_on,
            value_on=s.value_on,
            amount=Money(amount=s.amount, currency=s.currency),
            description=s.description,
            note=s.note,
            tag_ids=list(s.tag_ids),
            counterpart_entry_id=s.counterpart_entry_id,
            fields={
                n: UnitFieldOut(  # type: ignore[misc]
                    value=v,
                    key=UnitKeyOut.of(s.derivation.get(n)),
                    is_proposal=False,
                    commit_key=None,
                    stored=UnitStoredFieldOut(value=v, key=UnitKeyOut.of(s.derivation.get(n))),
                )
                for n, v in fields.items()
            },
            review_flags=[],
            derivation=dict(s.derivation),
            stored=UnitStoredRowOut(
                amount=Money(amount=s.amount, currency=s.currency), description=s.description, note=s.note
            ),
        )


class UnitStateOut(BaseModel):
    confirmed: bool
    reasons: list[UnitReason]

    @staticmethod
    def of(state: UnitState) -> UnitStateOut:
        return UnitStateOut(confirmed=state.confirmed, reasons=list(state.reasons))


class UnitPlannedOut(BaseModel):
    anchor_entry_id: int  # the lowest stored entry id of the unit
    unit_key: int
    entry_ids: list[int]  # stored ids ascending, then temporary ids in draft order
    state: UnitStateOut

    @staticmethod
    def of(u: PlannedUnit) -> UnitPlannedOut:
        return UnitPlannedOut(
            anchor_entry_id=u.anchor_entry_id,
            unit_key=u.unit_key,
            entry_ids=list(u.entry_ids),
            state=UnitStateOut.of(u.state),
        )


class UnitSplitOut(BaseModel):
    """One source transaction's allocation: the residual is its original entry."""

    source_transaction_id: int
    source_amount: Money
    residual_entry_id: int
    residual_amount: Money
    entry_ids: list[int]

    @staticmethod
    def of(s: Split, currency: str) -> UnitSplitOut:
        return UnitSplitOut(
            source_transaction_id=s.source_transaction_id,
            source_amount=Money(amount=s.source_amount, currency=currency),
            residual_entry_id=s.residual_entry_id,
            residual_amount=Money(amount=s.residual_amount, currency=currency),
            entry_ids=list(s.entry_ids),
        )


class UnitProblemOut(BaseModel):
    """A way the result would break an invariant (a commit is refused for it): a code, never prose."""

    code: str
    entry_id: int | None
    field: str | None
    detail: dict[str, int | str | None]

    @staticmethod
    def of(p: Problem) -> UnitProblemOut:
        return UnitProblemOut(code=p.code, entry_id=p.entry_id, field=p.field, detail=dict(p.detail))


class UnitConsequenceOut(BaseModel):
    entry_id: int
    kind: ConsequenceKind
    version: int | None  # the stored version; null for a row the draft creates
    row: UnitPreviewRowOut  # the row as the draft leaves it (a deleted entry: as it was)

    @staticmethod
    def of(c: Consequence, plan: Plan, stored: StoredUnit | None = None) -> UnitConsequenceOut:
        if c.kind == "deleted":
            entry = next(e for e in plan.removed if e.id == c.entry_id)
            row = UnitPreviewRowOut.of_stored(entry, plan.anchor_unit.unit_key)
            return UnitConsequenceOut(entry_id=c.entry_id, kind=c.kind, version=entry.version, row=row)
        planned = plan.row(c.entry_id)
        return UnitConsequenceOut(
            entry_id=c.entry_id, kind=c.kind, version=planned.version, row=UnitPreviewRowOut.of(planned)
        )


class UnitPreviewOut(BaseModel):
    """What committing the draft would do. Nothing was written."""

    state: UnitStateOut  # the anchor's unit as it will stand: what the commit leads to
    units: list[UnitPlannedOut]  # every unit the draft leaves (a pair that no longer exists is two)
    rows: list[UnitPreviewRowOut]  # stored ascending, then the new rows in draft order
    splits: list[UnitSplitOut]
    problems: list[UnitProblemOut]  # empty: a commit is not refused for an invariant
    consequences: list[UnitConsequenceOut]
    versions: dict[int, int]  # every entry a commit writes, with its version: send them back

    @staticmethod
    def of(plan: Plan) -> UnitPreviewOut:
        currency = {r.source_transaction_id: r.currency for r in plan.rows}
        return UnitPreviewOut(
            state=UnitStateOut.of(plan.anchor_unit.state),
            units=[UnitPlannedOut.of(u) for u in plan.units],
            rows=[UnitPreviewRowOut.of(r) for r in plan.rows],
            splits=[UnitSplitOut.of(s, currency[s.source_transaction_id]) for s in plan.splits],
            problems=[UnitProblemOut.of(p) for p in plan.problems],
            consequences=[UnitConsequenceOut.of(c, plan) for c in plan.consequences],
            versions=dict(plan.versions),
        )


class UnitCommittedOut(BaseModel):
    anchor_entry_id: int
    entry_ids: list[int]  # real ids
    state: UnitStateOut


class UnitCommitConsequenceOut(BaseModel):
    entry_id: int  # a real id
    kind: ConsequenceKind


class UnitCommitOut(BaseModel):
    """Everything the commit touched, as rows (architecture §4.1): the client patches what comes back."""

    created: dict[int, int]  # the draft's temporary id -> the real id
    removed_entry_ids: list[int]
    entries: list[EntryOut]  # the unit, its consequences and the partners' rows, then settle-touched rows
    other_entry_ids: list[int]  # settle-touched entries beyond the rows above (their rows are refetched)
    truncated: bool  # `other_entry_ids` is itself cut short
    units: list[UnitCommittedOut]
    consequences: list[UnitCommitConsequenceOut]
    settle: SettleOut

    @staticmethod
    def of(r: CommitResult) -> UnitCommitOut:
        return UnitCommitOut(
            created=dict(r.created),
            removed_entry_ids=list(r.removed_entry_ids),
            entries=[EntryOut.of(e) for e in r.entries],
            other_entry_ids=list(r.other_entry_ids),
            truncated=r.truncated,
            units=[
                UnitCommittedOut(
                    anchor_entry_id=u.anchor_entry_id,
                    entry_ids=list(u.entry_ids),
                    state=UnitStateOut.of(u.state),
                )
                for u in r.units
            ],
            consequences=[UnitCommitConsequenceOut(entry_id=c.entry_id, kind=c.kind) for c in r.consequences],
            settle=SettleOut.of(r.settle),
        )
