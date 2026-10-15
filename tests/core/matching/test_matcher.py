"""The pure matcher (spec §5.7): candidate filters, pairing order, standing counter-accounts."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core.matching import Leg, candidates, pair_all, real_end_to_end_id, unmatched, waiting
from app.core.plugins.classifier import AccountFact

D = date(2026, 3, 10)
A, B, C, USD_ACC = 1, 2, 3, 4
ACCOUNTS = {
    A: AccountFact(A, "EUR", None),
    B: AccountFact(B, "EUR", None),
    C: AccountFact(C, "EUR", None),
    USD_ACC: AccountFact(USD_ACC, "USD", None),
}
W = 7


def leg(i: int, account: int = A, amount: int = -1000, on: date = D, **kw) -> Leg:  # noqa: ANN003
    currency = kw.pop("currency", "USD" if account == USD_ACC else "EUR")
    return Leg(i, account, currency, amount, on, **kw)


def cand(first: Leg, *pool: Leg, window: int = W) -> list[int]:
    return [m.entry_id for m in candidates(first, pool, window, accounts=ACCOUNTS)]


def pairs(*legs: Leg, window: int = W) -> list[tuple[int, int]]:
    return [(p.leg_id, p.partner_id) for p in pair_all(legs, window, ACCOUNTS)]


# ---- candidate filters ----------------------------------------------------------------------


def test_the_basic_candidate() -> None:
    assert cand(leg(1), leg(2, B, 1000)) == [2]


def test_same_sign_other_account_and_type_are_filtered() -> None:
    assert cand(leg(1), leg(2, B, -1000)) == []
    assert cand(leg(1), leg(2, A, 1000)) == []
    assert cand(leg(1), leg(2, B, 1000, type="flow")) == []
    assert cand(leg(1), leg(2, B, 1000, type=None)) == []


def test_window_edges() -> None:
    assert cand(leg(1), leg(2, B, 1000, on=D + timedelta(days=W))) == [2]
    assert cand(leg(1), leg(2, B, 1000, on=D - timedelta(days=W))) == [2]
    assert cand(leg(1), leg(2, B, 1000, on=D + timedelta(days=W + 1))) == []
    assert cand(leg(1), leg(2, B, 1000, on=D - timedelta(days=W + 1))) == []
    assert cand(leg(1), leg(2, B, 1000, on=D), window=0) == [2]
    assert cand(leg(1), leg(2, B, 1000, on=D + timedelta(days=1)), window=0) == []


def test_amount_must_match_exactly_in_the_same_currency() -> None:
    assert cand(leg(1), leg(2, B, 999)) == []
    assert cand(leg(1), leg(2, B, 1001)) == []


def test_no_conversion_a_different_currency_with_equal_numbers_is_no_match() -> None:
    assert cand(leg(1), leg(2, USD_ACC, 1000)) == []


def test_cross_currency_by_instructed_amount_both_directions() -> None:
    withdrawal = leg(1, A, -1000, instructed_amount=-1100, instructed_currency="USD")
    received = leg(2, USD_ACC, 1100)
    assert cand(withdrawal, received) == [2]
    assert cand(received, withdrawal) == [1]
    assert cand(withdrawal, leg(3, USD_ACC, 1099)) == []
    assert cand(withdrawal, leg(3, USD_ACC, 1100, currency="GBP")) == []  # not the instructed currency


def test_the_other_side_knows_the_conversion() -> None:
    # the USD leg reports the EUR amount it came from
    usd = leg(1, USD_ACC, 1100, instructed_amount=1000, instructed_currency="EUR")
    eur = leg(2, A, -1000)
    assert cand(usd, eur) == [2] and cand(eur, usd) == [1]


def test_currency_rule_for_a_leg_with_an_instructed_currency() -> None:
    # same-currency equal amounts, but the money arrived in USD: a EUR account is not its counter-account
    withdrawal = leg(1, A, -1000, instructed_amount=-1000, instructed_currency="USD")
    assert cand(withdrawal, leg(2, B, 1000)) == []


def test_counter_account_filters_both_ways() -> None:
    assert cand(leg(1, counter_account_id=B), leg(2, B, 1000)) == [2]
    assert cand(leg(1, counter_account_id=C), leg(2, B, 1000)) == []
    assert cand(leg(1), leg(2, B, 1000, counter_account_id=C)) == []
    assert cand(leg(1), leg(2, B, 1000, counter_account_id=A)) == [2]


@pytest.mark.parametrize("placeholder", ["NOTPROVIDED", "notprovided", "NonRef", "", "  "])
def test_placeholder_end_to_end_ids_count_as_absent(placeholder: str) -> None:
    assert real_end_to_end_id(placeholder) is None
    assert cand(leg(1, end_to_end_id="X1"), leg(2, B, 1000, end_to_end_id=placeholder)) == [2]
    assert cand(leg(1, end_to_end_id=placeholder), leg(2, B, 1000, end_to_end_id="X2")) == [2]


def test_real_end_to_end_ids_must_be_equal() -> None:
    assert cand(leg(1, end_to_end_id="X1"), leg(2, B, 1000, end_to_end_id="X1")) == [2]
    assert cand(leg(1, end_to_end_id="X1"), leg(2, B, 1000, end_to_end_id="X2")) == []
    assert cand(leg(1, end_to_end_id="X1"), leg(2, B, 1000)) == [2]


def test_purpose_is_not_a_filter() -> None:
    assert cand(leg(1, purpose="rent"), leg(2, B, 1000, purpose="miete")) == [2]


# ---- pairing ---------------------------------------------------------------------------------


def test_i33_an_automatic_pair_needs_a_known_counter_account() -> None:
    assert pairs(leg(1), leg(2, B, 1000)) == []
    assert pairs(leg(1, counter_account_id=B), leg(2, B, 1000)) == [(1, 2)]
    assert pairs(leg(1), leg(2, B, 1000, counter_account_id=A)) == [(1, 2)]


def test_the_pair_sets_a_counter_account_only_on_a_leg_without_one() -> None:
    (p,) = pair_all([leg(1, counter_account_id=B), leg(2, B, 1000)], W, ACCOUNTS)
    assert (p.leg_counter_account, p.partner_counter_account) == (None, A)
    (p,) = pair_all([leg(1, counter_account_id=B), leg(2, B, 1000, counter_account_id=A)], W, ACCOUNTS)
    assert (p.leg_counter_account, p.partner_counter_account) == (None, None)


def test_a_leg_with_no_candidate_stays_unpaired() -> None:
    assert pairs(leg(1, counter_account_id=B), leg(2, B, 999)) == []


def test_same_purpose_beats_a_closer_date() -> None:
    a = leg(1, counter_account_id=B, purpose="rent")
    near = leg(2, B, 1000, on=D, purpose="other")
    far = leg(3, B, 1000, on=D + timedelta(days=3), purpose="rent")
    assert pairs(a, near, far) == [(1, 3)]


def test_without_a_purpose_match_the_closest_date_wins() -> None:
    a = leg(1, counter_account_id=B, purpose="rent")
    near = leg(2, B, 1000, on=D + timedelta(days=1), purpose="x")
    far = leg(3, B, 1000, on=D + timedelta(days=4), purpose="y")
    assert pairs(a, far, near) == [(1, 2)]


def test_equal_distance_prefers_earlier_booking_then_lower_id() -> None:
    a = leg(1, counter_account_id=B)
    before = leg(5, B, 1000, on=D - timedelta(days=2))
    after = leg(2, B, 1000, on=D + timedelta(days=2))
    assert pairs(a, after, before) == [(5, 1)]  # the earlier booking is processed first
    same_day_hi, same_day_lo = leg(9, B, 1000), leg(7, B, 1000)
    assert pairs(a, same_day_hi, same_day_lo) == [(1, 7)]
    assert pairs(a, after, leg(6, B, 1000, on=D + timedelta(days=2))) == [(1, 2)]


def test_legs_are_processed_in_date_order_with_id_ties() -> None:
    # leg 10 (early) and leg 3 (later) both fit candidate 20; the earlier booking gets it
    early = leg(10, counter_account_id=B, on=D)
    late = leg(3, counter_account_id=B, on=D + timedelta(days=1))
    target = leg(20, B, 1000, on=D)
    assert pairs(late, early, target) == [(10, 20)]
    # same day: the lower id goes first
    x, y = leg(4, counter_account_id=B), leg(8, counter_account_id=B)
    assert pairs(y, x, target) == [(4, 20)]


def test_a_paired_leg_is_not_offered_to_the_next() -> None:
    x = leg(1, counter_account_id=B)
    y = leg(2, counter_account_id=B)
    t1, t2 = leg(3, B, 1000), leg(4, B, 1000)
    assert pairs(x, y, t1, t2) == [(1, 3), (2, 4)]


def test_pairing_is_invariant_under_input_order() -> None:
    legs = [
        leg(1, counter_account_id=B),
        leg(2, counter_account_id=B, on=D + timedelta(days=1)),
        leg(3, B, 1000),
        leg(4, B, 1000, on=D + timedelta(days=2)),
        leg(5, C, 1000, counter_account_id=A),
    ]
    expected = pairs(*legs)
    assert expected
    for rotation in range(len(legs)):
        assert pairs(*legs[rotation:], *legs[:rotation]) == expected
    assert pairs(*reversed(legs)) == expected


def test_cross_currency_pair_through_pair_all() -> None:
    w = leg(1, A, -1000, counter_account_id=USD_ACC, instructed_amount=-1100, instructed_currency="USD")
    r = leg(2, USD_ACC, 1100)
    (p,) = pair_all([r, w], W, ACCOUNTS)
    assert (p.leg_id, p.partner_id, p.leg_counter_account, p.partner_counter_account) == (1, 2, None, A)


# ---- waiting and unmatched ---------------------------------------------------------------------


def test_waiting_and_unmatched() -> None:
    held = leg(1, counter_account_id=B)
    end = D + timedelta(days=W)
    assert waiting(held, counter_synced=True, synced_through=None, window=W)
    assert waiting(held, counter_synced=True, synced_through=end - timedelta(days=1), window=W)
    assert not waiting(held, counter_synced=True, synced_through=end, window=W)
    assert not waiting(held, counter_synced=False, synced_through=None, window=W)
    assert not waiting(leg(1), counter_synced=True, synced_through=None, window=W)
    assert unmatched(held, paired=False, counter_synced=True, synced_through=end, window=W)
    assert not unmatched(held, paired=False, counter_synced=True, synced_through=None, window=W)
    assert not unmatched(held, paired=True, counter_synced=False, synced_through=None, window=W)
    assert unmatched(leg(1), paired=False, counter_synced=False, synced_through=None, window=W)
