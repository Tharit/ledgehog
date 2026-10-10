"""base_value() (schema.sql §10): the one conversion to the base currency, and its rate-age window."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import psycopg
import pytest
from sqlalchemy import Connection, text

from app.utils.config import Config
from app.utils.db import admin
from tests.invariants.helpers import make_balance_record, make_derived_entry, scalar


@pytest.fixture
def ledger(db_conn: Connection) -> Connection:
    db_conn.execute(text("INSERT INTO ledger_setting (base_currency) VALUES ('EUR')"))
    return db_conn


def _rate(conn: Connection, currency: str, on: date, per_base: str) -> None:
    conn.execute(
        text("INSERT INTO fx_rate (currency, rate_date, per_base) VALUES (:c, :d, CAST(:r AS numeric))"),
        {"c": currency, "d": on, "r": per_base},
    )


def _value(conn: Connection, amount: int, currency: str, on: date) -> int | None:
    return scalar(conn, "SELECT base_value(:a, :c, :d)", a=amount, c=currency, d=on)


# ---- the setting is required


def test_unset_max_rate_age_is_an_error_not_a_default(isolated_db: Config) -> None:
    """A connection that did not get the setting (not from the engine) must fail loudly."""
    with admin.connect(isolated_db) as raw:
        raw.execute("INSERT INTO ledger_setting (base_currency) VALUES ('EUR')")
        with pytest.raises(psycopg.errors.UndefinedObject, match="ledger.max_rate_age"):
            raw.execute("SELECT base_value(100, 'EUR', DATE '2026-01-01')")
        # even the base-currency shortcut needs it: the setting is read first
        with pytest.raises(psycopg.errors.UndefinedObject):
            raw.execute("SELECT base_value(100, 'USD', DATE '2026-01-01')")


def test_a_reset_setting_reads_as_empty_and_is_still_an_error(isolated_db: Config) -> None:
    """After SET then RESET a custom GUC reads as '' not 'unrecognised': still refused, differently."""
    with admin.connect(isolated_db) as raw:
        raw.execute("INSERT INTO ledger_setting (base_currency) VALUES ('EUR')")
        raw.execute("SET ledger.max_rate_age = '7 days'")
        raw.execute("RESET ledger.max_rate_age")
        with pytest.raises(psycopg.errors.InvalidDatetimeFormat):
            raw.execute("SELECT base_value(100, 'EUR', DATE '2026-01-01')")


def test_engine_connections_carry_the_setting(ledger: Connection) -> None:
    assert scalar(ledger, "SELECT current_setting('ledger.max_rate_age')::interval") is not None
    assert _value(ledger, 100, "EUR", date(2026, 1, 1)) == 100


# ---- conversion


def test_base_currency_amounts_are_returned_unchanged(ledger: Connection) -> None:
    assert _value(ledger, -12345, "EUR", date(2026, 3, 1)) == -12345


def test_no_rate_means_unvalued_never_zero(ledger: Connection) -> None:
    assert _value(ledger, 100, "USD", date(2026, 3, 1)) is None


def test_conversion_divides_by_units_per_base(ledger: Connection) -> None:
    _rate(ledger, "USD", date(2026, 3, 1), "2.0")
    assert _value(ledger, 200, "USD", date(2026, 3, 1)) == 100
    assert _value(ledger, -200, "USD", date(2026, 3, 1)) == -100


def test_the_latest_rate_on_or_before_the_date_is_used(ledger: Connection) -> None:
    _rate(ledger, "USD", date(2026, 3, 1), "2.0")
    _rate(ledger, "USD", date(2026, 3, 3), "4.0")
    _rate(ledger, "USD", date(2026, 3, 5), "10.0")
    assert _value(ledger, 400, "USD", date(2026, 3, 3)) == 100  # exact day
    assert _value(ledger, 400, "USD", date(2026, 3, 4)) == 100  # falls back to the 3rd
    assert _value(ledger, 400, "USD", date(2026, 3, 2)) == 200  # the 5th is in the future


@pytest.mark.parametrize(
    ("amount", "expected"),
    [(1, 0), (3, 2), (5, 2), (7, 4), (-1, 0), (-3, -2), (-5, -2), (-7, -4)],  # x / 2: half-even
)
def test_rounding_is_half_even(ledger: Connection, amount: int, expected: int) -> None:
    _rate(ledger, "USD", date(2026, 3, 1), "2.0")
    assert _value(ledger, amount, "USD", date(2026, 3, 1)) == expected


def test_minor_unit_exponents_are_respected(ledger: Connection) -> None:
    _rate(ledger, "JPY", date(2026, 3, 1), "160.0")  # 160 yen per euro; yen has no minor unit
    assert _value(ledger, 1600, "JPY", date(2026, 3, 1)) == 1000  # 1600 yen = 10.00 EUR


# ---- the rate-age window


def test_date_minus_interval_is_a_timestamp_and_the_boundary_day_is_inclusive(ledger: Connection) -> None:
    """`p_on - interval '7 days'` is a TIMESTAMP at midnight; `rate_date >= that` casts the date up.
    So a rate exactly max_rate_age days old is still usable; one day older is not."""
    assert (
        scalar(ledger, "SELECT pg_typeof(DATE '2026-03-08' - interval '7 days')::text")
        == "timestamp without time zone"
    )
    on = date(2026, 3, 8)
    _rate(ledger, "USD", date(2026, 3, 1), "2.0")  # exactly 7 days before
    assert _value(ledger, 200, "USD", on) == 100
    assert _value(ledger, 200, "USD", date(2026, 3, 9)) is None  # 8 days: stale


def test_a_stale_rate_is_ignored_even_though_it_is_the_latest(ledger: Connection) -> None:
    _rate(ledger, "USD", date(2026, 2, 1), "2.0")
    assert _value(ledger, 200, "USD", date(2026, 3, 1)) is None


def test_the_window_follows_the_setting(ledger: Connection) -> None:
    _rate(ledger, "USD", date(2026, 3, 1), "2.0")
    ledger.execute(text("SET LOCAL ledger.max_rate_age = '3 days'"))
    assert _value(ledger, 200, "USD", date(2026, 3, 4)) == 100
    assert _value(ledger, 200, "USD", date(2026, 3, 5)) is None
    ledger.execute(text("SET LOCAL ledger.max_rate_age = '10 days'"))
    assert _value(ledger, 200, "USD", date(2026, 3, 11)) == 100


def test_a_fractional_day_interval_keeps_the_boundary_inside_the_day(ledger: Connection) -> None:
    """With '36 hours' the cut-off is noon the day before yesterday: a rate dated the day before
    yesterday (midnight) is older than the cut-off and excluded, yesterday's is kept. Months work the
    same way (calendar arithmetic on the timestamp), not as 30 days."""
    _rate(ledger, "USD", date(2026, 3, 6), "2.0")
    ledger.execute(text("SET LOCAL ledger.max_rate_age = '36 hours'"))
    assert _value(ledger, 200, "USD", date(2026, 3, 7)) == 100  # 1 day old
    assert _value(ledger, 200, "USD", date(2026, 3, 8)) is None  # 2 days old: midnight < cut-off noon
    ledger.execute(text("SET LOCAL ledger.max_rate_age = '1 month'"))
    assert _value(ledger, 200, "USD", date(2026, 4, 6)) == 100  # exactly one calendar month
    assert _value(ledger, 200, "USD", date(2026, 4, 7)) is None


def test_net_worth_counts_unvalued_accounts_instead_of_zeroing_them(
    ledger: Connection, make_account: Callable[..., int]
) -> None:
    usd = make_account(ledger, name="USD", currency="USD")
    rec = make_balance_record(ledger, usd, balance_on=date(2026, 1, 1), currency="USD")
    make_derived_entry(
        ledger, usd, rec, type="opening", booked_on=date(2026, 1, 1), amount=500, currency="USD"
    )
    row = ledger.execute(text("SELECT * FROM net_worth_on(DATE '2026-03-01')")).one()
    assert (row.net_worth, row.unvalued_accounts) == (0, 1)
    _rate(ledger, "USD", date(2026, 3, 1), "2.0")
    row = ledger.execute(text("SELECT * FROM net_worth_on(DATE '2026-03-01')")).one()
    assert (row.net_worth, row.unvalued_accounts) == (250, 0)
