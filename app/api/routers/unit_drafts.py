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
from app.core.matching import Offer
from app.core.units.commit import CommitResult
from app.core.units.draft import UNSET, DraftEntry, FieldDraft, PairingDraft, ShownBasis, UnitDraft
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
    TransferView,
)
from app.core.units.state import UnitState

UnitReason = Literal[
    "incomplete", "unpaired_transfer", "waiting_for_partner", "unmatched_transfer", "non_standing_keys"
]
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


class UnitPairingIn(BaseModel):
    """What the draft says of a transfer leg's partner (spec §5.7). `keep` (also: absent) leaves it, and a
    commit accepts the proposal the preview shows. `pick` names a stored partner entry (`partner_entry_id`,
    positive): it must be an offer of the leg, else the preview lists the problem `partner_not_offered` or
    `partner_in_unit`. `reresolve` drops the stored pair and lets the passes decide again. A `pairing` on an
    entry that is not a transfer leg, or a negative id, is 422 `invalid_draft`."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["keep", "pick", "reresolve"] = "keep"
    partner_entry_id: TempOrStoredId | None = None

    def to_core(self) -> PairingDraft:
        return PairingDraft(self.mode, self.partner_entry_id)


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
    pairing: UnitPairingIn = Field(default_factory=UnitPairingIn)
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
            pairing=self.pairing.to_core(),
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

    def to_core(self, window_days: int | None = None) -> UnitDraft:
        return UnitDraft(
            window_days=window_days,
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


class UnitPartnerOut(BaseModel):
    """A leg in a few words: the partner of a leg, or the one a leg paired elsewhere is paired with."""

    entry_id: int
    account_id: int
    booked_on: date
    amount: Money
    description: str | None


class UnitOfferFeeOut(BaseModel):
    larger_entry_id: int  # the leg the difference is split off, as a new flow entry
    difference: Money  # positive, in the currency of both legs


class UnitOfferEffectOut(BaseModel):
    """What picking the offer would also do (the real consequences show after the pick)."""

    types_as_transfer: bool  # an untyped entry becomes a transfer
    fee: UnitOfferFeeOut | None  # a same-currency offer of another amount: the difference becomes a flow
    breaks_pair_with: list[int]  # the entries whose pair the pick breaks (the leg's own, the picked leg's)


class UnitCounterLegOut(BaseModel):
    """The counter-leg a commit would create on the offer's account (an unsynced one)."""

    booked_on: date
    purpose: str | None
    amount: Money | None  # null: the user types the amount received (`needs_received_amount`)
    needs_received_amount: bool


class UnitOfferOut(BaseModel):
    """A partner a transfer leg may be given. The groups come in this order: open offers (`open_leg`,
    `untyped_entry`), legs paired elsewhere, the counter-leg; within the first two, exact amounts first,
    then by date distance (earlier `booked_on`, then lower id on a tie)."""

    kind: Literal["open_leg", "untyped_entry", "paired_elsewhere", "counter_leg"]
    entry_id: int | None  # null for the counter-leg: it does not exist yet
    account_id: int
    booked_on: date
    amount: Money | None  # null only for a counter-leg that needs the amount received
    description: str | None
    exact: bool  # equal and opposite, or across currencies one leg's instructed amount
    proposed: bool  # the preview's preselection (a `user` decision once committed; never stored)
    paired_with: UnitPartnerOut | None  # the partner of a leg paired elsewhere
    effect: UnitOfferEffectOut
    counter_leg: UnitCounterLegOut | None

    @staticmethod
    def of(o: Offer) -> UnitOfferOut:
        def money(amount: int | None) -> Money | None:
            return None if amount is None else Money(amount=amount, currency=o.currency)

        paired = o.paired_with
        fee = o.effect.fee
        cl = o.counter_leg
        return UnitOfferOut(
            kind=o.kind,
            entry_id=o.entry_id,
            account_id=o.account_id,
            booked_on=o.booked_on,
            amount=money(o.amount),
            description=o.description,
            exact=o.exact,
            proposed=o.proposed,
            paired_with=None
            if paired is None
            else UnitPartnerOut(
                entry_id=paired.entry_id,
                account_id=paired.account_id,
                booked_on=paired.booked_on,
                amount=Money(amount=paired.amount, currency=paired.currency),
                description=paired.description,
            ),
            effect=UnitOfferEffectOut(
                types_as_transfer=o.effect.types_as_transfer,
                fee=None
                if fee is None
                else UnitOfferFeeOut(
                    larger_entry_id=fee.larger_entry_id,
                    difference=Money(amount=fee.difference, currency=fee.currency),
                ),
                breaks_pair_with=list(o.effect.breaks_pair_with),
            ),
            counter_leg=None
            if cl is None
            else UnitCounterLegOut(
                booked_on=cl.booked_on,
                purpose=cl.purpose,
                amount=None if cl.amount is None else Money(amount=cl.amount, currency=cl.currency),
                needs_received_amount=cl.needs_received_amount,
            ),
        )


