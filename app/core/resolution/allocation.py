"""A carrier's split along the lines its line allocation gives it (spec/features/documents.md §6): pure, exact
integers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True, slots=True)
class DocLine:
    """One line of a document, in the document's currency, signed like its total."""

    line_no: int
    amount: int


def _sign(n: int) -> int:
    return (n > 0) - (n < 0)


def split_along_lines(
    entry_amount: int,
    entry_currency: str,
    instructed_amount: int | None,
    instructed_currency: str | None,
    lines: Sequence[DocLine],
    party_amount: int,
    document_total: int,
    document_currency: str,
) -> list[tuple[int, int]] | None:
    """The proposed split of one carrier as [(line_no, amount)] in line order, summing exactly to
    `entry_amount`.

    `lines` are the lines the document's line allocation gives the transaction (`matching.lines.allocate`),
    of either sign; `party_amount` is its amount in the document's currency. One entry per line of the
    document's sign (that of `document_total`): the original takes the first and the remainder of the
    transaction (shipping, rounding, and every line of the opposite sign, a coupon or a credit), each other
    line of the sign becomes an entry. A document in the instructed currency converts a line
    proportionally (`line * entry_amount / party_amount`), rounded half-even. A transaction given a single
    line of the sign gets a list of one: the original takes it. None where there is no split: no line of the
    sign, an amount that is not the transaction's in the document's currency, a line that converts to
    nothing, or an original share that is zero or has not the entry's sign.
    """
    if document_currency == entry_currency and party_amount == entry_amount:
        scale: Fraction | None = None
    elif (
        instructed_currency is not None
        and instructed_amount is not None
        and document_currency == instructed_currency
        and party_amount == instructed_amount
        and party_amount != 0
    ):
        scale = Fraction(entry_amount, party_amount)
    else:
        return None
    sign = _sign(document_total) or _sign(entry_amount)
    ordered = [line for line in sorted(lines, key=lambda line: line.line_no) if _sign(line.amount) == sign]
    if not ordered:
        return None
    rest = [
        (line.line_no, line.amount if scale is None else round(line.amount * scale)) for line in ordered[1:]
    ]
    if any(amount == 0 for _, amount in rest):
        return None
    original = entry_amount - sum(amount for _, amount in rest)
    if original == 0 or _sign(original) != _sign(entry_amount):
        return None
    return [(ordered[0].line_no, original), *rest]


def lines_for_entry(lines: Sequence[DocLine], line_no: int | None) -> list[DocLine]:
    """The lines an entry of the draft is resolved with (§5): the one it was made from, or, for any
    other entry (an unsplit one included), all of them."""
    if line_no is None:
        return list(lines)
    return [line for line in lines if line.line_no == line_no]
