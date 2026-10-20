"""The card answer to records, coverage and balance (fints.md §6a). Invented entries, as the plugin's seam
hands them over: named fields as the bank sent them, the card number not among them."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.plugins.errors import ParseFailed
from app.plugins.importers.fints.bank import CardAnswer, CardBalance
from app.plugins.importers.fints.cards import CardRead, read_card

UNTIL = date(2026, 10, 31)  # the day before today


def entry(booked: str, amount: str, direction: str = "D", **more: str) -> dict[str, str]:
    return {
        "booking_date": booked,
        "amount": amount,
        "currency": "EUR",
        "direction": direction,
        "merchant_name": "SHOP",
        "billed": "J",
        **more,
    }


def unbilled(booked: str, amount: str, direction: str = "D") -> dict[str, str]:
    return entry(booked, amount, direction, billed="N")


def read(*entries: dict[str, str], balance: CardBalance | None = None) -> CardRead:
    return read_card(CardAnswer(balance, tuple(entries)), until=UNTIL, minor_units_of=lambda c: 2)


# ---- the rows -----------------------------------------------------------------------------------------


def test_a_billed_entry_is_a_row_in_ledger_sign_with_its_dates_merchant_and_joined_lines() -> None:
    (row,) = read(
        entry(
            "20261012",
            "12,50",
            value_date="20261014",
            description_1="Zeile 1",
            description_2="  Zeile   2 ",
            statement_date="20261015",
        )
    ).rows
    assert (row.amount_minor, row.currency) == (-1250, "EUR")
    assert (row.booked_on, row.value_on) == (date(2026, 10, 12), date(2026, 10, 14))
    assert (row.counterparty_name, row.purpose) == ("SHOP", "Zeile 1 Zeile 2")
    assert (row.source_id, row.source_format) == (None, "hkkku")
    assert (row.instructed_amount_minor, row.instructed_currency) == (None, None)
    assert row.raw["statement_date"] == "20261015" and row.raw["description_2"] == "  Zeile   2 "


def test_a_credit_is_positive_and_an_entry_without_a_value_date_or_lines_has_none() -> None:
    (row,) = read(entry("20261014", "9,20", "C")).rows
    assert row.amount_minor == 920 and row.value_on is None and row.purpose is None


def test_a_foreign_original_amount_is_the_instructed_amount_in_its_own_sign() -> None:
    (row,) = read(
        entry(
            "20261014", "9,20", "C", original_amount="10,00", original_currency="USD", original_direction="C"
        )
    ).rows
    assert (row.amount_minor, row.currency) == (920, "EUR")
    assert (row.instructed_amount_minor, row.instructed_currency) == (1000, "USD")


def test_an_original_amount_in_the_booked_currency_is_not_instructed() -> None:
    (row,) = read(entry("20261014", "9,20", original_amount="9,20", original_currency="EUR")).rows
    assert (row.instructed_amount_minor, row.instructed_currency) == (None, None)


def test_a_zero_booking_is_dropped_and_counted() -> None:
    result = read(entry("20261014", "0,00"), entry("20261015", "1,00"))
    assert len(result.rows) == 1 and result.filtered == 1


# ---- the unbilled entries and the coverage ------------------------------------------------------------


def test_unbilled_entries_are_not_imported() -> None:
    result = read(entry("20261010", "5,00"), unbilled("20261028", "12,50"))
    assert [r.amount_minor for r in result.rows] == [-500]


def test_without_unbilled_entries_the_coverage_is_the_day_before_today() -> None:
    assert read(entry("20261010", "5,00")).covered_through == UNTIL
    assert read().covered_through == UNTIL


def test_the_coverage_is_held_the_day_before_the_earliest_unbilled_booking() -> None:
    result = read(unbilled("20261030", "1,00"), unbilled("20261028", "2,00"), entry("20261010", "5,00"))
    assert result.covered_through == date(2026, 10, 27)


def test_an_unbilled_entry_booked_today_or_after_leaves_the_coverage_at_the_closed_day() -> None:
    assert read(unbilled("20261101", "1,00")).covered_through == UNTIL


# ---- the balance --------------------------------------------------------------------------------------


def test_the_balance_is_the_current_one_minus_the_unbilled_entries_rolled_back_to_the_coverage() -> None:
    """Debt of 500,00 on the 30th, which includes the unbilled 12,50 (the 28th) and 7,50 (the 30th): the
    booked balance on the 30th is -480,00. The coverage is held at the 27th, so the billed 15,00 of the 29th
    is taken off the figure: -465,00 on the 27th."""
    result = read(
        entry("20261020", "40,00"),
        entry("20261029", "15,00"),
        unbilled("20261028", "12,50"),
        unbilled("20261030", "7,50"),
        balance=CardBalance("D", "500,00", "EUR", "20261030"),
    )
    assert result.covered_through == date(2026, 10, 27)
    assert (result.balance_minor, result.balance_on) == (-46500, date(2026, 10, 27))


def test_a_balance_without_unbilled_entries_is_dated_at_its_own_date_when_that_is_closed() -> None:
    result = read(entry("20261020", "40,00"), balance=CardBalance("D", "500,00", "EUR", "20261029"))
    assert (result.balance_minor, result.balance_on) == (-50000, date(2026, 10, 29))


def test_a_balance_dated_after_the_last_closed_day_loses_the_billed_entries_after_it() -> None:
    result = read(
        entry("20261030", "5,00"),
        entry("20261101", "8,00"),
        balance=CardBalance("D", "100,00", "EUR", "20261101"),
    )
    # dated the 31st: the entry of the 1st (-8,00) comes off, so -92,00
    assert (result.balance_minor, result.balance_on) == (-9200, UNTIL)


def test_a_credit_balance_is_positive() -> None:
    result = read(balance=CardBalance("C", "25,00", "EUR", "20261029"))
    assert (result.balance_minor, result.balance_on) == (2500, date(2026, 10, 29))


def test_no_balance_in_the_answer_means_none() -> None:
    assert (read(entry("20261010", "5,00")).balance_minor, read().balance_on) == (None, None)


# ---- what is refused ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        {"booking_date": ""},
        {"booking_date": "2026-10-12"},
        {"booking_date": "20261342"},
        {"amount": "12,505"},
        {"amount": "twelve"},
        {"amount": "-12,50"},
        {"direction": "X"},
        {"currency": ""},
    ],
)
def test_an_entry_that_cannot_be_read_fails_the_run_naming_no_value(bad: dict[str, str]) -> None:
    broken = {**entry("20261012", "12,50"), **bad}
    broken = {k: v for k, v in broken.items() if v != ""}
    with pytest.raises(ParseFailed) as err:
        read(broken)
    assert "12,505" not in str(err.value) and "twelve" not in str(err.value)


def test_pending_entries_in_another_currency_than_the_balance_fail_the_run() -> None:
    other = {**unbilled("20261028", "1,00"), "currency": "USD"}
    with pytest.raises(ParseFailed):
        read(other, balance=CardBalance("D", "5,00", "EUR", "20261030"))
