"""The document list filter (architecture §4.1, ux/views/documents.md): one value object, validated on
construction, with the conventions of `LedgerFilter` (an amount bound is a magnitude in minor units of a
currency; a multi-select is OR; dimensions are AND-ed)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from app.core.ledger.filters import MAX_TEXT, InvalidFilter

_CURRENCY = re.compile(r"[A-Z]{3}")


@dataclass(frozen=True)
class DocumentFilter:
    providers: tuple[str, ...] = ()
    date_from: date | None = None  # on occurred_on, inclusive
    date_to: date | None = None  # inclusive
    amount_min: int | None = None  # magnitude, minor units of `currency`
    amount_max: int | None = None
    currency: str | None = None
    text: str | None = None  # merchant name, title or a line's description
    linked: bool | None = None  # True: carried by a transaction; False: carried by none; None: either
    fully_charged: bool | None = None  # its carriers' amounts reach its total (by magnitude); None: either

    def __post_init__(self) -> None:
        if any(not 1 <= len(p) <= MAX_TEXT for p in self.providers):
            raise InvalidFilter("provider", f"provider must be 1 to {MAX_TEXT} characters")
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
        if self.text is not None and not 1 <= len(self.text.strip()) <= MAX_TEXT:
            raise InvalidFilter("q", f"q must be 1 to {MAX_TEXT} characters")
