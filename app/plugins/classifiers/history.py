"""Classifier pass 2: history (spec §5.9, classifiers/history.md).

Pure: the evidence comes from `ctx.history`, a read-only source provided by core, which also
owns the lookback. Here only matching refinements, counting and the strict majority.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from app.core.ingest.identity import canonical_text
from app.core.plugins.classifier import (
    HISTORY_KEYS,
    NO_PAYEE,
    ClassifierContext,
    EntryInput,
    Field,
    HistoryKey,
    Proposal,
    Vote,
)
from app.core.plugins.text import jaccard, tokens

JACCARD_MIN = 0.5

_MATCHED_ON: dict[HistoryKey, str] = {
    "counterparty_ref": "counterparty_ref",
    "counterparty_name": "counterparty_name+booking_text",
    "payee": "payee",
    "booking_text": "booking_text",
    "tokens": "tokens",
}


def _other_code(entry_value: str | None, vote_value: str | None) -> bool:
    """True when both carry a value and they differ (canonically)."""
    a, b = canonical_text(entry_value), canonical_text(vote_value)
    return bool(a) and bool(b) and a != b


class HistoryClassifier:
    """Pass 2. Proposes what a strict majority of the matches of the first decisive key share."""

    pass_name = "history"

    def propose(self, field: Field, entry: EntryInput, ctx: ClassifierContext) -> Proposal | None:
        if ctx.history is None:
            return None
        payee = ctx.resolved.get("payee")
        resolved_payee = payee.value if payee is not None and isinstance(payee.value, int) else None
        for key in HISTORY_KEYS:
            votes = self._matches(key, field, entry, ctx, resolved_payee)
            if votes is None:
                continue
            counted = self._counted(field, votes, ctx)
            if not counted:
                continue
            winner = self._majority([v for v, _ in counted])
            if winner is None:
                continue
            value, agree = winner
            basis: dict[str, object] = {
                "matched_on": _MATCHED_ON[key],
                "agree": agree,
                "of": len(counted),
                "since": min(vote.booked_on for _, vote in counted).isoformat(),
            }
            if field == "counter_account":
                basis["account_id"] = value
            return Proposal(field, value, basis)
        return None

    @staticmethod
    def _matches(
        key: HistoryKey,
        field: Field,
        entry: EntryInput,
        ctx: ClassifierContext,
        resolved_payee: int | None,
    ) -> list[Vote] | None:
        """The votes matching `key`, refined; None when the key does not apply."""
        assert ctx.history is not None
        entry_tokens: frozenset[str] = frozenset()
        if key == "counterparty_ref":
            if not canonical_text(entry.counterparty_ref):
                return None
        elif key == "counterparty_name":
            if not canonical_text(entry.counterparty_name):
                return None
        elif key == "payee":
            if field != "category" or resolved_payee is None:
                return None
        elif key == "booking_text":
            if not canonical_text(entry.booking_text):
                return None
        else:
            entry_tokens = tokens(entry.counterparty_name, entry.purpose)
            if not entry_tokens:
                return None
        candidates: Sequence[Vote] = ctx.history.candidates(
            key,
            entry,
            payee_id=resolved_payee if key == "payee" else None,
            exclude_entry_ids=ctx.exclude_entry_ids,
        )
        # an entry without the refining code keeps every candidate: the entry side is read once
        if key == "counterparty_ref":
            mandate = canonical_text(entry.mandate_ref)
            if not mandate:
                return list(candidates)
            return [v for v in candidates if not _other_code(mandate, v.mandate_ref)]
        if key == "counterparty_name":
            booking = canonical_text(entry.booking_text)
            if not booking:
                return list(candidates)
            return [v for v in candidates if not _other_code(booking, v.booking_text)]
        if key == "booking_text":
            return [v for v in candidates if v.account_id == entry.account_id]
        if key == "tokens":
            return [
                v
                for v in candidates
                if jaccard(entry_tokens, tokens(v.counterparty_name, v.purpose)) >= JACCARD_MIN
            ]
        return list(candidates)

    @staticmethod
    def _counted(field: Field, votes: Sequence[Vote], ctx: ClassifierContext) -> list[tuple[int | str, Vote]]:
        """(value voted, vote) for the votes that count for `field`."""
        out: list[tuple[int | str, Vote]] = []
        for v in votes:
            if field == "type":
                out.append((v.type, v))
            elif field == "counter_account":
                if (
                    v.type == "transfer"
                    and v.counter_account_id is not None
                    and ctx.account_ok(v.counter_account_id)
                ):
                    out.append((v.counter_account_id, v))
            elif v.type == "flow":
                if field == "payee":
                    out.append((v.payee_id if v.payee_id is not None else NO_PAYEE, v))
                elif v.category_id is not None:
                    out.append((v.category_id, v))
        return out

    @staticmethod
    def _majority(values: Sequence[int | str]) -> tuple[int | str, int] | None:
        """The value held by a strict majority (`agree * 2 > of`), with its count."""
        top = Counter(values).most_common(1)
        if not top:
            return None
        value, agree = top[0]
        return (value, agree) if agree * 2 > len(values) else None
