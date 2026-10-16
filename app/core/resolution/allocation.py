"""Allocating a document's lines to a split (spec/features/documents.md §6): pure, exact integers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True, slots=True)
class DocLine:
    """One line of a document, in the document's currency, signed like its total."""

    line_no: int
    amount: int


def split_along_lines(
    entry_amount: int,
    entry_currency: str,
    instructed_amount: int | None,
    instructed_currency: str | None,
    lines: Sequence[DocLine],
    document_total: int,
    document_currency: str,
) -> list[tuple[int, int]] | None:
    """The proposed split as [(line_no, amount)] in line order, summing exactly to `entry_amount`.

    The original entry takes the first line plus the remainder (shipping, discounts, rounding); each
    other line becomes an entry. A document in the instructed currency converts its other lines
    proportionally (`line * entry_amount / document_total`), rounded half-even. None where there is
    no split: fewer than two lines, a total that does not match the entry exactly (spec §3), or an
    original share that is zero or has not the entry's sign.
    """
    if len(lines) < 2:
        return None
    if document_currency == entry_currency and document_total == entry_amount:
        scale: Fraction | None = None
    elif (
        instructed_currency is not None
        and instructed_amount is not None
        and document_currency == instructed_currency
        and document_total == instructed_amount
        and document_total != 0
    ):
        scale = Fraction(entry_amount, document_total)
    else:
        return None
    ordered = sorted(lines, key=lambda line: line.line_no)
    rest = [
        (line.line_no, line.amount if scale is None else round(line.amount * scale)) for line in ordered[1:]
    ]
    original = entry_amount - sum(amount for _, amount in rest)
    if original == 0 or (original > 0) != (entry_amount > 0):
        return None
    return [(ordered[0].line_no, original), *rest]


def lines_for_entry(lines: Sequence[DocLine], line_no: int | None) -> list[DocLine]:
    """The lines an entry of the draft is resolved with (§5): the one it was made from, or, for any
    other entry (an unsplit one included), all of them."""
    if line_no is None:
        return list(lines)
    return [line for line in lines if line.line_no == line_no]
