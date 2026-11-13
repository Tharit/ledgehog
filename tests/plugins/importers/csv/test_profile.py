from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from app.core.plugins.errors import InvalidProfile
from app.plugins.importers.csv.profile import Profile


def minimal() -> dict[str, Any]:
    return {
        "header_marker": ["Datum", "Betrag"],
        "booked_on": "Datum",
        "date_format": "dd.MM.yyyy",
        "amount": {"column": "Betrag"},
    }


def full() -> dict[str, Any]:
    p = minimal()
    p.update(
        {
            "encoding": "cp1252",
            "delimiter": ";",
            "quote": '"',
            "value_on": "Valuta",
            "decimal_sep": ",",
            "thousands_sep": ".",
            "invert_amounts": True,
            "invert_balance": True,
            "counterparty_name": "Name",
            "counterparty_ref": 4,
            "counterparty_bic": "BIC",
            "end_to_end_id": "E2E",
            "mandate_ref": "Mandate",
            "booking_text": "Text#2",
            "purpose": ["A", "B"],
            "instructed": {"amount": "Betrag#1", "currency": "Fremd"},
            "currency": "Whrg",
            "placeholders": ["n/a", "-"],
            "filters": [{"column": "Valuta", "equals": "vorgemerkt"}, {"column": "X", "matches": "^pend"}],
            "balance": {
                "mode": "labelled",
                "label": "Saldo",
                "right": 0,
                "below": 1,
                "date": {"format": "dd.MM.yyyy", "label": None, "right": 2, "below": 1, "pattern": None},
            },
            "export_date": {
                "label": "Export",
                "right": 0,
                "below": 1,
                "format": "dd.MM.yyyy HH:mm:ss",
                "pattern": None,
            },
            "coverage_end": {
                "label": "Stand",
                "right": 0,
                "below": 0,
                "format": "d.M.yyyy",
                "pattern": r"(\d+\.\d+\.\d{4})",
            },
            "statement_payment": {
                "counter_account_ref": "DE00X",
                "purpose": "S {statement_date}",
                "date_offset_days": 4,
            },
        }
    )
    return p


def test_minimal_round_trips_with_defaults() -> None:
    p = Profile.from_dict(minimal())
    p.validate()
    assert p.encoding is None and p.delimiter is None
    assert p.decimal_sep == "," and p.thousands_sep == "."
    assert p.balance is None and p.statement_payment is None and p.coverage_end is None
    assert Profile.from_dict(p.to_dict()) == p


def test_full_round_trips_and_is_json_serialisable() -> None:
    p = Profile.from_dict(full())
    p.validate()
    d = p.to_dict()
    assert Profile.from_dict(json.loads(json.dumps(d))) == p
    assert d["purpose"] == ["A", "B"]
    assert d["counterparty_ref"] == 4


def test_counterparty_name_is_a_column_or_a_column_with_a_pattern() -> None:
    plain = Profile.from_dict(minimal() | {"counterparty_name": "Name"})
    plain.validate()
    assert plain.counterparty_pattern is None and plain.to_dict()["counterparty_name"] == "Name"
    with_pattern = {"column": "Zweck", "pattern": "^([^,]+),"}
    p = Profile.from_dict(minimal() | {"counterparty_name": with_pattern})
    p.validate()
    assert (p.counterparty_name, p.counterparty_pattern) == ("Zweck", "^([^,]+),")
    assert p.to_dict()["counterparty_name"] == with_pattern
    assert Profile.from_dict(json.loads(json.dumps(p.to_dict()))) == p


@pytest.mark.parametrize(
    ("value", "setting"),
    [
        ({"column": "Z", "pattern": "("}, "counterparty_name.pattern"),
        ({"column": "Z", "pattern": "^[^,]+,"}, "counterparty_name.pattern"),
        ({"column": "Z", "pattern": 5}, "counterparty_name.pattern"),
        ({"column": "Z", "patern": "(a)"}, "counterparty_name.patern"),
        ({"pattern": "(a)"}, "counterparty_name"),
        ({"column": "", "pattern": "(a)"}, "counterparty_name.column"),
    ],
)
def test_invalid_counterparty_pattern_names_the_setting(value: dict[str, Any], setting: str) -> None:
    with pytest.raises(InvalidProfile, match=setting):
        Profile.from_dict(minimal() | {"counterparty_name": value}).validate()


