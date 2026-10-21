"""Pass 3 as a classifier (spec §5.9): pure, it only reads the stored answer.

The model is never asked here: settling must not wait for it. The worker (`core/model`) asks in the
background and stores the answer as the category's `llm` key with the payload's fingerprint; this pass
proposes that answer again while the entry's payload still has the fingerprint, and nothing otherwise
(a changed payload, a stale answer: the worker asks anew). Category only, never a payee.
"""

from __future__ import annotations

from typing import Any

from app.core.plugins.classifier import ClassifierContext, EntryInput, Field, Proposal
from app.plugins.classifiers.llm.payload import fingerprint_of, payload_of


class LlmClassifier:
    pass_name = "llm"

    def propose(self, field: Field, entry: EntryInput, ctx: ClassifierContext) -> Proposal | None:
        if field != "category":
            return None
        stored: Any = ctx.stored.get("category")
        if stored is None or stored.pass_name != self.pass_name or not isinstance(stored.value, int):
            return None
        payload = payload_of(entry)
        if payload is None or stored.basis.get("fingerprint") != fingerprint_of(payload):
            return None
        return Proposal("category", stored.value, dict(stored.basis))
