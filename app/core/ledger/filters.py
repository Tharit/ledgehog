"""The ledger filter (spec §8): one value object, validated on construction.

The list, and later the tag-apply operation, take the same `LedgerFilter`. Within one dimension a
multi-select is OR; across dimensions the dimensions are AND-ed. Composing it into SQL is
`app.core.ledger.compose`; this module is pure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

# schema.sql: ledger_entry.type and ck_review_flags_known
ENTRY_TYPES = ("flow", "transfer", "opening", "valuation", "reconciliation")
REVIEW_FLAGS = ("unconfirmed", "unclassified", "document_suggested", "waiting", "unmatched_transfer")
DIRECTIONS = ("in", "out")

MAX_ID = 2**53  # as app.api.ids: JSON-safe and inside bigint
MAX_TEXT = 200
_CURRENCY = re.compile(r"[A-Z]{3}")


class InvalidFilter(ValueError):
    """The filter contradicts itself or holds an invalid value; nothing was queried.

    `parameter` names the query parameter at fault. The message states the rule and never quotes
    the value (a text search is user input).
    """

    def __init__(self, parameter: str, message: str) -> None:
        super().__init__(message)
        self.parameter = parameter


@dataclass(frozen=True)
class LedgerFilter:
    date_from: date | None = None  # inclusive
    date_to: date | None = None  # inclusive
    account_ids: tuple[int, ...] = ()
    category_ids: tuple[int, ...] = ()
    category_descendants: bool = True  # a parent includes its descendants
    uncategorised: bool = False  # flows with no category; OR-ed with category_ids
    payee_ids: tuple[int, ...] = ()
    tag_ids: tuple[int, ...] = ()  # any of them
    amount_min: int | None = None  # magnitude, minor units of `currency`
    amount_max: int | None = None
    currency: str | None = None
    direction: str | None = None  # "in" (amount > 0) | "out" (amount < 0)
    text: str | None = None
    types: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()  # a review token; any of them

    def __post_init__(self) -> None:
        for name, param, ids in (
            ("account_ids", "account_id", self.account_ids),
            ("category_ids", "category_id", self.category_ids),
            ("payee_ids", "payee_id", self.payee_ids),
            ("tag_ids", "tag_id", self.tag_ids),
        ):
            if any(not 0 < i <= MAX_ID for i in ids):
                raise InvalidFilter(param, f"{param} must be a positive id")
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise InvalidFilter("to", "to must not be before from")
        for param, bound in (("amount_min", self.amount_min), ("amount_max", self.amount_max)):
            if bound is not None and not 0 <= bound <= 2**63 - 1:
                raise InvalidFilter(param, f"{param} must be a non-negative amount in minor units")
        if self.amount_min is not None and self.amount_max is not None and self.amount_min > self.amount_max:
            raise InvalidFilter("amount_min", "amount_min must not exceed amount_max")
        if self.currency is not None and not _CURRENCY.fullmatch(self.currency):
            raise InvalidFilter("currency", "currency must be three capital letters")
        if (self.amount_min is not None or self.amount_max is not None) and self.currency is None:
            raise InvalidFilter("currency", "currency is required with an amount bound")
        if self.direction is not None and self.direction not in DIRECTIONS:
            raise InvalidFilter("direction", "direction must be 'in' or 'out'")
        if self.text is not None and not 1 <= len(self.text.strip()) <= MAX_TEXT:
            raise InvalidFilter("q", f"q must be 1 to {MAX_TEXT} characters")
        if any(t not in ENTRY_TYPES for t in self.types):
            raise InvalidFilter("type", "type is not a known entry type")
        if any(f not in REVIEW_FLAGS for f in self.flags):
            raise InvalidFilter("flag", "flag is not a known review flag")

    @property
    def is_empty(self) -> bool:
        """True when no dimension restricts anything (`category_descendants` alone restricts nothing)."""
        return self == LedgerFilter(category_descendants=self.category_descendants)
