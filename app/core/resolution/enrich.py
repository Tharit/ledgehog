"""A linked document as an input to resolution (spec §5.8, §5.9; documents.md §5): pure.

The source row is read as stored: the document never rewrites `counterparty_name`, `purpose` or any other
source field. It adds three entry-level facts the entry's input carries: `documented` (a document is linked or
picked), `document_merchant` (its merchant name) and `document_line` (the description of the entry's OWN
line of it, or None). Rules read the two fields (`plugins/classifiers/rules.py`), history asks the merchant
(`plugins/classifiers/history.py`). The input is built when resolving and never stored.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.core.plugins.classifier import EntryInput


@dataclass(frozen=True, slots=True)
class LinkedDocument:
    """What resolution reads of a document: its merchant name and its lines, in line order.

    `lines` are `(line_no, amount, description)`; the amounts are for the allocation of a split
    (`core/resolution/allocation.py`), resolution itself reads the description of one entry's line only.
    """

    merchant_name: str | None
    lines: tuple[tuple[int, int, str], ...] = ()

    def description_of(self, line_no: int | None) -> str | None:
        """The description of line `line_no`, None for no line or a number the document does not have."""
        if line_no is None:
            return None
        return next((d for no, _amount, d in self.lines if no == line_no), None)


def with_document(
    entry: EntryInput, document: LinkedDocument | None, *, line_no: int | None = None
) -> EntryInput:
    """`entry` as resolution reads it with `document` linked: the source fields as they are, plus the
    document's merchant name and the description of the entry's own line `line_no` (None: no line)."""
    if document is None:
        return entry
    merchant = document.merchant_name if document.merchant_name and document.merchant_name.strip() else None
    return replace(
        entry,
        documented=True,
        document_merchant=merchant,
        document_line=document.description_of(line_no),
    )
