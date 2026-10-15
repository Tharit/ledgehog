"""Offers (spec §5.7 "Offers"), pure: the partners a transfer leg may be given, computed when read.

For a transfer leg L with the counter-account C (whatever it holds under any key), the offers are movements
on C within a window, of the opposite sign and of ANY amount; where L has no counter-account, on every
account the currency rule allows. Three groups, in this order:

1. **open offers** — unpaired transfer legs (`open_leg`) and untyped entries (`untyped_entry`; only a source's
   original can become a transfer, I31, so no other is offered). An unpaired leg whose own known
   counter-account is another account is not offered at all. Exact amounts first, then by distance in
   days, then the earlier `booked_on`, then the lower entry id;
2. **legs paired elsewhere** (`paired_elsewhere`), with their partner's summary, in the same order;
3. **the counter-leg** (`counter_leg`) for a leg without a partner whose C is unsynced and open on the date:
   what a commit would create on C. Its amount is the negated amount of L in one currency; across currencies
   the negated instructed amount where L has one in C's currency, else `needs_received_amount` (no estimate:
   conversion happens only in reporting, I27).

The **proposal** (a preselection in the preview, never stored): the first open offer when it is exact; else,
where there is no open offer at all, the counter-leg when offered; else nothing. A leg paired elsewhere is
never proposed, nor is anything proposed for a leg that already has a partner.

Each offer carries the **effect** of picking it: an untyped entry becomes a transfer; a same-currency open
offer of another amount splits the difference off the LARGER leg; a pick breaks the pairs it replaces.
`has_more`: candidates exist beyond `window`, up to the cap the pool was loaded for.

No database here: the pool is data (`PoolEntry`), loaded by the caller.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date
from typing import Literal

from app.core.matching.candidates import amounts_match
from app.core.matching.leg import Leg
from app.core.plugins.classifier import AccountFact
from app.core.resolution.accounts import arrival_currency_ok

MAX_WINDOW = 90  # the widest window a pick may ask for (spec §5.7), and what the pool is loaded for

OfferKind = Literal["open_leg", "untyped_entry", "paired_elsewhere", "counter_leg"]


@dataclass(frozen=True, slots=True)
class Summary:
    """A leg in a few words: what a partner summary shows."""

    entry_id: int
    account_id: int
    booked_on: date
    amount: int
    currency: str
    description: str | None = None


@dataclass(frozen=True, slots=True)
class PoolEntry:
    """A movement an offer may be made of. `leg.type` is `transfer` or None (an untyped entry);
    `partner` is set for a leg that is paired; `original` is the residual of its source (I31)."""

    leg: Leg
    original: bool = True
    description: str | None = None
    partner: Summary | None = None


@dataclass(frozen=True, slots=True)
class OfferWorld:
    """What offers read of the accounts: their facts, and whether each is synced (`v_account_synced`)."""

    accounts: Mapping[int, AccountFact]
    synced: Mapping[int, bool]


@dataclass(frozen=True, slots=True)
class OfferFee:
    larger_entry_id: int
    difference: int  # positive minor units, in the currency of both legs
    currency: str


@dataclass(frozen=True, slots=True)
class OfferEffect:
    types_as_transfer: bool = False
    fee: OfferFee | None = None
    breaks_pair_with: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class CounterLegOffer:
    booked_on: date
    purpose: str | None
    amount: int | None  # None: the user types the amount received (`needs_received_amount`)
    currency: str
    needs_received_amount: bool


@dataclass(frozen=True, slots=True)
class Offer:
    kind: OfferKind
    entry_id: int | None  # None for the counter-leg: it does not exist yet
    account_id: int
    booked_on: date
    amount: int | None  # None only for a counter-leg that needs the amount received
    currency: str
    description: str | None
    exact: bool
    proposed: bool
    paired_with: Summary | None
    effect: OfferEffect
    counter_leg: CounterLegOffer | None = None


@dataclass(frozen=True, slots=True)
class Proposal:
    kind: Literal["entry", "counter_leg"]
    entry_id: int | None


@dataclass(frozen=True, slots=True)
class OfferSet:
    offers: tuple[Offer, ...]
    proposal: Proposal | None
    has_more: bool


def _sign(n: int) -> int:
    return (n > 0) - (n < 0)


def _order(leg: Leg, exact: bool, other: Leg) -> tuple[bool, int, date, int]:
    return (not exact, abs((other.booked_on - leg.booked_on).days), other.booked_on, other.entry_id)


def _reachable(leg: Leg, p: PoolEntry, partner_id: int | None, world: OfferWorld) -> bool:
    """Whether `p` is on an account `leg` may pair with, with the opposite sign, and not `leg`'s partner."""
    other = p.leg
    if other.entry_id in (leg.entry_id, partner_id) or other.account_id == leg.account_id:
        return False
    if leg.amount == 0 or other.amount == 0 or _sign(leg.amount) == _sign(other.amount):
        return False
    if leg.counter_account_id is not None:
        return other.account_id == leg.counter_account_id
    account = world.accounts.get(other.account_id)
    return account is not None and arrival_currency_ok(leg.instructed_currency, leg.currency, account)


