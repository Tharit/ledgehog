"""Date-ordered greedy pairing (spec §5.7 "Pairing"), pure.

Legs are processed by (booked_on, entry id). A leg with candidates among the remaining legs prefers
those whose canonical purpose equals its own (a non-empty one), then the closest booked date, then the earlier
booked_on, then the lower entry id. An automatic pair needs a known counter-account on one leg at
least (I33). Lookups are keyed on the amount (and the instructed amount), so the work is
proportional to the matches, not to the square of the legs.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from app.core.matching.candidates import is_candidate
from app.core.matching.leg import Leg
from app.core.plugins.classifier import AccountFact

# the basis a counter-account set by a pair carries (§5.7)
PAIR_BASIS: Mapping[str, str] = {"from": "counterpart"}

_Key = tuple[str, int]
_Bucket = list[Leg]


@dataclass(frozen=True, slots=True)
class Pair:
    """Two legs paired. `*_counter_account` is the value the pair sets on that leg: its partner's
    account, only for a leg that had none (its basis is `PAIR_BASIS`); else None."""

    leg_id: int
    partner_id: int
    leg_counter_account: int | None
    partner_counter_account: int | None


def _order(leg: Leg) -> tuple[date, int]:
    return (leg.booked_on, leg.entry_id)


def _pair_of(leg: Leg, partner: Leg) -> Pair:
    return Pair(
        leg_id=leg.entry_id,
        partner_id=partner.entry_id,
        leg_counter_account=partner.account_id if leg.counter_account_id is None else None,
        partner_counter_account=leg.account_id if partner.counter_account_id is None else None,
    )


def _preferred(leg: Leg, options: list[Leg]) -> Leg:
    # no purpose is no evidence: two empty purposes do not count as equal
    same_purpose = [m for m in options if leg.purpose and m.purpose == leg.purpose]
    chosen = same_purpose or options
    return min(
        chosen,
        key=lambda m: (abs((m.booked_on - leg.booked_on).days), m.booked_on, m.entry_id),
    )


class _Index:
    """The unpaired legs by amount, each bucket sorted by (booked_on, id) so a date range is a slice."""

    def __init__(self, legs: Iterable[Leg]) -> None:
        self._amount: dict[_Key, _Bucket] = defaultdict(list)
        self._instructed: dict[_Key, _Bucket] = defaultdict(list)
        for leg in legs:  # `legs` arrive sorted
            self._amount[(leg.currency, leg.amount)].append(leg)
            if leg.instructed_currency is not None and leg.instructed_amount is not None:
                self._instructed[(leg.instructed_currency, leg.instructed_amount)].append(leg)

    def remove(self, leg: Leg) -> None:
        self._drop(self._amount, (leg.currency, leg.amount), leg)
        if leg.instructed_currency is not None and leg.instructed_amount is not None:
            self._drop(self._instructed, (leg.instructed_currency, leg.instructed_amount), leg)

    @staticmethod
    def _drop(table: dict[_Key, _Bucket], key: _Key, leg: Leg) -> None:
        bucket = table[key]
        i = bisect_left(bucket, _order(leg), key=_order)
        del bucket[i]

    def near(self, leg: Leg, window: int) -> dict[int, Leg]:
        """The remaining legs whose amounts could match `leg`'s and that are within the window."""
        lo, hi = leg.booked_on - timedelta(days=window), leg.booked_on + timedelta(days=window)
        found: dict[int, Leg] = {}
        probes: list[tuple[dict[_Key, _Bucket], _Key]] = [
            (self._amount, (leg.currency, -leg.amount)),  # same currency
            (self._instructed, (leg.currency, -leg.amount)),  # the other leg's instructed amount is ours
        ]
        if leg.instructed_currency is not None and leg.instructed_amount is not None:
            probes.append((self._amount, (leg.instructed_currency, -leg.instructed_amount)))
        for table, key in probes:
            bucket = table.get(key)
            if not bucket:
                continue
            start = bisect_left(bucket, lo, key=lambda m: m.booked_on)
            stop = bisect_right(bucket, hi, key=lambda m: m.booked_on)
            for m in bucket[start:stop]:
                found[m.entry_id] = m
        return found


def pair_all(legs: Iterable[Leg], window: int, accounts: Mapping[int, AccountFact]) -> list[Pair]:
    """Pair the unpaired transfer legs `legs`; the result does not depend on their order in the input."""
    ordered = sorted((leg for leg in legs if leg.type == "transfer"), key=_order)
    index = _Index(ordered)
    gone: set[int] = set()
    pairs: list[Pair] = []
    for leg in ordered:
        if leg.entry_id in gone:
            continue
        options = [
            m
            for m in index.near(leg, window).values()
            if m.entry_id != leg.entry_id
            and (leg.counter_account_id is not None or m.counter_account_id is not None)  # I33
            and is_candidate(leg, m, window, accounts)
        ]
        if not options:
            continue
        partner = _preferred(leg, options)
        pairs.append(_pair_of(leg, partner))
        for member in (leg, partner):
            gone.add(member.entry_id)
            index.remove(member)
    return pairs
