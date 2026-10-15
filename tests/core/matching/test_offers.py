"""The pure offers (spec §5.7 "Offers"): groups and their order, exactness, exclusions, the counter-leg, the
proposal rules, the effect hints and `has_more`."""

from __future__ import annotations

from datetime import date, timedelta

from app.core.matching import Leg, OfferWorld, PoolEntry, Summary, offers
from app.core.matching.offers import OfferSet
from app.core.plugins.classifier import AccountFact

D = date(2026, 3, 10)
A, B, C, USD_ACC, CASH = 1, 2, 3, 4, 5
ACCOUNTS = {
    A: AccountFact(A, "EUR", None),
    B: AccountFact(B, "EUR", None),
    C: AccountFact(C, "EUR", None),
    USD_ACC: AccountFact(USD_ACC, "USD", None),
    CASH: AccountFact(CASH, "EUR", None),
}
SYNCED = {A: True, B: True, C: True, USD_ACC: False, CASH: False}
WORLD = OfferWorld(ACCOUNTS, SYNCED)
W = 7


def me(i: int = 1, account: int = A, amount: int = -1000, on: date = D, **kw) -> Leg:  # noqa: ANN003
    currency = kw.pop("currency", "USD" if account == USD_ACC else "EUR")
    return Leg(i, account, currency, amount, on, **kw)


def p(
    i: int,
    account: int = B,
    amount: int = 1000,
    on: date = D,
    *,
    partner: Summary | None = None,
    original: bool = True,
    description: str | None = None,
    **kw,  # noqa: ANN003
) -> PoolEntry:
    currency = kw.pop("currency", "USD" if account == USD_ACC else "EUR")
    return PoolEntry(Leg(i, account, currency, amount, on, **kw), original, description, partner)


def untyped(i: int, account: int = B, amount: int = 1000, on: date = D, **kw) -> PoolEntry:  # noqa: ANN003
    return p(i, account, amount, on, type=None, **kw)


def summary(i: int, account: int = C, amount: int = -1000) -> Summary:
    return Summary(i, account, D, amount, "EUR", "elsewhere")


def run(leg: Leg, *pool: PoolEntry, window: int = W, world: OfferWorld = WORLD, **kw) -> OfferSet:  # noqa: ANN003
    return offers(leg, pool, world, window, **kw)


def ids(result: OfferSet) -> list[int | None]:
    return [o.entry_id for o in result.offers]


# ---- the groups and their order -----------------------------------------------------------------


def test_open_offers_come_first_then_paired_elsewhere() -> None:
    res = run(
        me(counter_account_id=B),
        p(10, partner=summary(99)),
        p(11, amount=700),
        untyped(12, amount=1000),
    )
    assert [o.kind for o in res.offers] == ["untyped_entry", "open_leg", "paired_elsewhere"]
    assert ids(res) == [12, 11, 10]


def test_an_open_offer_of_any_amount_is_offered_exact_first_then_by_date_distance() -> None:
    res = run(
        me(counter_account_id=B),
        p(10, amount=500, on=D),
        p(11, amount=1000, on=D + timedelta(days=5)),
        p(12, amount=300, on=D + timedelta(days=1)),
    )
    assert ids(res) == [11, 10, 12]  # the exact one first although the farthest; then by distance
    assert [o.exact for o in res.offers] == [True, False, False]


def test_ties_break_to_the_earlier_booking_date_then_the_lower_id() -> None:
    res = run(
        me(counter_account_id=B),
        p(10, amount=1, on=D + timedelta(days=2)),
        p(12, amount=2, on=D - timedelta(days=2)),
        p(11, amount=3, on=D - timedelta(days=2)),
    )
    assert ids(res) == [11, 12, 10]


def test_paired_elsewhere_follows_the_same_order_and_carries_its_partner() -> None:
    other = summary(98)
    res = run(
        me(counter_account_id=B),
        p(10, amount=500, partner=other),
        p(11, amount=1000, on=D + timedelta(days=4), partner=summary(97)),
    )
    assert ids(res) == [11, 10]
    assert [o.paired_with for o in res.offers] == [summary(97), other]
    assert all(o.kind == "paired_elsewhere" for o in res.offers)


def test_a_leg_outside_the_window_is_not_offered_and_the_window_edge_is() -> None:
    res = run(
        me(counter_account_id=B),
        p(10, on=D + timedelta(days=W)),
        p(11, on=D + timedelta(days=W + 1)),
        p(12, on=D - timedelta(days=W + 1)),
    )
    assert ids(res) == [10]


# ---- who is offered ---------------------------------------------------------------------------------


def test_only_the_counter_account_when_it_is_known() -> None:
    res = run(me(counter_account_id=B), p(10, account=B), p(11, account=C), p(12, account=A))
    assert ids(res) == [10]