def _kind(leg: Leg, p: PoolEntry) -> OfferKind | None:
    other = p.leg
    if other.type is None:
        return "untyped_entry" if p.original and p.partner is None else None
    if other.type != "transfer":
        return None
    if p.partner is not None:
        return "paired_elsewhere"
    # an unpaired leg that already knows another counter-account is not this leg's to take
    if other.counter_account_id is not None and other.counter_account_id != leg.account_id:
        return None
    return "open_leg"


def _effect(leg: Leg, p: PoolEntry, kind: OfferKind, exact: bool, partner_id: int | None) -> OfferEffect:
    other = p.leg
    fee = None
    if kind in ("open_leg", "untyped_entry") and not exact and other.currency == leg.currency:
        larger = leg if abs(leg.amount) > abs(other.amount) else other
        fee = OfferFee(larger.entry_id, abs(abs(leg.amount) - abs(other.amount)), leg.currency)
    broken = {partner_id} if partner_id is not None else set()
    if p.partner is not None:
        broken.add(p.partner.entry_id)
    return OfferEffect(
        types_as_transfer=kind == "untyped_entry",
        fee=fee,
        breaks_pair_with=tuple(sorted(broken)),
    )


def _counter_leg(leg: Leg, partner_id: int | None, world: OfferWorld, purpose: str | None) -> Offer | None:
    """The counter-leg a commit would create: for a leg without a partner whose C is unsynced and open."""
    c = leg.counter_account_id
    if partner_id is not None or c is None or c == leg.account_id:
        return None
    account = world.accounts.get(c)
    if account is None or world.synced.get(c, True):
        return None
    if account.closed_on is not None and leg.booked_on > account.closed_on:
        return None
    if leg.instructed_currency is not None and account.currency != leg.instructed_currency:
        return None  # I11: the money arrived in another currency
    amount: int | None = None
    if account.currency == leg.currency:
        amount = -leg.amount
    elif leg.instructed_currency == account.currency and leg.instructed_amount is not None:
        amount = -leg.instructed_amount
    shown_purpose = purpose if purpose is not None else leg.purpose
    return Offer(
        kind="counter_leg",
        entry_id=None,
        account_id=c,
        booked_on=leg.booked_on,
        amount=amount,
        currency=account.currency,
        description=shown_purpose,
        exact=False,
        proposed=False,
        paired_with=None,
        effect=OfferEffect(),
        counter_leg=CounterLegOffer(
            booked_on=leg.booked_on,
            purpose=shown_purpose,
            amount=amount,
            currency=account.currency,
            needs_received_amount=amount is None,
        ),
    )


def offers(
    leg: Leg,
    pool: Iterable[PoolEntry],
    world: OfferWorld,
    window: int,
    *,
    partner_id: int | None = None,
    purpose: str | None = None,
    cap: int = MAX_WINDOW,
) -> OfferSet:
    """The offers of `leg` (module docstring). `partner_id` is its current partner, if paired, which is
    never offered; `purpose` is its purpose as shown (the counter-leg carries it), default the canonical
    one."""
    groups: dict[OfferKind, list[tuple[tuple[bool, int, date, int], Offer]]] = {
        "open_leg": [],
        "untyped_entry": [],
        "paired_elsewhere": [],
    }
    has_more = False
    for p in pool:
        if not _reachable(leg, p, partner_id, world):
            continue
        kind = _kind(leg, p)
        if kind is None:
            continue
        distance = abs((p.leg.booked_on - leg.booked_on).days)
        if distance > window:
            has_more = has_more or distance <= cap
            continue
        exact = amounts_match(leg, p.leg)
        offer = Offer(
            kind=kind,
            entry_id=p.leg.entry_id,
            account_id=p.leg.account_id,
            booked_on=p.leg.booked_on,
            amount=p.leg.amount,
            currency=p.leg.currency,
            description=p.description,
            exact=exact,
            proposed=False,
            paired_with=p.partner,
            effect=_effect(leg, p, kind, exact, partner_id),
        )
        groups[kind].append((_order(leg, exact, p.leg), offer))
    # open legs and untyped entries are one group: exact first, then by date
    open_offers = [o for _k, o in sorted(groups["open_leg"] + groups["untyped_entry"], key=lambda t: t[0])]
    elsewhere = [o for _k, o in sorted(groups["paired_elsewhere"], key=lambda t: t[0])]
    counter = _counter_leg(leg, partner_id, world, purpose)

    proposal: Proposal | None = None
    if partner_id is None:
        if open_offers and open_offers[0].exact:
            open_offers[0] = replace(open_offers[0], proposed=True)
            proposal = Proposal("entry", open_offers[0].entry_id)
        elif not open_offers and counter is not None:
            counter = replace(counter, proposed=True)
            proposal = Proposal("counter_leg", None)
    return OfferSet(
        offers=(*open_offers, *elsewhere, *((counter,) if counter is not None else ())),
        proposal=proposal,
        has_more=has_more,
    )
