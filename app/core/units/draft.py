"""The draft of a unit (spec §6, architecture §4.1): the user's choices, laid over the stored state.

Pure records, no database. A draft names the unit by its anchor entry and lists what the user changed:
an entry's allocation, text and derived fields, the rows a split creates (client-issued NEGATIVE ids, which
preview echoes and commit maps to real ones) and the rows it removes. Nothing here says what those choices
imply: `overlay.plan_unit` lays the draft over the stored unit and returns that.

A derived field (`type`, `payee`, `category`, `counter_account`) is drafted as a `FieldDraft`:

* ``keep`` - not touched by the user. It is what the unit's stored values and the passes make of it now:
  a standing value stays, a proposal is resolved afresh (spec §5.9 "Rederiving"). A commit accepts it.
* ``fixed`` - the user's value (``None`` leaves the field empty). It is decided: the fields after it resolve
  around it. `shown_basis` names the proposal the value was accepted from, if the client showed one.
* ``reresolve`` - "reset to proposal": the passes decide this field afresh, a decided value included.

`UnitDraft.reresolve_all` makes every ``keep`` field ``reresolve``: the whole unit resolved afresh (§5.9).

Not modelled yet, on purpose: picking a partner, offers, counter-legs, documents (steps 8 and 9).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from app.core.plugins.classifier import Field

Mode = Literal["keep", "fixed", "reresolve"]
MODES: Final[tuple[Mode, ...]] = ("keep", "fixed", "reresolve")
# the proposal passes a client may name as the basis of a value it accepted (spec §5.9)
PROPOSAL_PASSES: Final = frozenset({"history", "llm", "matcher_proposal"})
DERIVED_FIELDS: Final[tuple[Field, ...]] = ("type", "payee", "category", "counter_account")
TYPES: Final = ("flow", "transfer")


class DraftError(Exception):
    """A draft that makes no sense against the stored unit, whatever it would write (a 422).

    `code` is a stable machine code; `entry_id` and `field` locate it. Never prose to match on.
    """

    def __init__(self, code: str, message: str, *, entry_id: int | None = None, field: str | None = None):
        super().__init__(message)
        self.code = code
        self.entry_id = entry_id
        self.field = field


class _Unset:
    """The text of an entry the draft leaves as stored (None would mean 'make it empty')."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "UNSET"


UNSET: Final = _Unset()


@dataclass(frozen=True, slots=True)
class ShownBasis:
    """The key of the proposal the client showed for a value: `{"pass", "basis"}`, never evidence."""

    pass_name: str
    basis: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.pass_name not in PROPOSAL_PASSES:
            raise DraftError(
                "invalid_basis",
                "a basis may name only a proposal pass: history, llm or matcher_proposal",
            )


@dataclass(frozen=True, slots=True)
class FieldDraft:
    mode: Mode = "keep"
    value: int | str | None = None  # a type, or an id of a payee, category or account; fixed only
    shown_basis: ShownBasis | None = None

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise DraftError("invalid_mode", f"unknown mode {self.mode!r}")
        if self.mode != "fixed" and (self.value is not None or self.shown_basis is not None):
            raise DraftError("invalid_field", "only a fixed field carries a value")


KEEP: Final = FieldDraft()


@dataclass(frozen=True, slots=True)
class DraftEntry:
    """One entry of the unit, as the draft would have it.

    `id` is a stored entry id (positive) or the client's temporary id of a row the draft creates
    (negative). `amount` is the entry's allocation of its source transaction; the source's original entry
    (its lowest id) is the residual and takes whatever the others leave, so its amount is never drafted.
    A new entry names `source_entry_id`, a stored entry of the source it splits.
    """

    id: int
    amount: int | None = None
    description: str | None | _Unset = UNSET
    note: str | None | _Unset = UNSET
    type: FieldDraft = KEEP
    payee: FieldDraft = KEEP
    category: FieldDraft = KEEP
    counter_account: FieldDraft = KEEP
    source_entry_id: int | None = None

    @property
    def is_new(self) -> bool:
        return self.id < 0

    def field(self, name: Field) -> FieldDraft:
        match name:
            case "type":
                return self.type
            case "payee":
                return self.payee
            case "category":
                return self.category
            case "counter_account":
                return self.counter_account

    def __post_init__(self) -> None:
        if self.id == 0:
            raise DraftError("invalid_entry_id", "an entry id is stored (positive) or temporary (negative)")
        if self.amount == 0:
            raise DraftError("amount_zero", "an entry has a non-zero amount", entry_id=self.id)
        if self.is_new != (self.source_entry_id is not None):
            raise DraftError(
                "invalid_new_entry",
                "a new entry names the stored entry of the source it splits; a stored entry does not",
                entry_id=self.id,
            )
        if self.is_new and self.amount is None:
            raise DraftError("amount_missing", "a new entry carries its amount", entry_id=self.id)
        for name in DERIVED_FIELDS:
            d = self.field(name)
            if d.mode != "fixed":
                continue
            if name == "type":
                if d.value not in TYPES:
                    raise DraftError(
                        "invalid_type", "a type is flow or transfer", entry_id=self.id, field=name
                    )
            elif d.value is not None and (
                not isinstance(d.value, int) or isinstance(d.value, bool) or d.value <= 0
            ):
                raise DraftError("invalid_value", f"{name} is an id or empty", entry_id=self.id, field=name)


@dataclass(frozen=True, slots=True)
class UnitDraft:
    """The draft of the unit anchored on `anchor_entry_id`.

    A stored entry of the unit that `entries` does not list is as if listed with every field ``keep``.
    `versions` are the entry versions the client saw (a commit carries them; a preview ignores them).
    """

    anchor_entry_id: int
    entries: Sequence[DraftEntry] = ()
    removed_entry_ids: Sequence[int] = ()
    reresolve_all: bool = False
    versions: Mapping[int, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.anchor_entry_id <= 0:
            raise DraftError("invalid_anchor", "the anchor is a stored entry")
        ids = [e.id for e in self.entries]
        if len(set(ids)) != len(ids):
            dup = sorted({i for i in ids if ids.count(i) > 1})
            raise DraftError("duplicate_entry", "an entry is listed twice", entry_id=dup[0])
        if len(set(self.removed_entry_ids)) != len(self.removed_entry_ids):
            raise DraftError("duplicate_entry", "an entry is removed twice")
        for rid in self.removed_entry_ids:
            if rid <= 0:
                raise DraftError("unknown_entry", "only a stored entry is removed", entry_id=rid)
            if rid in ids:
                raise DraftError("removed_and_edited", "an entry is removed and edited", entry_id=rid)
            if rid == self.anchor_entry_id:
                raise DraftError("anchor_removed", "the anchor entry is not removed", entry_id=rid)

    def entry(self, entry_id: int) -> DraftEntry | None:
        for e in self.entries:
            if e.id == entry_id:
                return e
        return None
