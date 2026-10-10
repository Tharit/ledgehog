"""Decimal text to integer minor units, without floats (csv.md §3)."""

from __future__ import annotations

from app.core.domain.money import Money


def parse_amount(text: str, *, currency: str, minor_units: int, decimal_sep: str, thousands_sep: str) -> int:
    """Parse `1.234,56`-style text. More decimals than `minor_units` is an error; fewer is fine."""
    plain = text.strip()
    if thousands_sep:
        plain = plain.replace(thousands_sep, "")
    if decimal_sep != ".":
        if "." in plain:
            raise ValueError("not a decimal amount")
        plain = plain.replace(decimal_sep, ".")
    return Money.parse(plain, currency, minor_units=minor_units).minor
