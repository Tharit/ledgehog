"""The history snapshot (architecture §5.4, spec §5.9, classifiers/history.md §1).

One query per settle loads every voter - a confirmed entry with a source transaction - into Python
indexes; `candidates()` then answers each key by dictionary lookup, inside the lookback, so resolving
thousands of entries issues no query. Between rounds `add()` takes the entries a round confirmed, with no
reload.

Each entry is one vote. Only a paired transfer carries a counter-account (and that account's
currency and closing date); a pair counts however it was made (a commit, or settling's step 4 once its
unit is confirmed), and an unpaired transfer is never confirmed, so never a voter.
Candidates come back ordered by (`booked_on`, entry id), so a proposal never depends on load order.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, cast

from sqlalchemy import Connection, Row, TextClause, text

from app.core.ingest.identity import canonical_text
from app.core.plugins.classifier import EntryInput, HistoryKey, Vote
from app.core.resolution.confirmed import units_binds, units_sql
from app.core.resolution.load import load_category_paths

LOOKBACK_DAYS = 365

_SortKey = tuple[int, int]  # (booked_on ordinal, entry id)


@dataclass(frozen=True, slots=True)
class Grown:
    """What a batch of new votes added: the (key, value) buckets."""

    buckets: frozenset[tuple[str, str | int]] = frozenset()


class _Bucket:
    """Votes sorted by (booked_on, entry id), so a lookback window is one bisect."""

    __slots__ = ("keys", "votes")

    def __init__(self) -> None:
        self.keys: list[_SortKey] = []
        self.votes: list[Vote] = []

    def add(self, key: _SortKey, vote: Vote) -> None:
        i = bisect_left(self.keys, key)
        self.keys.insert(i, key)
        self.votes.insert(i, vote)

    def window(self, lo: _SortKey, hi: _SortKey) -> list[Vote]:
        return self.votes[bisect_left(self.keys, lo) : bisect_right(self.keys, hi)]


def _sort_key(v: Vote) -> _SortKey:
    return (v.booked_on.toordinal(), v.entry_id)


class HistorySnapshot:
    """A `HistorySource` over the confirmed entries loaded once; see the module docstring."""

    def __init__(self, votes: Iterable[Vote] = (), category_paths: Mapping[int, str] | None = None) -> None:
        # the category tree as paths, loaded with the votes: the classifier orders by it (`HistorySource`)
        self.category_paths: Mapping[int, str] = category_paths if category_paths is not None else {}
        self._by: dict[str, dict[str | int, _Bucket]] = {
            "counterparty_ref": defaultdict(_Bucket),
            "counterparty_name": defaultdict(_Bucket),
            "payee": defaultdict(_Bucket),
        }
        self._ids: set[int] = set()
        self.add(votes)

    def __len__(self) -> int:
        return len(self._ids)

    def add(self, votes: Iterable[Vote]) -> Grown:
        """Take more votes (entries confirmed since); one already held is ignored.

        Returns the (key, value) buckets that grew: an entry whose own values hit none of them
        cannot have a different proposal because of these votes (see `touches`).
        """
        grown: set[tuple[str, str | int]] = set()

        def put(key: str, value: str | int, k: _SortKey, v: Vote) -> None:
            self._by[key][value].add(k, v)
            grown.add((key, value))

        for v in votes:
            if v.entry_id in self._ids:
                continue
            self._ids.add(v.entry_id)
            k = _sort_key(v)
            put("counterparty_ref", canonical_text(v.counterparty_ref), k, v)
            put("counterparty_name", canonical_text(v.counterparty_name), k, v)
            if v.payee_id is not None:
                put("payee", v.payee_id, k, v)
        return Grown(frozenset(grown))

    def candidates(
        self,
        key: HistoryKey,
        entry: EntryInput,
        *,
        payee_id: int | None = None,
        exclude_entry_ids: frozenset[int] = frozenset(),
    ) -> Sequence[Vote]:
        day = entry.booked_on.toordinal()
        lo: _SortKey = (day - LOOKBACK_DAYS, -1)
        hi: _SortKey = (day + LOOKBACK_DAYS, 1 << 62)
        buckets = self._by[key]
        if key == "payee":
            value: str | int | None = payee_id
        elif key == "counterparty_ref":
            value = canonical_text(entry.counterparty_ref)
        else:
            value = canonical_text(entry.counterparty_name)
        bucket = buckets.get(value) if value is not None else None
        found = bucket.window(lo, hi) if bucket is not None else []
        if exclude_entry_ids:
            return [v for v in found if v.entry_id not in exclude_entry_ids]
        return found


class LayeredHistory(HistorySnapshot):
    """A snapshot laid over another that it never changes: `add` goes to this layer only.

    The unit preview teaches history the units a plan confirms (settling does the same to its own snapshot);
    a layer makes that a property of one plan, so the base can serve the next plan unchanged.
    """

    def __init__(self, base: HistorySnapshot) -> None:
        super().__init__(category_paths=base.category_paths)
        self._base = base

    def __len__(self) -> int:
        return len(self._base) + super().__len__()

    def add(self, votes: Iterable[Vote]) -> Grown:
        return super().add(v for v in votes if v.entry_id not in self._base._ids)

    def candidates(
        self,
        key: HistoryKey,
        entry: EntryInput,
        *,
        payee_id: int | None = None,
        exclude_entry_ids: frozenset[int] = frozenset(),
    ) -> Sequence[Vote]:
        below = self._base.candidates(key, entry, payee_id=payee_id, exclude_entry_ids=exclude_entry_ids)
        here = super().candidates(key, entry, payee_id=payee_id, exclude_entry_ids=exclude_entry_ids)
        if not here:
            return below
        return sorted([*below, *here], key=_sort_key)


def touches(grown: Grown, entry: EntryInput, payee_id: int | None) -> bool:
    """Whether votes that added `grown` can change the history proposals for `entry`.

    The entry's own values are what the keys look up; `payee_id` is the payee stored on it (key 3
    reads the payee resolved so far, which is stored or changes only through the other keys). The purpose
    only refines the votes a key finds, it never finds any, so the buckets are all that matters.
    """
    b = grown.buckets
    # a key whose value the entry lacks is never asked (history.md §2), so an empty value reaches nothing
    for key, raw in (
        ("counterparty_ref", entry.counterparty_ref),
        ("counterparty_name", entry.counterparty_name),
    ):
        value = canonical_text(raw)
        if value and (key, value) in b:
            return True
    return payee_id is not None and ("payee", payee_id) in b


_VOTES = """
    WITH units AS ({units})
    SELECT e.id AS entry_id, e.account_id, e.booked_on, e.type, e.payee_id, e.category_id,
           CASE WHEN e.counterpart_entry_id IS NOT NULL THEN e.counter_account_id END AS counter_account_id,
           CASE WHEN e.counterpart_entry_id IS NOT NULL THEN ca.currency END AS counter_account_currency,
           CASE WHEN e.counterpart_entry_id IS NOT NULL THEN ca.closed_on END AS counter_account_closed_on,
           s.counterparty_ref, s.counterparty_name, s.purpose, s.booking_text, s.mandate_ref
      FROM units AS u
      JOIN ledger_entry AS e ON e.id = u.id
      JOIN source_transaction AS s ON s.id = e.source_transaction_id
      LEFT JOIN account AS ca ON ca.id = e.counter_account_id
     WHERE u.unit_ok
       {booking}
       {only}
