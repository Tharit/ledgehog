"""Test oracles for the classifier plugins: an in-memory history source and builders."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from app.core.ingest.identity import canonical_text
from app.core.plugins.classifier import EntryInput, HistoryKey, Vote


class ListHistory:
    """HistorySource over a list of votes, scanning with canonical equality. No lookback."""

    def __init__(self, votes: Sequence[Vote], category_paths: Mapping[int, str] | None = None) -> None:
        self.votes = list(votes)
        self.category_paths: Mapping[int, str] = category_paths or {}
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
            if v.entry_id in exclude_entry_ids:
                continue
            if key == "counterparty_ref":
                ok = canonical_text(v.counterparty_ref) == canonical_text(entry.counterparty_ref)
            elif key == "counterparty_name":
                ok = canonical_text(v.counterparty_name) == canonical_text(entry.counterparty_name)
            else:
                ok = payee_id is not None and v.payee_id == payee_id
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
