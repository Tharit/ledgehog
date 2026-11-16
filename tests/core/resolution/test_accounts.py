"""I11, the open-on-booking-date rule and own-account exclusion (spec §5.7, §3.3, §5.9)."""

from __future__ import annotations

from datetime import timedelta

from app.core.resolution import (
    counter_account_ok,
    currency_ok,
    open_on_booking_date,
    own_account_match_ok,
)
from tests.core.resolution.helpers import DAY, account, entry


def test_currency_ok_compares_the_entry_currency() -> None:
    assert currency_ok(entry(currency="EUR"), account(2, "EUR"))
    assert not currency_ok(entry(currency="EUR"), account(2, "USD"))


def test_instructed_currency_wins_over_the_entry_currency() -> None:
    e = entry(currency="EUR", instructed_currency="USD")
    assert currency_ok(e, account(2, "USD"))
    assert not currency_ok(e, account(2, "EUR"))


def test_open_on_the_booking_date_includes_the_closing_day() -> None:
    e = entry()
    assert open_on_booking_date(e, account(2, closed_on=None))
    assert open_on_booking_date(e, account(2, closed_on=DAY))
    assert not open_on_booking_date(e, account(2, closed_on=DAY - timedelta(days=1)))


def test_own_account_is_never_a_counter_account() -> None:
    assert not counter_account_ok(entry(account_id=1), account(1))
    assert not own_account_match_ok(entry(account_id=1), account(1))


def test_counter_account_ok_needs_all_three_tests() -> None:
    e = entry()
    assert counter_account_ok(e, account(2))
    assert not counter_account_ok(e, account(2, "USD"))
    assert not counter_account_ok(e, account(2, closed_on=DAY - timedelta(days=1)))


def test_pass_zero_test_ignores_closing() -> None:
    closed = account(2, closed_on=DAY - timedelta(days=30))
    assert own_account_match_ok(entry(), closed)
    assert not own_account_match_ok(entry(), account(2, "USD"))


def test_a_users_choice_may_also_be_the_legs_own_currency_where_there_is_an_instructed_one() -> None:
    from app.core.resolution.accounts import arrival_currency_ok, currency_choices

    eur, usd, gbp = account(2, "EUR"), account(3, "USD"), account(4, "GBP")
    assert not arrival_currency_ok("USD", "EUR", eur)  # a machine keeps to the default
    assert arrival_currency_ok("USD", "EUR", eur, users_choice=True)
    assert arrival_currency_ok("USD", "EUR", usd, users_choice=True)
    assert not arrival_currency_ok("USD", "EUR", gbp, users_choice=True)  # a third currency stays invalid
    assert not arrival_currency_ok(None, "EUR", usd, users_choice=True)  # no instructed amount: not here
    assert currency_choices("USD", "EUR", eur) == ["USD", "EUR"]
    assert currency_choices(None, "EUR", eur) == ["EUR"]


def test_a_clearance_account_takes_only_the_default_currency_whoever_chooses() -> None:
    from app.core.resolution.accounts import arrival_currency_ok, currency_choices

    clearance = account(2, "EUR", clearance=True)
    assert not arrival_currency_ok("USD", "EUR", clearance, users_choice=True)
    assert currency_choices("USD", "EUR", clearance) == ["USD"]
