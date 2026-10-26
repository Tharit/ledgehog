"""`LedgerFilter` validates its own invariants, purely (no database)."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.ledger import InvalidFilter, LedgerFilter


def bad(**kw: object) -> InvalidFilter:
    with pytest.raises(InvalidFilter) as caught:
        LedgerFilter(**kw)  # type: ignore[arg-type]
    return caught.value


def test_empty_filter_is_valid_and_says_so():
    flt = LedgerFilter()
    assert flt.is_empty
    assert not LedgerFilter(account_ids=(1,)).is_empty
    assert not LedgerFilter(uncategorised=True).is_empty
    assert not LedgerFilter(category_descendants=False, text="x").is_empty


@pytest.mark.parametrize("bound", ["amount_min", "amount_max"])
def test_an_amount_bound_requires_a_currency(bound: str):
    err = bad(**{bound: 100})
    assert err.parameter == "currency"
    assert "currency" in str(err)
    LedgerFilter(**{bound: 100}, currency="EUR")  # type: ignore[arg-type]


def test_zero_is_a_bound_that_still_needs_a_currency():
    assert bad(amount_min=0).parameter == "currency"


@pytest.mark.parametrize("bound", ["amount_min", "amount_max"])
def test_amount_bounds_are_not_negative(bound: str):
    assert bad(**{bound: -1}, currency="EUR").parameter == bound


def test_amount_range_must_not_be_inverted():
    assert bad(amount_min=10, amount_max=5, currency="EUR").parameter == "amount_min"
    LedgerFilter(amount_min=5, amount_max=5, currency="EUR")


def test_date_range_must_not_be_inverted():
    assert bad(date_from=date(2026, 2, 1), date_to=date(2026, 1, 1)).parameter == "to"
    LedgerFilter(date_from=date(2026, 1, 1), date_to=date(2026, 1, 1))


def test_currency_is_three_capitals():
    for value in ("eur", "EU", "EURO", ""):
        assert bad(currency=value).parameter == "currency"


def test_direction_is_in_or_out():
    assert bad(direction="sideways").parameter == "direction"
    LedgerFilter(direction="in")
    LedgerFilter(direction="out")


def test_type_and_flag_values_are_closed_sets():
    assert bad(types=("flow", "bogus")).parameter == "type"
    assert bad(flags=("bogus",)).parameter == "flag"
    LedgerFilter(
        types=("flow", "transfer", "opening", "valuation", "reconciliation"),
        flags=("unconfirmed", "unclassified", "waiting", "unmatched_transfer"),
    )


def test_text_is_trimmed_non_empty_and_bounded_and_never_echoed():
    assert bad(text="   ").parameter == "q"
    secret = "s" * 201
    err = bad(text=secret)
    assert err.parameter == "q"
    assert secret not in str(err)
    LedgerFilter(text="x" * 200)


def test_ids_are_positive_and_bounded():
    for field in ("account_ids", "category_ids", "payee_ids", "tag_ids"):
        assert (
            bad(**{field: (0,)}).parameter
            == {
                "account_ids": "account_id",
                "category_ids": "category_id",
                "payee_ids": "payee_id",
                "tag_ids": "tag_id",
            }[field]
        )
        bad(**{field: (2**63,)})
