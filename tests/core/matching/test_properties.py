"""Properties of date-ordered pairing, and the indexed pairing against a brute-force reading of §5.7."""

from __future__ import annotations

import random
import time
from datetime import date, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.matching import Leg, Pair, is_candidate, pair_all
from app.core.matching.candidates import real_end_to_end_id
from app.core.plugins.classifier import AccountFact

D = date(2026, 3, 10)
ACCOUNTS = {i: AccountFact(i, "EUR" if i < 4 else "USD", None) for i in range(1, 6)}


@st.composite
def legs_st(draw: st.DrawFn) -> list[Leg]:
    n = draw(st.integers(0, 18))
    out = []
    for i in range(1, n + 1):
        account = draw(st.integers(1, 5))
        amount = draw(st.sampled_from([-300, -200, -100, 100, 200, 300])) * draw(st.sampled_from([1, 1, 11]))
        currency = ACCOUNTS[account].currency
        instructed = draw(st.sampled_from([None, (1, "USD"), (-1, "EUR")]))
        out.append(
            Leg(
                i,
                account,
                currency,
                amount,
                D + timedelta(days=draw(st.integers(0, 12))),
                counter_account_id=draw(st.sampled_from([None, None, 1, 2, 3, 4, 5])),
                end_to_end_id=draw(st.sampled_from([None, "NOTPROVIDED", "E1", "E2"])),
                purpose=draw(st.sampled_from(["", "a", "b"])),
                instructed_amount=None if instructed is None else amount * instructed[0] * 2,
                instructed_currency=None if instructed is None else instructed[1],
            )
        )
    return out


def reference(legs: list[Leg], window: int) -> list[Pair]:
    """§5.7 read literally, O(n^2): the oracle for the indexed implementation."""
    remaining = sorted(legs, key=lambda x: (x.booked_on, x.entry_id))
    out: list[Pair] = []
    while remaining:
        leg = remaining.pop(0)
        options = [
            m
            for m in remaining
            if (leg.counter_account_id is not None or m.counter_account_id is not None)
            and is_candidate(leg, m, window, ACCOUNTS)
        ]
        if not options:
            continue
        pool = [m for m in options if leg.purpose and m.purpose == leg.purpose] or options
        best = min(pool, key=lambda m: (abs((m.booked_on - leg.booked_on).days), m.booked_on, m.entry_id))
        remaining.remove(best)
        out.append(
            Pair(
                leg.entry_id,
                best.entry_id,
                best.account_id if leg.counter_account_id is None else None,
                leg.account_id if best.counter_account_id is None else None,
            )
        )
    return out


@settings(max_examples=300, deadline=None)
@given(legs_st(), st.integers(0, 8), st.randoms(use_true_random=False))
def test_pairing_properties(legs: list[Leg], window: int, rnd: random.Random) -> None:
    by_id = {x.entry_id: x for x in legs}
    pairs = pair_all(legs, window, ACCOUNTS)

    used = [i for p in pairs for i in (p.leg_id, p.partner_id)]
    assert len(used) == len(set(used)), "a leg is in two pairs"

    for p in pairs:
        a, b = by_id[p.leg_id], by_id[p.partner_id]
        assert a.account_id != b.account_id and (a.amount > 0) != (b.amount > 0)  # I10
        if a.currency == b.currency and not (a.instructed_currency or b.instructed_currency):
            assert a.amount == -b.amount
        assert a.counter_account_id in (None, b.account_id)
        assert b.counter_account_id in (None, a.account_id)  # I10, I24
        ea, eb = real_end_to_end_id(a.end_to_end_id), real_end_to_end_id(b.end_to_end_id)
        assert ea is None or eb is None or ea == eb  # I24
        assert a.counter_account_id is not None or b.counter_account_id is not None  # I33
        assert (p.leg_counter_account is None) == (a.counter_account_id is not None)
        assert (p.partner_counter_account is None) == (b.counter_account_id is not None)

    assert pairs == reference(legs, window)  # the lookups lose nothing

    shuffled = legs[:]
    rnd.shuffle(shuffled)
    assert pair_all(shuffled, window, ACCOUNTS) == pairs  # input order is irrelevant

    leftover = [x for x in legs if x.entry_id not in set(used)]
    assert pair_all(leftover, window, ACCOUNTS) == []  # idempotent: nothing left that pairs


def test_five_thousand_legs_are_paired_quickly() -> None:
    rnd = random.Random(7)
    legs: list[Leg] = []
    for i in range(1, 2501):
        amount = rnd.choice([-1, 1]) * rnd.randint(1, 400) * 100
        day = D + timedelta(days=rnd.randint(0, 90))
        out_acc, in_acc = rnd.sample([1, 2, 3], 2)
        legs.append(Leg(2 * i, out_acc, "EUR", -abs(amount), day, counter_account_id=in_acc))
        legs.append(Leg(2 * i + 1, in_acc, "EUR", abs(amount), day + timedelta(days=rnd.randint(0, 5))))
    started = time.perf_counter()
    pairs = pair_all(legs, 7, ACCOUNTS)
    elapsed = time.perf_counter() - started
    assert len(pairs) > 2000
    assert elapsed < 2.0, f"{elapsed:.2f}s"