def test_unknown_setting_rejected_by_name() -> None:
    d = minimal() | {"decimal_seperator": ","}
    with pytest.raises(InvalidProfile, match="decimal_seperator"):
        Profile.from_dict(d)


def test_missing_required_setting_named() -> None:
    d = minimal()
    del d["header_marker"]
    with pytest.raises(InvalidProfile, match="header_marker"):
        Profile.from_dict(d)


def bad(**changes: Any) -> dict[str, Any]:
    d = copy.deepcopy(full())
    d.update(changes)
    return d


@pytest.mark.parametrize(
    ("changes", "setting"),
    [
        ({"encoding": "no-such-codec"}, "encoding"),
        ({"delimiter": ";;"}, "delimiter"),
        ({"quote": ""}, "quote"),
        ({"header_marker": []}, "header_marker"),
        ({"header_marker": [""]}, "header_marker"),
        ({"booked_on": 0}, "booked_on"),
        ({"booked_on": ""}, "booked_on"),
        ({"date_format": "dd.MM.yy"}, "date_format"),
        ({"amount": {}}, "amount"),
        ({"amount": {"column": "A", "credit": "B", "debit": "C"}}, "amount"),
        ({"amount": {"credit": "B"}}, "amount"),
        ({"decimal_sep": ",,"}, "decimal_sep"),
        ({"decimal_sep": ",", "thousands_sep": ","}, "thousands_sep"),
        ({"purpose": "A"}, "purpose"),
        ({"instructed": {"amount": "A"}}, "instructed"),
        ({"filters": [{"column": "A"}]}, "filters"),
        ({"filters": [{"column": "A", "equals": "x", "matches": "y"}]}, "filters"),
        ({"filters": [{"column": "A", "matches": "("}]}, "filters"),
        ({"balance": {"mode": "sideways"}}, "balance"),
        ({"balance": {"mode": "running_column"}}, "balance"),
        ({"balance": {"mode": "labelled"}}, "balance"),
        ({"balance": {"mode": "labelled", "label": "S", "right": -1}}, "balance"),
        ({"export_date": {"format": "dd.MM.yyyy"}}, "export_date"),
        ({"coverage_end": {"format": "dd.MM.yyyy"}}, "coverage_end"),
        ({"coverage_end": {"label": "S", "format": "dd.MM.yyyy", "pattern": "("}}, "coverage_end"),
        (
            {"statement_payment": {"counter_account_ref": "X", "purpose": "p", "date_offset_days": 0}},
            "statement_payment",
        ),
        (
            {"statement_payment": {"counter_account_ref": "X", "purpose": "p", "date_offset_days": True}},
            "statement_payment",
        ),
        (
            {"statement_payment": {"counter_account_ref": "X", "purpose": "p", "date_offset_days": 367}},
            "statement_payment",
        ),
        (
            {"statement_payment": {"counter_account_ref": "X", "purpose": "p", "date_offset_days": 10**9}},
            "statement_payment",
        ),
        (
            {"statement_payment": {"counter_account_ref": "", "purpose": "p", "date_offset_days": 3}},
            "statement_payment",
        ),
    ],
)
def test_invalid_settings_name_the_setting(changes: dict[str, Any], setting: str) -> None:
    with pytest.raises(InvalidProfile, match=setting):
        Profile.from_dict(bad(**changes)).validate()


def test_validate_via_importer_entry_point() -> None:
    from app.plugins.importers.csv import CsvImporter

    CsvImporter().validate_settings(minimal())
    with pytest.raises(InvalidProfile, match="amount"):
        CsvImporter().validate_settings(minimal() | {"amount": {}})
