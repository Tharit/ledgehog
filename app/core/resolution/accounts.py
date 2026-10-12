"""Which accounts may be an entry's counter-account (spec §5.7 I11, §3.3, §5.9).

One home for the tests every machine proposal of a counter-account passes: the currency rule
(I11), the account not being the entry's own, and, for passes 1 and 2, being open on the booking
date. Pass 0 skips the last: a closed account's payout is still a transfer from it.
"""

from __future__ import annotations

from app.core.plugins.classifier import AccountFact, EntryInput


def currency_ok(entry: EntryInput, account: AccountFact) -> bool:
    """I11: the account is in the currency the money arrived in.

    That is the instructed currency where the source has one (a card payment abroad), else the
    entry's own.
    """
    return (entry.instructed_currency or entry.currency) == account.currency


def open_on_booking_date(entry: EntryInput, account: AccountFact) -> bool:
    return account.closed_on is None or entry.booked_on <= account.closed_on


def own_account_match_ok(entry: EntryInput, account: AccountFact) -> bool:
    """Pass 0's test: not the entry's own account, and the currency rule; closing is not tested."""
    return account.id != entry.account_id and currency_ok(entry, account)


def counter_account_ok(entry: EntryInput, account: AccountFact) -> bool:
    """A rule's or history's counter-account candidate: pass 0's test and open on the booking date."""
    return own_account_match_ok(entry, account) and open_on_booking_date(entry, account)
