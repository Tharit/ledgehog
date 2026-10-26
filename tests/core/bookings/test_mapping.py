"""Where a document is booked, and why it is not (features/documents.md §1): pure."""

from __future__ import annotations

from datetime import date

from app.core.bookings.documents import (
    ClearanceAccount,
    DocumentFacts,
    NotBooked,
    account_for,
    not_booked,
    provider_index,
)

START = date(2026, 1, 31)


def doc(**kw: object) -> DocumentFacts:
    base: dict[str, object] = {
        "id": 1,
        "provider": "Amazon",
        "external_id": "A1",
        "occurred_on": date(2026, 2, 1),
        "total": -1000,
        "currency": "EUR",
    }
    base.update(kw)
    return DocumentFacts(**base)  # type: ignore[arg-type]


EUR = ClearanceAccount(10, "EUR", ("Amazon", "Amazon EU"), START)
USD = ClearanceAccount(11, "USD", ("amazon",), START)
INDEX = provider_index([EUR, USD])


def test_the_provider_is_compared_without_regard_to_case_and_the_currency_decides() -> None:
    assert account_for("AMAZON", "EUR", INDEX) == EUR
    assert account_for("amazon eu", "EUR", INDEX) == EUR
    assert account_for("Amazon", "USD", INDEX) == USD
    assert account_for("Amazon", "GBP", INDEX) is None
    assert account_for("Ebay", "EUR", INDEX) is None


def test_a_document_after_the_start_is_booked() -> None:
    assert not_booked(doc(), INDEX) is None
    assert not_booked(doc(provider="AMAZON eu"), INDEX) is None


def test_the_start_is_strict() -> None:
    assert not_booked(doc(occurred_on=date(2026, 2, 1)), INDEX) is None
    assert not_booked(doc(occurred_on=START), INDEX) == NotBooked("before_start", account_id=10, start=START)
    assert not_booked(doc(occurred_on=date(2025, 12, 1)), INDEX) == NotBooked(
        "before_start", account_id=10, start=START
    )


def test_a_total_of_zero_is_not_booked_whatever_else_is_true() -> None:
    assert not_booked(doc(total=0), INDEX) == NotBooked("zero_total")
    assert not_booked(doc(total=0, provider="Ebay"), INDEX) == NotBooked("zero_total")


def test_no_account_names_the_currency() -> None:
    assert not_booked(doc(provider="Ebay"), INDEX) == NotBooked("no_account", currency="EUR")
    assert not_booked(doc(currency="GBP"), INDEX) == NotBooked("no_account", currency="GBP")


def test_an_account_without_a_start_names_itself() -> None:
    index = provider_index([ClearanceAccount(12, "EUR", ("Amazon",), None)])
    assert not_booked(doc(), index) == NotBooked("no_start", account_id=12)


def test_the_reasons_apply_in_order() -> None:
    # no account beats a date before any start; no start beats nothing else but zero and no account
    assert not_booked(doc(provider="Ebay", occurred_on=date(2000, 1, 1)), INDEX) == NotBooked(
        "no_account", currency="EUR"
    )
    index = provider_index([ClearanceAccount(12, "EUR", ("Amazon",), None)])
    assert not_booked(doc(occurred_on=date(2000, 1, 1)), index) == NotBooked("no_start", account_id=12)
