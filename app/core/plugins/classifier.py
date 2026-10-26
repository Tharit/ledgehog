"""The classifier protocol and the records it exchanges with `core/resolution` (architecture §5.4).

Pure data and protocols, no behaviour: passes 1 to 3 of spec §5.9 implement `Classifier`, core
hands them their evidence (`ClassifierContext`) and writes what they propose. Classifiers never
touch the database. Ids only, never names: a proposal can reference what exists, nothing else.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal, Protocol

# The fields resolution decides, in the order of spec §5.9 "Field order".
Field = Literal["type", "payee", "category", "counter_account"]
FIELD_ORDER: tuple[Field, ...] = ("type", "payee", "category", "counter_account")

# The fields that may be empty (spec §5.9, field order: "empty is a value"): the one place that says so. The
# payee may; a type, a category and a counter-account may not, because without them an entry is not complete.
MAY_BE_EMPTY: frozenset[Field] = frozenset({"payee"})

# The value of a Proposal that says "the field is empty" (history.md §3, e.g. the majority has no payee): an
# empty result, valid only on a field that may be empty. It ends the search for the field with nothing stored
# and no key (spec §5.9). A proposal with no value at all is something else: an explained absence.
EMPTY = "none"

# `derivation` pass names (spec §5.9). Standing: own_account, rule, matcher_decision (a pair settling made),
# booking (what settling's booking step fixes), user. Proposals: history, llm.
STANDING_PASSES = frozenset({"own_account", "rule", "matcher_decision", "booking", "user"})

# the history keys of spec §5.9 / classifiers/history.md, in order. The booking text is never a key on its
# own; it only refines key 2. (Key 5, the entry's source text, is added with its use.)
HistoryKey = Literal["counterparty_ref", "counterparty_name", "payee", "tokens"]
HISTORY_KEYS: tuple[HistoryKey, ...] = (
    "counterparty_ref",
    "counterparty_name",
    "payee",
    "tokens",
)


@dataclass(frozen=True, slots=True)
class EntryInput:
    """What resolution reads about one entry: its source transaction and its own columns.

    Raw source strings as stored (never canonicalised here); a manual entry has none of them.
    `user_authored` is true when the entry's source has the origin `user` (spec §5.9: a user-authored entry
    still resolves, from what it has).
    """

    entry_id: int
    account_id: int
    currency: str
    booked_on: date
    amount: int
    user_authored: bool = False
    counterparty_ref: str | None = None
    counterparty_name: str | None = None
    purpose: str | None = None
    booking_text: str | None = None
    mandate_ref: str | None = None
    instructed_currency: str | None = None
    end_to_end_id: str | None = None
    instructed_amount: int | None = None  # signed minor units, in `instructed_currency`
    # the kind of source its booking was made from (`document` or `transfer`), None for an entry that is not a
    # booking's: a booking decides the type first, under the key `booking` (spec §5.9)
    booking: str | None = None


@dataclass(frozen=True, slots=True)
class AccountFact:
    """The account facts resolution needs; `external_ref` is stored canonicalised (accounts.py)."""

    id: int
    currency: str
    external_ref: str | None
    closed_on: date | None = None
    # a clearance account (spec §3.3): its movements are bookings, so none is ever a transfer leg's partner
    # or a candidate, and no pass proposes `transfer` for an entry on it (spec §5.7)
    clearance: bool = False


ConditionField = Literal[
    "counterparty_name",
    "counterparty_ref",
    "purpose",
    "booking_text",
    "mandate_ref",
    "payee",
]
ConditionOp = Literal["equals", "starts_with", "contains", "regex", "is"]
CONDITION_FIELDS: tuple[ConditionField, ...] = (
    "counterparty_name",
    "counterparty_ref",
    "purpose",
    "booking_text",
    "mandate_ref",
    "payee",
)
CONDITION_OPS: tuple[ConditionOp, ...] = ("equals", "starts_with", "contains", "regex", "is")
# `payee` (the id of the payee resolved so far, as a digit string) takes `is` only; the others the rest
PAYEE_FIELD: ConditionField = "payee"
TEXT_OPS: tuple[ConditionOp, ...] = ("equals", "starts_with", "contains", "regex")


@dataclass(frozen=True, slots=True)
class Condition:
    """One `{field, op, value}` of a rule (spec §5.9, classifiers/rules.md §2): as the user typed it."""

    field: ConditionField
    op: ConditionOp
    value: str


@dataclass(frozen=True, slots=True)
class RuleSpec:
    """One row of `rule`. `target_id` is the id of what the rule sets, by `sets`.

    All `conditions` must hold; a category rule's may include `payee` conditions.
    """

    id: int
    name: str
    sets: Literal["counter_account", "payee", "category"]
    target_id: int
    priority: int = 100
    conditions: tuple[Condition, ...] = ()


class RuleInvalid(ValueError):
    """A rule that cannot be saved (rules.md §3). `field` names the part of the rule at fault; the
    message states the rule and never quotes a pattern or a value the user typed."""

    def __init__(self, message: str, field: str = "rule") -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True, slots=True)
class Proposal:
    """A classifier's answer for one field: the value (an id, or `"flow"`/`"transfer"` for the
    type) and the machine-readable basis that is stored in the key and rendered in review.

    No value (`None`) is an explained absence: the field stays empty and the basis says why (a payee or
    a category; the type and a counter-account always have a value). It is a proposal like any other:
    the first one for a field ends the search, a human never accepts it, and it stands exactly as long as
    its classifier proposes it."""

    field: Field
    value: int | str | None
    basis: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Vote:
    """One confirmed past entry as history evidence (spec §5.9, classifiers/history.md).

    Each entry is one vote (a split's entries vote separately). The counter-account facts are
    those of the account the vote's transfer pointed at, filled only for a paired transfer.
    """

    entry_id: int
    account_id: int
    booked_on: date
    type: Literal["flow", "transfer"]
    payee_id: int | None = None
    category_id: int | None = None
    counter_account_id: int | None = None
    counter_account_currency: str | None = None
    counter_account_closed_on: date | None = None
    counterparty_ref: str | None = None
    counterparty_name: str | None = None
    purpose: str | None = None
    booking_text: str | None = None
    mandate_ref: str | None = None


class HistorySource(Protocol):
    """Read-only candidates for one history key (architecture §5.4).

    Returns the votes within the lookback (365 days either side of `entry.booked_on`), left out:
    `exclude_entry_ids` (the entry's own unit). For an equality key the candidates equal the entry
    on that key's canonical value; for
    `tokens`, they share at least one token. Scoring and
    counting are the classifier's. `payee_id` is the payee resolved so far (key `payee`).
    """

    def candidates(
        self,
        key: HistoryKey,
        entry: EntryInput,
        *,
        payee_id: int | None = None,
        exclude_entry_ids: frozenset[int] = frozenset(),
    ) -> Sequence[Vote]: ...


@dataclass(frozen=True, slots=True)
class ClassifierContext:
    """The evidence core hands a classifier for one entry.

    `resolved` holds what is decided so far, earlier fields first, fixed values included.
    `account_ok(account_id)` is core's currency rule (I11) and open-on-booking-date test for a
    counter-account candidate of this entry. `history` is None for classifiers that do not use it.
    """

    resolved: Mapping[Field, Proposal] = field(default_factory=dict)
    account_ok: Callable[[int], bool] = lambda _account_id: True
    history: HistorySource | None = None
    exclude_entry_ids: frozenset[int] = frozenset()
    # what is stored on the entry now (value and key per field, an explained absence included): how the
    # model's answer, its `llm` key, is read as an input (architecture §5.4)
    stored: Mapping[Field, Any] = field(default_factory=dict)


class Classifier(Protocol):
    """One pass (rules, history, later the model). Pure: writes nothing, queries nothing."""

    # the `derivation` pass name its proposals are stored under: "rule" | "history" | "llm"
    pass_name: str

    def propose(self, field: Field, entry: EntryInput, ctx: ClassifierContext) -> Proposal | None:
        """The proposal for `field`, or None when this pass has none (no evidence, no majority)."""
        ...
