"""Classifier pass 2: history (spec §5.9, classifiers/history.md).

Pure: the evidence comes from `ctx.history`, a read-only source provided by core, which also
owns the lookback. Here only matching refinements, counting and the strict majority.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from app.core.ingest.identity import canonical_text
from app.core.plugins.classifier import (
    EMPTY,
    HISTORY_KEYS,
    ClassifierContext,
    EntryInput,
    Field,
    HistoryKey,
    Proposal,
    Vote,
)
from app.core.plugins.text import purpose_tokens

JACCARD_MIN = 0.5

_MATCHED_ON: dict[HistoryKey, str] = {
    "counterparty_ref": "counterparty_ref",
    "counterparty_name": "counterparty_name+booking_text",
    "payee": "payee",
}

MODEL_CATEGORIES = 3  # the categories the model is told (spec §5.9, pass 3)


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
        resolved_payee = self._resolved_payee(ctx)
        if entry.booking is not None:
            return None  # a booking's entries take no part in history (history.md §1)
        mine = purpose_tokens(entry.purpose)
        for key in HISTORY_KEYS:
            matches = self._matches(key, field, entry, ctx, resolved_payee)
            if matches is None:
                continue
            for similar, votes in self._tiers(mine, matches):
                counted = self._counted(field, votes, ctx)
                if not counted:
                    continue
                winner = self._majority([v for v, _ in counted])
                if winner is None:
                    continue
                value, agree = winner
                basis: dict[str, object] = {
                    "matched_on": _MATCHED_ON[key] + ("+purpose" if similar else ""),
                    "agree": agree,
                    "of": len(counted),
                    "since": min(vote.booked_on for _, vote in counted).isoformat(),
                }
                if field == "counter_account":
                    basis["account_id"] = value
                # on the category the proposal stands only where the votes are unanimous (spec §5.9)
                return Proposal(field, value, basis, gives_way=field == "category" and agree != len(counted))
        return None

    def categories_seen(self, entry: EntryInput, ctx: ClassifierContext) -> tuple[int, ...]:
        """The (at most three) most frequent categories among all the matches of the first key that has any
        counted category vote, ties by path, in path order: what the model is told (history.md §3)."""
        if ctx.history is None or entry.booking is not None:
            return ()
        paths = ctx.history.category_paths
        resolved_payee = self._resolved_payee(ctx)
        for key in HISTORY_KEYS:
            matches = self._matches(key, "category", entry, ctx, resolved_payee)
            if matches is None:
                continue
            counts = Counter(int(v) for v, _ in self._counted("category", matches, ctx))
            if not counts:
                continue

            def by_path(category_id: int) -> tuple[str, int]:
                return (paths.get(category_id, ""), category_id)

            top = sorted(counts, key=lambda c: (-counts[c], *by_path(c)))[:MODEL_CATEGORIES]
            return tuple(sorted(top, key=by_path))
        return ()

    @staticmethod
    def _resolved_payee(ctx: ClassifierContext) -> int | None:
        payee = ctx.resolved.get("payee")
        return payee.value if payee is not None and isinstance(payee.value, int) else None

    @staticmethod
    def _tiers(mine: frozenset[str], matches: list[Vote]) -> list[tuple[bool, list[Vote]]]:
        """The sets of a key's matches to count, in order: the similar-purpose ones, then all. An entry
        whose purpose has no tokens skips the narrowing; a vote whose purpose has none is not similar."""
        if not mine:
            return [(False, matches)]
        size = len(mine)
        similar = []
        for v in matches:
            theirs = purpose_tokens(v.purpose)
            shared = len(mine & theirs)
            # Jaccard on the purposes alone, without building sets (the hot loop of settling)
            if shared and shared / (size + len(theirs) - shared) >= JACCARD_MIN:
                similar.append(v)
        return [(True, similar)] + ([(False, matches)] if len(similar) < len(matches) else [])

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
        if key == "counterparty_ref":
            if not canonical_text(entry.counterparty_ref):
                return None
        elif key == "counterparty_name":
            if not canonical_text(entry.counterparty_name):
                return None
        elif key == "payee":
            if field != "category" or resolved_payee is None:
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
        return list(candidates)  # payee: equal on the key's own value

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
                    out.append((v.payee_id if v.payee_id is not None else EMPTY, v))
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
