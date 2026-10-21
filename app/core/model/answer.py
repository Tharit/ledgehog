"""The model's "none" answer as it stands on an entry (spec §5.9 pass 3): the category left empty, its
`llm` key `{"pass": "llm", "basis": {"model", "rationale", "fingerprint", "none": true}}` the only trace.

It is the one key that explains an absence, so settling must not strip it as the key of an empty field,
and it is kept only while the payload the model was given is the entry's payload now: a changed payload
asks anew (the key goes), and so does a category some other pass or a user decides (the key is replaced).
Pure reads; the fingerprint is the queue's, so core never learns what the payload is made of.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core.model.queue import current_model_queue
from app.core.plugins.classifier import EntryInput


def none_key_of(derivation: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The `category` key when it is the model's "none" answer, else None."""
    key = derivation.get("category")
    if not isinstance(key, Mapping) or key.get("pass") != "llm":
        return None
    basis = key.get("basis")
    return key if isinstance(basis, Mapping) and basis.get("none") is True else None


def holds_none_answer(derivation: Mapping[str, Any], entry: EntryInput) -> bool:
    """The entry carries the model's "none" answer for the payload it has now: answered, not asked again."""
    key = none_key_of(derivation)
    queue = current_model_queue()
    if key is None or queue is None:
        return False
    fingerprint = queue.fingerprint(entry)
    basis = key["basis"]
    return fingerprint is not None and basis.get("fingerprint") == fingerprint
