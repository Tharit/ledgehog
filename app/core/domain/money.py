"""Money: a signed integer in the minor units of a currency (architecture §5.6).

No floats, ever. The minor-unit exponent comes from the `currency` table; this
module imports nothing, so callers pass the exponent to `parse` and `format`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

_CURRENCY = re.compile(r"^[A-Z]{3}$")
_NUMBER = re.compile(r"^[+-]?\d+(\.\d+)?$")


class CurrencyMismatch(ValueError):
    """Arithmetic or comparison across currencies."""


@dataclass(frozen=True, slots=True)
class Money:
    minor: int
    currency: str

    def __post_init__(self) -> None:
        if type(self.minor) is not int:
            raise TypeError(f"Money.minor must be an int, got {type(self.minor).__name__}")
        if not isinstance(self.currency, str) or not _CURRENCY.match(self.currency):
            raise ValueError(f"invalid currency code: {self.currency!r}")

    # -- constructors ----------------------------------------------------
    @classmethod
    def parse(cls, text: str, currency: str, *, minor_units: int) -> Money:
        """Parse plain decimal text ('-12.34'). Excess precision is an error, not rounded."""
        if not _NUMBER.match(text):
            raise ValueError(f"not a decimal amount: {text!r}")
        try:
            value = Decimal(text)
        except InvalidOperation as exc:  # pragma: no cover - regex guards this
            raise ValueError(f"not a decimal amount: {text!r}") from exc
        scaled = value.scaleb(minor_units)
        if scaled != scaled.to_integral_value():
            raise ValueError(f"{text!r} has more than {minor_units} decimal places")
        return cls(int(scaled), currency)

    def format(self, *, minor_units: int) -> str:
        sign = "-" if self.minor < 0 else ""
        digits = str(abs(self.minor))
        if minor_units == 0:
            return f"{sign}{digits}"
        digits = digits.rjust(minor_units + 1, "0")
        return f"{sign}{digits[:-minor_units]}.{digits[-minor_units:]}"

    # -- arithmetic ------------------------------------------------------
    def _same(self, other: Money) -> None:
        if not isinstance(other, Money):
            raise TypeError(f"expected Money, got {type(other).__name__}")
        if other.currency != self.currency:
            raise CurrencyMismatch(f"{self.currency} vs {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._same(other)
        return Money(self.minor + other.minor, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._same(other)
        return Money(self.minor - other.minor, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.minor, self.currency)

    def __mul__(self, factor: int) -> Money:
        if type(factor) is not int:
            raise TypeError("Money can only be multiplied by an int")
        return Money(self.minor * factor, self.currency)

    def __lt__(self, other: Money) -> bool:
        self._same(other)
        return self.minor < other.minor

    def __le__(self, other: Money) -> bool:
        self._same(other)
        return self.minor <= other.minor

    def __gt__(self, other: Money) -> bool:
        self._same(other)
        return self.minor > other.minor

    def __ge__(self, other: Money) -> bool:
        self._same(other)
        return self.minor >= other.minor
