"""Picking a partner (spec §5.7 "Offers"): whether a stored entry may be the partner of a transfer leg.

Pure. `check_pick` is the server's validation of a draft's pick: the partner must be OFFERED for the leg
(the same filters `matching.offers` applies, read from stored entries), whatever the amount. It returns the
`Problem` that refuses the pick, or None. The overlay applies a valid pick (`overlay._apply_pairing`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from app.core.matching import MAX_WINDOW
from app.core.plugins.classifier import AccountFact
from app.core.resolution.accounts import arrival_currency_ok
from app.core.units.plan import Problem, StoredUnit


@dataclass(frozen=True, slots=True)
class PickLeg:
    """The leg that picks, as the draft plans it: its amount after a split, the counter-account it holds."""

    id: int
    account_id: int
    amount: int
    currency: str
    booked_on: date
    counter_account_id: int | None  # one the leg had before (a pair's own is not: it goes with the pair)
    instructed_currency: str | None


def window_of(window_days: int | None, matching_window: int) -> int:
    """The window a pick is checked against: the ledger's, widened by the request up to the cap."""
    if window_days is None:
        return matching_window
    return max(matching_window, min(window_days, MAX_WINDOW))


def _sign(n: int) -> int:
    return (n > 0) - (n < 0)


def check_pick(
    leg: PickLeg,
    partner_id: int,
    stored: StoredUnit,
    own_unit: frozenset[int],
    accounts: Mapping[int, AccountFact],
    window: int,
) -> Problem | None:
    """None where `partner_id` is an offer of `leg`, else the problem: `partner_in_unit`, `second_transfer`
    (an untyped entry that is not its source's original cannot become a transfer, I31) or
    `partner_not_offered`."""
    detail = {"partner": partner_id}
    not_offered = Problem("partner_not_offered", leg.id, "pairing", detail)
    partner = stored.entry(partner_id)
    if partner is None:
        return not_offered
    if partner_id in own_unit:
        return Problem("partner_in_unit", leg.id, "pairing", detail)
    if partner.account_id == leg.account_id or _sign(partner.amount) == _sign(leg.amount):
        return not_offered
    if partner.type not in (None, "transfer"):
        return not_offered
    if leg.counter_account_id is not None:
        if partner.account_id != leg.counter_account_id:
            return not_offered
    else:
        account = accounts.get(partner.account_id)
        if account is None or not arrival_currency_ok(leg.instructed_currency, leg.currency, account):
            return not_offered
    if (
        partner.type == "transfer"
        and partner.counterpart_entry_id is None
        and partner.counter_account_id is not None
        and partner.counter_account_id != leg.account_id
    ):
        return not_offered  # an unpaired leg that already knows another counter-account is not this leg's
    if abs((partner.booked_on - leg.booked_on).days) > window:
        return not_offered
    if partner.type is None and partner_id != stored.original_of(partner.source_transaction_id):
        return Problem("second_transfer", partner_id, "type", {"source": partner.source_transaction_id})
    return None