"""


def _votes_sql(*, of_entries: bool) -> TextClause:
    return text(
        _VOTES.format(
            units=units_sql(of_entries=of_entries),
            booking="AND s.origin <> 'booking'",
            only="AND e.id = ANY(:ids)" if of_entries else "",
        )
    )


def _votes(rows: Iterable[Row[Any]]) -> list[Vote]:
    out: list[Vote] = []
    for r in rows:
        m = r._mapping
        out.append(
            Vote(
                entry_id=m["entry_id"],
                account_id=m["account_id"],
                booked_on=cast(date, m["booked_on"]),
                type=cast(Literal["flow", "transfer"], m["type"]),
                payee_id=m["payee_id"],
                category_id=m["category_id"],
                counter_account_id=m["counter_account_id"],
                counter_account_currency=m["counter_account_currency"],
                counter_account_closed_on=m["counter_account_closed_on"],
                counterparty_ref=m["counterparty_ref"],
                counterparty_name=m["counterparty_name"],
                purpose=m["purpose"],
                booking_text=m["booking_text"],
                mandate_ref=m["mandate_ref"],
            )
        )
    return out


def load_votes(conn: Connection) -> list[Vote]:
    """Every voter: the one query of a settle."""
    return _votes(conn.execute(_votes_sql(of_entries=False), units_binds(conn)))


def load_votes_of(conn: Connection, entry_ids: Sequence[int]) -> list[Vote]:
    """The votes among these entries (those that became confirmed in a round)."""
    if not entry_ids:
        return []
    return _votes(conn.execute(_votes_sql(of_entries=True), {**units_binds(conn), "ids": list(entry_ids)}))


def load_snapshot(conn: Connection) -> HistorySnapshot:
    return HistorySnapshot(load_votes(conn), category_paths_of(conn))


def category_paths_of(conn: Connection) -> dict[int, str]:
    """The category tree as {id: path}, for the snapshot."""
    return {c.id: c.path for c in load_category_paths(conn)}
