from __future__ import annotations

from datetime import date

import pytest

from app.plugins.importers.csv.amounts import parse_amount
from app.plugins.importers.csv.dates import parse_date, validate_format


@pytest.mark.parametrize(
    ("fmt", "text", "expected"),
    [
        ("dd.MM.yyyy", "03.08.2026", date(2026, 8, 3)),
        ("dd.MM.yyyy", "3.8.2026", date(2026, 8, 3)),  # unpadded parses under either
        ("d.M.yyyy", "03.08.2026", date(2026, 8, 3)),
        ("d.M.yyyy", "3.8.2026", date(2026, 8, 3)),
        ("dd/MM/yyyy", " 31/12/2026 ", date(2026, 12, 31)),
        ("dd.MM.yyyy, HH:mm:ss", "10.10.2026, 13:05:59", date(2026, 10, 10)),
        ("dd.MM.yyyy HH:mm:ss", "10.10.2026 13:05:59", date(2026, 10, 10)),
    ],
)
def test_parse_date(fmt: str, text: str, expected: date) -> None:
    assert parse_date(text, fmt) == expected


@pytest.mark.parametrize(
    ("fmt", "text"),
    [
        ("dd.MM.yyyy", "03.08.26"),  # two-digit years are not accepted
        ("dd.MM.yyyy", "31.02.2026"),  # not a date
        ("dd.MM.yyyy", "vorgemerkt"),
        ("dd.MM.yyyy", ""),
        ("dd.MM.yyyy", "03.08.2026 extra"),
        ("dd.MM.yyyy", "03-08-2026"),
    ],
)
def test_parse_date_rejects(fmt: str, text: str) -> None:
    assert parse_date(text, fmt) is None


@pytest.mark.parametrize("fmt", ["dd.MM.yy", "dd.MM", "MM.yyyy", "dd.dd.yyyy", "", "yyyy-MM-dd-MM"])
def test_validate_format_rejects(fmt: str) -> None:
    with pytest.raises(ValueError):
        validate_format(fmt)


def test_validate_format_accepts_iso_like() -> None:
    validate_format("yyyy-MM-dd")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.234,56", 123456),
        ("-1.234,56", -123456),
        ("-12,5", -1250),  # fewer decimals accepted
        ("12", 1200),
        ("+0,99", 99),
        ("0,00", 0),
        ("-0,00", 0),
        ("1.234.567,89", 123456789),
        (" 7,10 ", 710),
    ],
)
def test_parse_amount_de(text: str, expected: int) -> None:
    assert parse_amount(text, currency="EUR", minor_units=2, decimal_sep=",", thousands_sep=".") == expected


@pytest.mark.parametrize("text", ["1,234", "abc", "1,2,3", "", "--1", "1,00 EUR"])
def test_parse_amount_rejects(text: str) -> None:
    with pytest.raises(ValueError):
        parse_amount(text, currency="EUR", minor_units=2, decimal_sep=",", thousands_sep=".")


def test_parse_amount_dot_decimal_comma_thousands() -> None:
    assert (
        parse_amount("1,234.50", currency="USD", minor_units=2, decimal_sep=".", thousands_sep=",") == 123450
    )


def test_parse_amount_zero_minor_units() -> None:
    assert parse_amount("1.500", currency="JPY", minor_units=0, decimal_sep=",", thousands_sep=".") == 1500
    with pytest.raises(ValueError):
        parse_amount("1,5", currency="JPY", minor_units=0, decimal_sep=",", thousands_sep=".")
