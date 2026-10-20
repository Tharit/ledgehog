"""The history snapshot (architecture §5.4, spec §5.9, classifiers/history.md §1).

One query per settle loads every voter - a confirmed entry with a source transaction - into Python
indexes; `candidates()` then answers each key by dictionary lookup, inside the lookback, so resolving
thousands of entries issues no query. An entry whose transaction carries a document votes for the key
`document_merchant` only (its bank fields describe the provider, not the purchase: classifiers/history.md
§1), an undocumented one for the other five; the merchant lookup is a grouping of that small subset by the
canonical merchant name, with no index in the database. Between rounds `add()` takes
the entries a round confirmed, with no reload.

Each entry is one vote. Only a paired transfer carries a counter-account (and that account's
currency and closing date); a pair counts however it was made (a commit, or settling's step 4 once its
unit is confirmed), and an unpaired transfer is never confirmed, so never a voter.
Candidates come back ordered by (`booked_on`, entry id), so a proposal never depends on load order.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, cast

from sqlalchemy import Connection, Row, text

from app.core.ingest.identity import canonical_text
from app.core.plugins.classifier import EntryInput, HistoryKey, Vote
from app.core.plugins.text import jaccard, tokens
from app.core.resolution.confirmed import units_binds, units_sql

LOOKBACK_DAYS = 365

# How similar two token sets must be for new votes to be able to move an entry's proposal. This is the
# history classifier's threshold (classifiers/history.md §2, `JACCARD_MIN`); a test pins them together.
# Only the rounds after the first use it, to leave alone entries the new votes cannot reach.
TOKEN_REACH = 0.5

_SortKey = tuple[int, int]  # (booked_on ordinal, entry id)


@dataclass(frozen=True, slots=True)
class Grown:
    """What a batch of new votes added: the (key, value) buckets, and the distinct token sets."""

    buckets: frozenset[tuple[str, str | int]] = frozenset()
    token_sets: frozenset[frozenset[str]] = frozenset()


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

    def __init__(self, votes: Iterable[Vote] = ()) -> None:
        self._by: dict[str, dict[str | int, _Bucket]] = {
            "counterparty_ref": defaultdict(_Bucket),
            "counterparty_name": defaultdict(_Bucket),
            "payee": defaultdict(_Bucket),
            "tokens": defaultdict(_Bucket),
            "document_merchant": defaultdict(_Bucket),
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
        token_sets: set[frozenset[str]] = set()

        def put(key: str, value: str | int, k: _SortKey, v: Vote) -> None:
            self._by[key][value].add(k, v)
            grown.add((key, value))

        for v in votes:
            if v.entry_id in self._ids:
                continue
            self._ids.add(v.entry_id)
            k = _sort_key(v)
            if v.documented:
                merchant = canonical_text(v.document_merchant)
                if merchant:
                    put("document_merchant", merchant, k, v)
                continue
            put("counterparty_ref", canonical_text(v.counterparty_ref), k, v)
            put("counterparty_name", canonical_text(v.counterparty_name), k, v)
            if v.payee_id is not None:
                put("payee", v.payee_id, k, v)
            vote_tokens = tokens(v.counterparty_name, v.purpose)
            token_sets.add(vote_tokens)
            for tok in vote_tokens:
                put("tokens", tok, k, v)
        return Grown(frozenset(grown), frozenset(token_sets))

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
        found: list[Vote]
        if key == "tokens":
            seen: dict[int, Vote] = {}
            for tok in tokens(entry.counterparty_name, entry.purpose):
                bucket = buckets.get(tok)
                if bucket is not None:
                    for v in bucket.window(lo, hi):
                        seen[v.entry_id] = v
            found = sorted(seen.values(), key=_sort_key)
        else:
            if key == "payee":
                value: str | int | None = payee_id
            elif key == "document_merchant":
                value = canonical_text(entry.document_merchant)
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
        super().__init__()
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
    reads the payee resolved so far, which is stored or changes only through the other keys). For
    the token key only a vote similar enough to the entry (`TOKEN_REACH`) can matter.
    """
    b = grown.buckets
    if entry.documented:  # asked on the document's merchant only
        merchant = canonical_text(entry.document_merchant)
        return bool(merchant) and ("document_merchant", merchant) in b
    # a key whose value the entry lacks is never asked (history.md §2), so an empty value reaches nothing
    for key, raw in (
        ("counterparty_ref", entry.counterparty_ref),
        ("counterparty_name", entry.counterparty_name),
    ):
        value = canonical_text(raw)
        if value and (key, value) in b:
            return True
    if payee_id is not None and ("payee", payee_id) in b:
        return True
    mine = tokens(entry.counterparty_name, entry.purpose)
    return bool(mine) and any(mine & ts and jaccard(mine, ts) >= TOKEN_REACH for ts in grown.token_sets)


_VOTES = """
    WITH units AS ({units})
    SELECT e.id AS entry_id, e.account_id, e.booked_on, e.type, e.payee_id, e.category_id,
           CASE WHEN e.counterpart_entry_id IS NOT NULL THEN e.counter_account_id END AS counter_account_id,
           CASE WHEN e.counterpart_entry_id IS NOT NULL THEN ca.currency END AS counter_account_currency,
           CASE WHEN e.counterpart_entry_id IS NOT NULL THEN ca.closed_on END AS counter_account_closed_on,
           s.counterparty_ref, s.counterparty_name, s.purpose, s.booking_text, s.mandate_ref,
           (vd.document_id IS NOT NULL) AS documented, x.merchant_name AS document_merchant
      FROM units AS u
      JOIN ledger_entry AS e ON e.id = u.id
      JOIN source_transaction AS s ON s.id = e.source_transaction_id
      LEFT JOIN account AS ca ON ca.id = e.counter_account_id
      LEFT JOIN v_entry_document AS vd ON vd.ledger_entry_id = e.id
      LEFT JOIN external_document AS x ON x.id = vd.document_id
     WHERE u.unit_ok
       {only}
"""
_ALL_VOTES = text(_VOTES.format(units=units_sql(), only=""))
_VOTES_OF = text(_VOTES.format(units=units_sql(of_entries=True), only="AND e.id = ANY(:ids)"))


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
                documented=bool(m["documented"]),
                document_merchant=m["document_merchant"],
            )
        )
    return out


def load_votes(conn: Connection) -> list[Vote]:
    """Every voter: the one query of a settle."""
    return _votes(conn.execute(_ALL_VOTES, units_binds()))


def load_votes_of(conn: Connection, entry_ids: Sequence[int]) -> list[Vote]:
    """The votes among these entries (those that became confirmed in a round)."""
    if not entry_ids:
        return []
    return _votes(conn.execute(_VOTES_OF, {**units_binds(), "ids": list(entry_ids)}))


def load_snapshot(conn: Connection) -> HistorySnapshot:
    return HistorySnapshot(load_votes(conn))
