"""Which legs may pair with a leg (spec §5.7 "Candidates"): one predicate, used everywhere.

Nothing here converts between currencies (I27): a cross-currency match needs one leg's instructed
amount to equal the other's amount, negated.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from app.core.matching.leg import Leg
from app.core.plugins.classifier import AccountFact
from app.core.resolution.accounts import arrival_currency_ok

PLACEHOLDER_END_TO_END_IDS = frozenset({"notprovided", "nonref", ""})


def real_end_to_end_id(value: str | None) -> str | None:
    """The id as compared, or None where the source carries none or a placeholder (case-insensitive)."""
    if value is None:
        return None
    folded = value.strip().casefold()
    return None if folded in PLACEHOLDER_END_TO_END_IDS else folded


def amounts_match(a: Leg, b: Leg) -> bool:
    """Equal and opposite in one currency, or one leg's instructed amount against the other's amount."""
    if a.currency == b.currency and a.amount == -b.amount:
        return True
    if a.instructed_currency is not None and a.instructed_amount is not None:
        if a.instructed_currency == b.currency and a.instructed_amount == -b.amount:
            return True
    if b.instructed_currency is not None and b.instructed_amount is not None:
        if b.instructed_currency == a.currency and b.instructed_amount == -a.amount:
            return True
    return False


def is_candidate(leg: Leg, other: Leg, window: int, accounts: Mapping[int, AccountFact]) -> bool:
    """Whether `other` is a candidate partner of `leg` (symmetric; both are unpaired transfer legs).

    Beyond the filters of §5.7 the currency rule (I11) is applied, as everywhere a counter-account is
    chosen: the other leg's account is in the currency the money arrived in.
    """
    if leg.type != "transfer" or other.type != "transfer":
        return False
    if leg.account_id == other.account_id or leg.entry_id == other.entry_id:
        return False
    if (leg.amount > 0) == (other.amount > 0) or leg.amount == 0 or other.amount == 0:
        return False
    if abs((leg.booked_on - other.booked_on).days) > window:
        return False
    if not amounts_match(leg, other):
        return False
    if leg.counter_account_id is not None and leg.counter_account_id != other.account_id:
        return False
    if other.counter_account_id is not None and other.counter_account_id != leg.account_id:
        return False
    a, b = real_end_to_end_id(leg.end_to_end_id), real_end_to_end_id(other.end_to_end_id)
    if a is not None and b is not None and a != b:
        return False
    return _arrives_in_currency(leg, other, accounts) and _arrives_in_currency(other, leg, accounts)


def _arrives_in_currency(leg: Leg, other: Leg, accounts: Mapping[int, AccountFact]) -> bool:
    """I11 for a leg that says what arrived (an instructed currency); one that does not has no say:
    its own currency is only what a machine proposes, not a filter."""
    if leg.instructed_currency is None:
        return True
    account = accounts.get(other.account_id)
    return account is None or arrival_currency_ok(leg.instructed_currency, leg.currency, account)


def candidates(
    leg: Leg, pool: Iterable[Leg], window: int, *, accounts: Mapping[int, AccountFact]
) -> list[Leg]:
    """The legs of `pool` that are candidates of `leg`, in pool order. `pool` holds unpaired legs."""
    return [m for m in pool if is_candidate(leg, m, window, accounts)]