class UnitProposalOut(BaseModel):
    kind: Literal["entry", "counter_leg"]
    entry_id: int | None  # the offer's entry; null for the counter-leg


class UnitProposedPickOut(BaseModel):
    entry_id: int  # the partner the preview took the leg's proposal to be: the leg shows that pair


class UnitWaitingForOut(BaseModel):
    account_id: int  # the counter-account the partner is awaited from
    synced_through: date | None  # how far that account has been fetched; null = never


class UnitNeedsAccountOut(BaseModel):
    currency: str  # the currency the leg needs an account in


class UnitTransferOut(BaseModel):
    """A transfer leg as the draft leaves it (spec §5.7): its state, partner and offers, computed now."""

    state: Literal["paired", "waiting", "unmatched", "needs_account"]
    waiting_for: UnitWaitingForOut | None  # state `waiting`
    needs_account: UnitNeedsAccountOut | None  # state `needs_account`
    partner: UnitPartnerOut | None  # state `paired`
    offers: list[UnitOfferOut]
    proposal: UnitProposalOut | None  # what the preview preselects; none for a leg with a partner of its own
    has_more: bool  # more candidates exist beyond the window, up to the widest a pick may ask for (90)
    # set where the preview took the leg's proposal (an exact open offer) to be the pick: the leg is then
    # `paired` with that partner and `offers` / `proposal` are the ones it had before (the proposed offer
    # first); a commit accepts it as the user's decision. An explicit pick in the draft overrides it, and
    # `pairing: reresolve` takes the proposal afresh.
    proposed_pick: UnitProposedPickOut | None = None

    @staticmethod
    def of(t: TransferView) -> UnitTransferOut:
        return UnitTransferOut(
            state=t.state,
            waiting_for=None
            if t.waiting_for is None
            else UnitWaitingForOut(
                account_id=t.waiting_for.account_id, synced_through=t.waiting_for.synced_through
            ),
            needs_account=None if t.needs_account is None else UnitNeedsAccountOut(currency=t.needs_account),
            partner=None
            if t.partner is None
            else UnitPartnerOut(
                entry_id=t.partner.entry_id,
                account_id=t.partner.account_id,
                booked_on=t.partner.booked_on,
                amount=Money(amount=t.partner.amount, currency=t.partner.currency),
                description=t.partner.description,
            ),
            offers=[UnitOfferOut.of(o) for o in t.offers],
            proposal=None
            if t.proposal is None
            else UnitProposalOut(kind=t.proposal.kind, entry_id=t.proposal.entry_id),
            has_more=t.has_more,
            proposed_pick=None if t.proposed_pick is None else UnitProposedPickOut(entry_id=t.proposed_pick),
        )


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
    transfer: UnitTransferOut | None = None  # a row that is a transfer leg: its state, partner, offers

    @staticmethod
    def of(r: PlannedRow, transfer: TransferView | None = None) -> UnitPreviewRowOut:
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
            transfer=None if transfer is None else UnitTransferOut.of(transfer),
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


class UnitSuggestedSplitOut(BaseModel):
    """How a `pair_unequal` is fixed: a new flow entry of `amount` (signed like the larger leg) split off the
    larger leg's source, named by one of its stored entries (`source_entry_id`)."""

    source_entry_id: int
    amount: Money


class UnitProblemOut(BaseModel):
    """A way the result would break an invariant (a commit is refused for it): a code, never prose."""

    code: str
    entry_id: int | None
    field: str | None
    detail: dict[str, int | str | None]
    suggested_split: UnitSuggestedSplitOut | None = None  # `pair_unequal` only

    @staticmethod
    def of(p: Problem, currency: str | None = None) -> UnitProblemOut:
        split = p.suggested_split
        return UnitProblemOut(
            code=p.code,
            entry_id=p.entry_id,
            field=p.field,
            detail=dict(p.detail),
            suggested_split=None
            if split is None or currency is None
            else UnitSuggestedSplitOut(
                source_entry_id=split.source_entry_id, amount=Money(amount=split.amount, currency=currency)
            ),
        )


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


def _problem_currency(p: Problem, plan: Plan) -> str | None:
    """The currency of a problem's split: the one of the larger leg's source (both legs share it)."""
    if p.suggested_split is None:
        return None
    return next((r.currency for r in plan.rows if r.id == p.suggested_split.source_entry_id), None)


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
            rows=[UnitPreviewRowOut.of(r, plan.transfers.get(r.id)) for r in plan.rows],
            splits=[UnitSplitOut.of(s, currency[s.source_transaction_id]) for s in plan.splits],
            problems=[UnitProblemOut.of(p, _problem_currency(p, plan)) for p in plan.problems],
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
