"""What the model is given of an entry, and the fingerprint of it (spec §5.9 pass 3, "Limited payload").

The payload of an entry without a line is the counterparty name, booking text and purpose, and for an entry
with a linked or picked document the document's merchant name. For an entry WITH a line, and for a document
line itself, it is the document's merchant name and the line's description only (spec §5.9 pass 3): the
entry takes the line's answer, so the two have the same payload and fingerprint. NEVER the counterparty
IBAN, BIC, end-to-end id, mandate or other references, amounts, dates, accounts or balances: this module is
the one place that reads an entry for the model, and `tests/plugins/classifiers/test_llm_payload.py` pins it.

The client sends the payload and fingerprints it for the worker's list; the classifier compares the
fingerprint with the one stored on the model's answer, so an answer stands only for the payload it was given.
Core knows none of this. Pure functions.

Limited is not anonymous: counterparty names and purpose lines include private persons' names and other
personal details, so a hosted endpoint receives third-party personal data. An on-premise model is the
expected configuration.
"""

from __future__ import annotations

import hashlib
import json

from app.core.plugins.classifier import EntryInput
from app.core.plugins.model import LineInput

# the payload's parts of an entry without a line, in the order the model reads them:
# (label shown to the model, entry attribute)
_ENTRY_PARTS: tuple[tuple[str, str], ...] = (
    ("counterparty", "counterparty_name"),
    ("booking text", "booking_text"),
    ("purpose", "purpose"),
    ("document merchant", "document_merchant"),
)
# a line's: the document's merchant and the line's description
_LINE_PARTS: tuple[tuple[str, str], ...] = (
    ("document merchant", "document_merchant"),
    ("document line", "description"),
)


def payload_of(subject: EntryInput | LineInput) -> dict[str, str] | None:
    """The permitted text of an entry or a document line, by label; None where it would be empty (the pass
    does not run). An entry with a line has its line's payload."""
    source: object
    if isinstance(subject, LineInput):
        parts, source = _LINE_PARTS, subject
    elif subject.document_line is not None:
        parts, source = _LINE_PARTS, LineInput(0, subject.document_merchant, subject.document_line)
    else:
        parts, source = _ENTRY_PARTS, subject
    out: dict[str, str] = {}
    for label, attr in parts:
        value = getattr(source, attr)
        if isinstance(value, str) and (text := " ".join(value.split())):
            out[label] = text
    return out or None


def fingerprint_of(payload: dict[str, str]) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def payload_fingerprint(subject: EntryInput | LineInput) -> str | None:
    """The fingerprint of the payload of an entry or a line, None when the payload is empty."""
    payload = payload_of(subject)
    return fingerprint_of(payload) if payload is not None else None


def user_message(payload: dict[str, str]) -> str:
    return "\n".join(f"{label}: {text}" for label, text in payload.items())
