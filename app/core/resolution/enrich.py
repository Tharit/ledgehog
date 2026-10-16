"""A linked document enriches an entry's resolution input (spec §5.8, §5.9; documents.md §5): pure.

The document's merchant name stands in for the counterparty name and its line descriptions are read with
the purpose. The input is built when resolving and never stored: the source row is not changed.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.core.plugins.classifier import EntryInput
from app.core.resolution.allocation import DocLine, lines_for_entry


@dataclass(frozen=True, slots=True)
class LinkedDocument:
    """What resolution reads of a document: its merchant name and its lines, in line order.

    `lines` are `(line_no, amount, description)`; the amounts only let `lines_for_entry` (the allocation's
    choice of lines for an entry) be reused as it is.
    """

    merchant_name: str | None
    lines: tuple[tuple[int, int, str], ...] = ()


def enriched_input(
    entry: EntryInput, document: LinkedDocument | None, *, line_no: int | None = None
) -> EntryInput:
    """`entry` as resolution reads it with `document` linked (documents.md §5).

    `line_no` names the line an entry of a draft split was made from (the original entry: the first line it
    carries); every other entry, an unsplit one included, and every stored entry (no line is stored with an
    entry) is read with all lines. The merchant name replaces the counterparty name where the document has
    one; the descriptions are appended to the purpose, one space apart.
    """
    if document is None:
        return entry
    by_no = {no: description for no, _amount, description in document.lines}
    chosen = lines_for_entry([DocLine(no, amount) for no, amount, _d in document.lines], line_no)
    parts = [entry.purpose, *(by_no[line.line_no] for line in chosen)]
    purpose = " ".join(p for p in parts if p) or None
    name = document.merchant_name if document.merchant_name else entry.counterparty_name
    return replace(entry, counterparty_name=name, purpose=purpose)
