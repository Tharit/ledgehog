"""What the model is given of an entry, and the fingerprint of it (spec §5.9 pass 3, "Limited payload").

The payload of an entry is the counterparty name, booking text and purpose, and for an entry with a source
text, its source text and the name of its account. NEVER the counterparty IBAN, BIC, end-to-end id, mandate
or other references, amounts, dates or balances, nor an account but the one such an entry is on: this
module is the one place that reads an entry for the model, and `tests/plugins/classifiers/test_llm_payload.py`
pins it.

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

from app.core.plugins.classifier import EntryInput, has_source_text

# the payload's parts of an entry, in the order the model reads them:
# (label shown to the model, entry attribute)
_ENTRY_PARTS: tuple[tuple[str, str], ...] = (
    ("counterparty", "counterparty_name"),
    ("booking text", "booking_text"),
    ("purpose", "purpose"),
)
# the parts of an entry with a source text, after the above: what its source gives it, and where it is booked
_SOURCE_TEXT_PARTS: tuple[tuple[str, str], ...] = (
    ("source text", "source_text"),
    ("account", "account_name"),
)


def payload_of(subject: EntryInput) -> dict[str, str] | None:
    """The permitted text of an entry, by label; None where it would be empty (the pass does not run)."""
    out: dict[str, str] = {}
    parts = _ENTRY_PARTS + _SOURCE_TEXT_PARTS if has_source_text(subject.source_text) else _ENTRY_PARTS
    for label, attr in parts:
        value = getattr(subject, attr)
        if isinstance(value, str) and (text := " ".join(value.split())):
            out[label] = text
    return out or None


def fingerprint_of(payload: dict[str, str]) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def payload_fingerprint(subject: EntryInput) -> str | None:
    """The fingerprint of the payload of an entry, None when the payload is empty."""
    payload = payload_of(subject)
    return fingerprint_of(payload) if payload is not None else None


def user_message(payload: dict[str, str]) -> str:
    return "\n".join(f"{label}: {text}" for label, text in payload.items())