def test_without_a_counter_account_every_account_the_currency_rule_allows() -> None:
    res = run(me(), p(10, account=B), p(11, account=C), p(12, account=USD_ACC), p(13, account=A))
    assert sorted(i for i in ids(res) if i is not None) == [10, 11]  # not the dollar account, not its own


def test_with_an_instructed_currency_only_accounts_in_it() -> None:
    leg = me(amount=-1000, instructed_amount=-1100, instructed_currency="USD")
    res = run(leg, p(10, account=B), p(11, account=USD_ACC, amount=1100))
    assert ids(res) == [11]


def test_own_partner_same_sign_zero_and_flows_are_never_offered() -> None:
    res = run(
        me(counter_account_id=B),
        p(10),
        p(11, amount=-1000),
        p(12, amount=0),
        p(13, type="flow"),
        partner_id=10,
    )
    assert ids(res) == []


def test_an_unpaired_leg_with_another_known_counter_account_is_excluded() -> None:
    res = run(
        me(counter_account_id=B),
        p(10, counter_account_id=C),  # wants another account
        p(11, counter_account_id=A),  # wants this one
        p(12),  # does not know
    )
    assert ids(res) == [11, 12]


def test_a_leg_paired_elsewhere_is_offered_whatever_its_counter_account() -> None:
    res = run(me(counter_account_id=B), p(10, counter_account_id=C, partner=summary(98)))
    assert ids(res) == [10]


def test_an_untyped_entry_is_offered_only_when_it_is_an_original() -> None:
    res = run(me(counter_account_id=B), untyped(10), untyped(11, original=False))
    assert [o.kind for o in res.offers] == ["untyped_entry"]
    assert ids(res) == [10]


# ---- exactness --------------------------------------------------------------------------------------


def test_exact_across_currencies_by_the_instructed_amount_of_either_leg() -> None:
    mine = me(amount=-1000, instructed_amount=-1100, instructed_currency="USD", counter_account_id=USD_ACC)
    res = run(mine, p(10, USD_ACC, 1100), p(11, USD_ACC, 1000))
    assert ids(res) == [10, 11, None] and [o.exact for o in res.offers] == [True, False, False]
    theirs = run(
        me(counter_account_id=USD_ACC, amount=-1100, currency="EUR"),
        p(12, USD_ACC, 1000, instructed_amount=1100, instructed_currency="EUR"),
    )
    assert theirs.offers[0].exact


def test_no_exactness_without_equal_and_opposite_amounts() -> None:
    res = run(me(counter_account_id=B), p(10, amount=999))
    assert not res.offers[0].exact


# ---- the counter-leg --------------------------------------------------------------------------------


def test_counter_leg_for_an_unpartnered_leg_on_an_unsynced_open_counter_account() -> None:
    res = run(me(counter_account_id=CASH, purpose="atm"), purpose="GA AUSZAHLUNG")
    (offer,) = res.offers
    assert offer.kind == "counter_leg" and offer.entry_id is None
    assert (offer.account_id, offer.booked_on, offer.amount, offer.description) == (
        CASH,
        D,
        1000,
        "GA AUSZAHLUNG",
    )
    assert offer.counter_leg is not None
    assert (offer.counter_leg.amount, offer.counter_leg.needs_received_amount) == (1000, False)
    assert offer.counter_leg.purpose == "GA AUSZAHLUNG" and offer.counter_leg.booked_on == D


def test_no_counter_leg_on_a_synced_account_without_a_counter_account_or_with_a_partner() -> None:
    assert run(me(counter_account_id=B)).offers == ()
    assert run(me()).offers == ()
    assert run(me(counter_account_id=CASH), partner_id=7).offers == ()


def test_no_counter_leg_on_an_account_closed_before_the_date() -> None:
    accounts = {**ACCOUNTS, CASH: AccountFact(CASH, "EUR", None, closed_on=D - timedelta(days=1))}
    assert run(me(counter_account_id=CASH), world=OfferWorld(accounts, SYNCED)).offers == ()
    accounts = {**ACCOUNTS, CASH: AccountFact(CASH, "EUR", None, closed_on=D)}
    assert len(run(me(counter_account_id=CASH), world=OfferWorld(accounts, SYNCED)).offers) == 1


def test_a_cross_currency_counter_leg_takes_the_instructed_amount() -> None:
    leg = me(amount=-1000, instructed_amount=-1100, instructed_currency="USD", counter_account_id=USD_ACC)
    (offer,) = run(leg).offers
    assert offer.counter_leg is not None
    assert (offer.amount, offer.currency, offer.counter_leg.needs_received_amount) == (1100, "USD", False)


def test_a_cross_currency_counter_leg_without_an_instructed_amount_needs_the_amount_received() -> None:
    (offer,) = run(me(counter_account_id=USD_ACC)).offers  # a user's choice of a dollar account
    assert offer.counter_leg is not None
    assert offer.amount is None and offer.counter_leg.amount is None
    assert offer.counter_leg.needs_received_amount


