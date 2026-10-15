"""The records of a unit plan (spec §6): what is stored, what the passes need, and what a draft implies.

Pure data. `overlay.plan_unit` takes a `StoredUnit` and a `World` and returns a `Plan`; the preview renders
the plan and the commit writes it. Nothing here reads or writes the database (`stored.py` loads, `commit.py`
writes).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from app.core.matching import Leg, Offer, PoolEntry, Proposal
from app.core.plugins.classifier import AccountFact, Classifier, Field
from app.core.resolution.snapshot import HistorySnapshot
from app.core.resolution.types import Decided
from app.core.units.state import UnitState

# ---- what is stored -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StoredSource:
    """The source transaction of a unit's entries: its amount and what resolution reads of it."""

    id: int
    amount: int
    account_id: int
    currency: str
    booked_on: date
    value_on: date | None
    user_authored: bool
    counterparty_ref: str | None = None
    counterparty_name: str | None = None
    purpose: str | None = None
    booking_text: str | None = None
    mandate_ref: str | None = None
    instructed_currency: str | None = None
    end_to_end_id: str | None = None
    instructed_amount: int | None = None


@dataclass(frozen=True, slots=True)
class Stored:
    """One stored entry of the unit's closure, as the overlay reads it."""

    id: int
    version: int
    source_transaction_id: int
    account_id: int
    currency: str
    booked_on: date
    value_on: date | None
    amount: int
    type: str | None
    payee_id: int | None
    category_id: int | None
    counter_account_id: int | None
    counterpart_entry_id: int | None
    description: str | None
    note: str | None
    derivation: Mapping[str, Any]
    tag_ids: tuple[int, ...] = ()
    document_id: int | None = None


@dataclass(frozen=True, slots=True)
class StoredUnit:
    """The closure of the anchor, as stored: every entry of its source and of its partner's source."""

    anchor_entry_id: int
    sources: Mapping[int, StoredSource]
    entries: tuple[Stored, ...]  # ascending by id

    def entry(self, entry_id: int) -> Stored | None:
        for e in self.entries:
            if e.id == entry_id:
                return e
        return None

    def original_of(self, source_id: int) -> int:
        """The entry the source's split keeps as its residual: the lowest stored id of the source."""
        return min(e.id for e in self.entries if e.source_transaction_id == source_id)


@dataclass(slots=True)
class World:
    """What resolution needs besides the unit: accounts, the classifiers, the history without the unit.

    `history` is a snapshot of the votes OTHER than the closure's entries, and is extended in place by the
    overlay as the plan's units become confirmed (settling teaches history the same way). `categories` and
    `payees` are the ids the draft names that exist; an id the draft names that is not here is stale.
    """

    accounts: Sequence[AccountFact]
    classifiers: Sequence[Classifier]
    history: HistorySnapshot
    categories: frozenset[int] = frozenset()
    payees: frozenset[int] = frozenset()
    # what `waiting` and `unmatched_transfer` read (spec §5.7): per account whether it is synced and its
    # `synced_through`, and the matching window.
    account_sync: Mapping[int, tuple[bool, date | None]] = dataclasses.field(default_factory=dict)
    matching_window: int = 0
    # the preview only: every unpaired transfer leg of the ledger, so the simulation of settling pairs a leg
    # of the plan with one outside it as settling will (a commit does not load them: settling follows it)
    ledger_legs: Sequence[Leg] = ()
    # the preview only: the movements offers are made of, read after the plan (`transfers.attach_transfers`)
    pool: Sequence[PoolEntry] = ()


# ---- what a draft implies -----------------------------------------------------------------------

PROBLEM_CODES = (
    "amount_zero",
    "residual_zero",
    "residual_sign_flip",
    "second_transfer",
    "new_entry_not_flow",
    "type_conflict",
    "currency_rule",
    "own_counter_account",
    "pair_unequal",
    "pair_sign",
    "split_sum",
    "stale_reference",
)


@dataclass(frozen=True, slots=True)
class Problem:
    """A way the result would break an invariant: a commit is refused for it. Codes, never prose."""

    code: str
    entry_id: int | None = None
    field: str | None = None
    detail: Mapping[str, int | str | None] = dataclasses.field(default_factory=dict)


