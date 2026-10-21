"""What the model is given of an entry, and the fingerprint of it (spec §5.9 pass 3, "Limited payload").

The payload is the counterparty name, booking text and purpose, and for an entry with a linked or picked
document the document's merchant name and the entry's own line. NEVER the counterparty IBAN, BIC,
end-to-end id, mandate or other references, amounts, dates, accounts or balances: this module is the one
place that reads an entry for the model, and `tests/plugins/classifiers/test_llm_payload.py` pins it.

Limited is not anonymous: counterparty names and purpose lines include private persons' names and other
personal details, so a hosted endpoint receives third-party personal data. An on-premise model is the
expected configuration.
"""

from __future__ import annotations

import hashlib
import json

from app.core.plugins.classifier import EntryInput

# the payload's parts, in the order the model reads them: (label shown to the model, entry attribute)
_PARTS: tuple[tuple[str, str], ...] = (
    ("counterparty", "counterparty_name"),
    ("booking text", "booking_text"),
    ("purpose", "purpose"),
    ("document merchant", "document_merchant"),
    ("document line", "document_line"),
)


def payload_of(entry: EntryInput) -> dict[str, str] | None:
    """The permitted text of `entry`, by label; None where it would be empty (the pass does not run)."""
    out: dict[str, str] = {}
    for label, attr in _PARTS:
        value = getattr(entry, attr)
        if isinstance(value, str) and (text := " ".join(value.split())):
            out[label] = text
    return out or None


def fingerprint_of(payload: dict[str, str]) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def user_message(payload: dict[str, str]) -> str:
    return "\n".join(f"{label}: {text}" for label, text in payload.items())