def test_no_counter_leg_where_the_currency_rule_is_broken() -> None:
    leg = me(amount=-1000, instructed_amount=-1100, instructed_currency="USD", counter_account_id=CASH)
    assert run(leg).offers == ()


# ---- the proposal -----------------------------------------------------------------------------------


def test_an_exact_open_offer_is_proposed_the_first_by_order() -> None:
    res = run(
        me(counter_account_id=B),
        p(10, amount=500),
        p(12, amount=1000, on=D + timedelta(days=3)),
        p(11, amount=1000, on=D + timedelta(days=1)),
    )
    assert res.proposal is not None and (res.proposal.kind, res.proposal.entry_id) == ("entry", 11)
    assert [o.proposed for o in res.offers] == [True, False, False]


def test_an_untyped_exact_entry_is_proposed_too() -> None:
    res = run(me(), untyped(10))
    assert res.proposal is not None and res.proposal.entry_id == 10 and res.offers[0].proposed


def test_with_no_open_offer_at_all_the_counter_leg_is_proposed() -> None:
    res = run(me(counter_account_id=CASH), p(10, account=CASH, partner=summary(98)))
    assert res.proposal is not None and res.proposal.kind == "counter_leg" and res.proposal.entry_id is None
    assert [o.proposed for o in res.offers] == [False, True]  # paired elsewhere is never proposed


def test_open_offers_of_another_amount_propose_nothing_not_even_the_counter_leg() -> None:
    res = run(me(counter_account_id=CASH), p(10, account=CASH, amount=900))
    assert res.proposal is None
    assert [o.kind for o in res.offers] == ["open_leg", "counter_leg"]
    assert not any(o.proposed for o in res.offers)


def test_a_leg_paired_elsewhere_is_never_proposed() -> None:
    res = run(me(counter_account_id=B), p(10, partner=summary(98)))
    assert res.proposal is None and not res.offers[0].proposed


def test_a_leg_that_has_a_partner_gets_offers_but_no_proposal() -> None:
    res = run(me(counter_account_id=B), p(10), partner_id=77)
    assert ids(res) == [10] and res.proposal is None


# ---- the effect hints -------------------------------------------------------------------------------


def test_an_untyped_entry_types_as_transfer() -> None:
    res = run(me(counter_account_id=B), untyped(10), p(11))
    assert [o.effect.types_as_transfer for o in res.offers] == [True, False]


def test_a_fee_is_split_off_the_larger_leg() -> None:
    res = run(me(amount=-1000, counter_account_id=B), p(10, amount=750), p(11, amount=1250))
    smaller, larger = res.offers
    assert smaller.effect.fee is not None
    assert (smaller.effect.fee.larger_entry_id, smaller.effect.fee.difference) == (1, 250)
    assert (smaller.effect.fee.currency) == "EUR"
    assert larger.effect.fee is not None
    assert (larger.effect.fee.larger_entry_id, larger.effect.fee.difference) == (11, 250)


def test_no_fee_for_an_exact_offer_across_currencies_or_a_paired_leg() -> None:
    exact = run(me(counter_account_id=B), p(10))
    assert exact.offers[0].effect.fee is None
    cross = run(me(counter_account_id=USD_ACC), p(10, USD_ACC, 5))
    assert cross.offers[0].effect.fee is None
    elsewhere = run(me(counter_account_id=B), p(10, amount=5, partner=summary(98)))
    assert elsewhere.offers[0].effect.fee is None


def test_a_pick_breaks_both_former_pairs() -> None:
    res = run(me(counter_account_id=B), p(10, partner=summary(98)), p(11), partner_id=77)
    by_id = {o.entry_id: o for o in res.offers}
    assert by_id[10].effect.breaks_pair_with == (77, 98)
    assert by_id[11].effect.breaks_pair_with == (77,)
    fresh = run(me(counter_account_id=B), p(10, partner=summary(98)), p(11))
    assert {o.entry_id: o.effect.breaks_pair_with for o in fresh.offers} == {10: (98,), 11: ()}


# ---- has_more -----------------------------------------------------------------------------------------


def test_has_more_when_a_candidate_lies_beyond_the_window_up_to_the_cap() -> None:
    far = p(10, on=D + timedelta(days=30))
    assert run(me(counter_account_id=B), far).has_more
    assert not run(me(counter_account_id=B), far, window=30).has_more
    assert not run(me(counter_account_id=B), p(10, on=D + timedelta(days=91))).has_more
    assert run(me(counter_account_id=B), p(10, on=D + timedelta(days=90))).has_more


def test_has_more_counts_only_what_would_be_offered() -> None:
    far = D + timedelta(days=30)
    res = run(
        me(counter_account_id=B),
        p(10, account=C, on=far),  # another account
        p(11, on=far, type="flow"),
        p(12, on=far, counter_account_id=C),  # wants another account
        p(13, on=far, amount=-5),  # same sign
    )
    assert not res.has_more