ConsequenceKind = Literal["created", "changed", "returns_to_review", "deleted", "unpaired", "left_behind"]


@dataclass(frozen=True, slots=True)
class Consequence:
    entry_id: int
    kind: ConsequenceKind


@dataclass(frozen=True, slots=True)
class FieldResult:
    """One derived field of a planned row."""

    value: int | str | None
    evidence: (
        Decided | None
    )  # the key resolution gave the value: a proposal while a human has not accepted it
    key: Mapping[str, Any] | None  # the key stored once the draft is committed and settled
    stored_value: int | str | None  # the stored value beside it (None for a created row)
    stored_key: Mapping[str, Any] | None


@dataclass(frozen=True, slots=True)
class Written:
    """What a commit writes on a row (settling follows and may rewrite proposals of an unconfirmed unit)."""

    type: str | None
    payee_id: int | None
    category_id: int | None
    counter_account_id: int | None
    counterpart_entry_id: int | None
    amount: int
    description: str | None
    note: str | None
    derivation: Mapping[str, Any]
    accepted: bool  # the draft's entry: its values are written; False: only a pair released is written


TransferState = Literal["paired", "waiting", "unmatched", "needs_account"]


@dataclass(frozen=True, slots=True)
class WaitingFor:
    account_id: int
    synced_through: date | None  # how far that account has been fetched; None = never


@dataclass(frozen=True, slots=True)
class PartnerView:
    entry_id: int
    account_id: int
    booked_on: date
    amount: int
    currency: str
    description: str | None


@dataclass(frozen=True, slots=True)
class TransferView:
    """What the preview says of a transfer leg (spec §5.7): its state, its partner and its offers."""

    state: TransferState
    waiting_for: WaitingFor | None
    needs_account: str | None  # the currency it needs an account in
    partner: PartnerView | None
    offers: tuple[Offer, ...]
    proposal: Proposal | None
    has_more: bool


@dataclass(frozen=True, slots=True)
class PlannedRow:
    id: int  # stored, or the client's temporary (negative) id
    version: int | None  # None for a row the draft creates
    stored: Stored | None
    source_transaction_id: int
    unit_key: int
    in_unit: bool  # the anchor's unit once the draft is applied (False: left behind, or on a split-off side)
    account_id: int
    currency: str
    booked_on: date
    value_on: date | None
    amount: int
    description: str | None
    note: str | None
    tag_ids: tuple[int, ...]
    counterpart_entry_id: int | None
    fields: Mapping[Field, FieldResult]
    derivation: Mapping[str, Any]  # as stored after the commit and the settle that follows
    flags: tuple[str, ...]
    written: Written
    original: bool  # the residual of its source
    leg: Leg | None = None  # the matcher's view of the row as planned (offers are made for it)
    purpose: str | None = None  # the source's purpose as stored


@dataclass(frozen=True, slots=True)
class PlannedUnit:
    anchor_entry_id: int  # the lowest stored entry id of the unit
    unit_key: int
    entry_ids: tuple[int, ...]  # ascending by stored id, then the new rows in draft order
    state: UnitState


@dataclass(frozen=True, slots=True)
class Split:
    """One source transaction's allocation after the draft."""

    source_transaction_id: int
    source_amount: int
    residual_entry_id: int
    residual_amount: int
    entry_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Plan:
    rows: tuple[PlannedRow, ...]
    removed: tuple[Stored, ...]
    unpaired_entry_ids: tuple[int, ...]  # stored entries that lose their counterpart
    units: tuple[PlannedUnit, ...]
    anchor_unit: PlannedUnit
    splits: tuple[Split, ...]
    problems: tuple[Problem, ...]
    consequences: tuple[Consequence, ...]
    versions: Mapping[int, int]  # every stored entry of the closure: what a commit must carry
    created_ids: tuple[int, ...]  # the draft's temporary ids, in draft order
    # legs outside the closure that the simulation of settling paired with a row of the plan: the preview
    # reads their units and plans again (a commit never has any: its world holds no ledger legs)
    pulled_entry_ids: tuple[int, ...] = ()
    transfers: Mapping[int, TransferView] = dataclasses.field(default_factory=dict)  # by row id

    def row(self, entry_id: int) -> PlannedRow:
        for r in self.rows:
            if r.id == entry_id:
                return r
        raise KeyError(entry_id)
