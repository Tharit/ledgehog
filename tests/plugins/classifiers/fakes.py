"""Test oracles for the classifier plugins: an in-memory history source and builders."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from app.core.ingest.identity import canonical_text
from app.core.plugins.classifier import EntryInput, HistoryKey, Vote
from app.core.plugins.text import tokens


class ListHistory:
    """HistorySource over a list of votes, scanning with canonical equality. No lookback."""

    def __init__(self, votes: Sequence[Vote]) -> None:
        self.votes = list(votes)
        self.calls: list[HistoryKey] = []

    def candidates(
        self,
        key: HistoryKey,
        entry: EntryInput,
        *,
        payee_id: int | None = None,
        exclude_entry_ids: frozenset[int] = frozenset(),
    ) -> Sequence[Vote]:
        self.calls.append(key)
        out: list[Vote] = []
        for v in self.votes:
            if (
                v.entry_id in exclude_entry_ids or v.has_line
            ):  # as the snapshot: a line's vote counts for no key
                continue
            if key == "document_merchant":
                # as the snapshot: a documented vote counts for this key only, an undocumented one never
                ok = v.documented and canonical_text(v.document_merchant) == canonical_text(
                    entry.document_merchant
                )
            elif v.documented:
                ok = False
            elif key == "counterparty_ref":
                ok = canonical_text(v.counterparty_ref) == canonical_text(entry.counterparty_ref)
            elif key == "counterparty_name":
                ok = canonical_text(v.counterparty_name) == canonical_text(entry.counterparty_name)
            elif key == "payee":
                ok = payee_id is not None and v.payee_id == payee_id
            else:
                ok = bool(
                    tokens(v.counterparty_name, v.purpose) & tokens(entry.counterparty_name, entry.purpose)
                )
            if ok:
                out.append(v)
        return out


def entry(**kw: object) -> EntryInput:
    base: dict[str, object] = {
        "entry_id": 1000,
        "account_id": 1,
        "currency": "EUR",
        "booked_on": date(2026, 6, 1),
        "amount": -1000,
    }
    base.update(kw)
    return EntryInput(**base)  # type: ignore[arg-type]


_n = [0]


def vote(**kw: object) -> Vote:
    _n[0] += 1
    base: dict[str, object] = {
        "entry_id": _n[0],
        "account_id": 1,
        "booked_on": date(2026, 3, 1),
        "type": "flow",
    }
    base.update(kw)
    return Vote(**base)  # type: ignore[arg-type]
