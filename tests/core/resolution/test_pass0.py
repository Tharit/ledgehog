"""Pass 0, own account (spec §5.9)."""

from __future__ import annotations

from datetime import timedelta

from app.core.resolution import Decided, own_account_index, pass0
from tests.core.resolution.helpers import DAY, account, entry

SAVINGS = account(2, ref="de89370400440532013000")


def test_matches_a_household_account_by_canonical_ref() -> None:
    index = own_account_index([account(1), SAVINGS])
    got = pass0(entry(counterparty_ref="DE89 3704 0044 0532 0130 00"), index)
    basis = {"account_id": 2}
    assert got == (Decided("transfer", "own_account", basis), Decided(2, "own_account", basis))


def test_the_entrys_own_account_is_excluded() -> None:
    index = own_account_index([SAVINGS])
    assert pass0(entry(account_id=2, counterparty_ref="DE89370400440532013000"), index) is None


def test_a_currency_mismatch_is_refused() -> None:
    index = own_account_index([SAVINGS])
    e = entry(counterparty_ref="DE89370400440532013000", instructed_currency="USD")
    assert pass0(e, index) is None


def test_a_closed_account_still_matches() -> None:
    closed = account(2, ref="de89370400440532013000", closed_on=DAY - timedelta(days=90))
    index = own_account_index([closed])
    assert pass0(entry(counterparty_ref="DE89370400440532013000"), index) is not None


def test_no_ref_or_unknown_ref_does_not_apply() -> None:
    index = own_account_index([SAVINGS, account(3)])
    assert pass0(entry(), index) is None
    assert pass0(entry(counterparty_ref=""), index) is None
    assert pass0(entry(counterparty_ref="FR7630006000011234567890189"), index) is None


def test_accounts_without_a_ref_are_not_indexed() -> None:
    assert dict(own_account_index([account(1), account(2, ref="")])) == {}
