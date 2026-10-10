from decimal import Decimal

import pytest

from app.core.domain.money import CurrencyMismatch, Money


def test_holds_signed_integer_minor_units_and_currency():
    m = Money(-1234, "EUR")
    assert m.minor == -1234
    assert m.currency == "EUR"


@pytest.mark.parametrize("bad", [1.5, Decimal("1"), "12", None, True])
def test_rejects_non_integer_minor(bad):
    with pytest.raises(TypeError):
        Money(bad, "EUR")


@pytest.mark.parametrize("bad", ["eur", "EU", "EURO", "", "E1R"])
def test_rejects_malformed_currency(bad):
    with pytest.raises(ValueError):
        Money(1, bad)


def test_is_immutable_and_hashable():
    m = Money(1, "EUR")
    with pytest.raises(AttributeError):
        m.minor = 2  # type: ignore[misc]
    assert {m, Money(1, "EUR")} == {m}


def test_addition_and_subtraction_same_currency():
    assert Money(100, "EUR") + Money(250, "EUR") == Money(350, "EUR")
    assert Money(100, "EUR") - Money(250, "EUR") == Money(-150, "EUR")
    assert -Money(5, "EUR") == Money(-5, "EUR")


def test_cross_currency_arithmetic_raises():
    with pytest.raises(CurrencyMismatch):
        Money(1, "EUR") + Money(1, "USD")
    with pytest.raises(CurrencyMismatch):
        Money(1, "EUR") - Money(1, "USD")


def test_cross_currency_comparison_raises_but_equality_is_false():
    with pytest.raises(CurrencyMismatch):
        Money(1, "EUR") < Money(2, "USD")
    assert Money(1, "EUR") != Money(1, "USD")


def test_ordering_same_currency():
    assert Money(1, "EUR") < Money(2, "EUR")
    assert sorted([Money(3, "EUR"), Money(-1, "EUR")])[0] == Money(-1, "EUR")


def test_multiplication_by_integer_only():
    assert Money(7, "EUR") * 3 == Money(21, "EUR")
    with pytest.raises(TypeError):
        Money(7, "EUR") * 1.5  # type: ignore[operator]


@pytest.mark.parametrize(
    ("text", "exp", "minor"),
    [
        ("12.34", 2, 1234),
        ("-12.34", 2, -1234),
        ("12", 2, 1200),
        ("12.3", 2, 1230),
        ("0.05", 2, 5),
        ("500", 0, 500),
        ("1.234", 3, 1234),
        ("+7.50", 2, 750),
    ],
)
def test_parse_decimal_text_uses_currency_exponent(text, exp, minor):
    assert Money.parse(text, "XXX", minor_units=exp) == Money(minor, "XXX")


@pytest.mark.parametrize(("text", "exp"), [("1.234", 2), ("1.5", 0), ("abc", 2), ("", 2), ("1,5", 2)])
def test_parse_rejects_text_with_excess_or_bad_precision(text, exp):
    with pytest.raises(ValueError):
        Money.parse(text, "EUR", minor_units=exp)


@pytest.mark.parametrize(
    ("minor", "exp", "text"),
    [(1234, 2, "12.34"), (-1234, 2, "-12.34"), (5, 2, "0.05"), (-5, 2, "-0.05"),
     (500, 0, "500"), (-1, 3, "-0.001"), (0, 2, "0.00")],
)
def test_format_round_trips_with_parse(minor, exp, text):
    m = Money(minor, "EUR")
    assert m.format(minor_units=exp) == text
    assert Money.parse(text, "EUR", minor_units=exp) == m
