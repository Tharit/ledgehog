from __future__ import annotations

from datetime import date

import pytest

from app.core.plugins.errors import InvalidProfile, ParseFailed
from tests.plugins.importers.csv.helpers import HEADER, run


def test_basic_row_mapping() -> None:
    pf = run(HEADER + "03.08.2026;-12,50;Coffee   Shop\n", value_on="Datum", counterparty_name="Zweck")
    (row,) = pf.rows
    assert row.amount_minor == -1250
    assert row.currency == "EUR"
    assert row.booked_on == date(2026, 8, 3)
    assert row.value_on == date(2026, 8, 3)
    assert row.source_format == "csv:t"
    assert row.source_id is None
    assert row.purpose == "Coffee Shop"
    assert row.counterparty_name == "Coffee Shop"
    assert row.counterparty_ref is None and row.end_to_end_id is None
    assert row.raw == {
        "profile": "t",
        "header": ["Datum", "Betrag", "Zweck"],
        "cells": ["03.08.2026", "-12,50", "Coffee   Shop"],
        "text": "03.08.2026;-12,50;Coffee   Shop",
    }
    assert pf.covered_through == date(2026, 8, 3)
    assert pf.data_start == date(2026, 8, 3)
    assert pf.reported_balance is None and pf.balance_on is None
    assert dict(pf.importer_stats) == {"filtered": 0, "synthetic_skipped": 0}
    assert pf.report.emitted == 1 and pf.report.rows_read == 1


def test_all_optional_columns() -> None:
    text = "Datum;Betrag;N;I;B;E;M;T\n03.08.2026;1,00;Name;DE00 0000 0000;BICXXXX;E2E-1;MAN-1;Lastschrift\n"
    pf = run(
        text,
        profile={
            **{
                "label": "t",
                "delimiter": ";",
                "header_marker": ["Datum", "Betrag"],
                "booked_on": "Datum",
                "date_format": "dd.MM.yyyy",
                "amount": {"column": "Betrag"},
            },
            "counterparty_name": "N",
            "counterparty_ref": "I",
            "counterparty_bic": "B",
            "end_to_end_id": "E",
            "mandate_ref": "M",
            "booking_text": "T",
        },
    )
    r = pf.rows[0]
    assert (r.counterparty_name, r.counterparty_ref, r.counterparty_bic) == (
        "Name",
        "DE00 0000 0000",
        "BICXXXX",
    )
    assert (r.end_to_end_id, r.mandate_ref, r.booking_text) == ("E2E-1", "MAN-1", "Lastschrift")
    assert r.purpose is None


def test_purpose_joins_trimmed_non_empty_cells() -> None:
    text = "Datum;Betrag;A;B;C\n03.08.2026;1,00;  one  two ;;three\n"
    pf = run(text, purpose=["A", "B", "C"])
    assert pf.rows[0].purpose == "one two three"


def test_footer_blank_and_title_rows_are_skipped_and_counted_with_examples() -> None:
    text = HEADER + "03.08.2026;1,00;a\n\nAbschnitt;;\nSaldo:;;-5,00\n04.08.2026;2,00;b\n;;\n"
    pf = run(text)
    assert len(pf.rows) == 2
    assert pf.report.rows_read == 4  # blank lines are not rows
    assert pf.report.skipped.count == 2
    assert [e.row for e in pf.report.skipped.examples] == [4, 5]
    assert all("booking date" in e.reason for e in pf.report.skipped.examples)


def test_examples_are_capped() -> None:
    text = HEADER + "03.08.2026;1,00;a\n" + "".join(f"x{i};;\n" for i in range(10))
    pf = run(text, samples=3)
    assert pf.report.skipped.count == 10
    assert len(pf.report.skipped.examples) == 3


def test_short_and_long_rows_are_tolerated() -> None:
    text = HEADER + "03.08.2026;1,00\n04.08.2026;2,00;x;extra;more\n"
    pf = run(text)
    assert [r.purpose for r in pf.rows] == [None, "x"]


def test_invalid_date_row_is_skipped() -> None:
    pf = run(HEADER + "31.02.2026;1,00;a\n03.08.2026;1,00;b\n")
    assert len(pf.rows) == 1 and pf.report.skipped.count == 1


def test_unpadded_dates() -> None:
    pf = run(HEADER + "3.8.2026;1,00;a\n", date_format="d.M.yyyy")
    assert pf.rows[0].booked_on == date(2026, 8, 3)


@pytest.mark.parametrize(
    ("cell", "minor"),
    [("1.234,56", 123456), ("-0,5", -50), ("-7", -700), ("+3,10", 310)],
)
def test_amount_forms(cell: str, minor: int) -> None:
    assert run(HEADER + f"03.08.2026;{cell};a\n").rows[0].amount_minor == minor


def test_three_decimals_rejected_naming_the_row() -> None:
    with pytest.raises(ParseFailed, match="row 2.*amount") as ei:
        run(HEADER + "03.08.2026;1,234;a\n")
    assert ei.value.report is not None and ei.value.report.failure is not None


def test_garbage_amount_fails_without_echoing_it() -> None:
    with pytest.raises(ParseFailed) as ei:
        run(HEADER + "03.08.2026;SECRET-CELL;a\n")
    assert "SECRET-CELL" not in str(ei.value)
    assert ei.value.report is not None and "SECRET-CELL" not in repr(ei.value.report)


def test_zero_bookings_are_dropped_and_counted_in_filtered() -> None:
    pf = run(HEADER + "03.08.2026;0,00;a\n04.08.2026;-0,00;b\n05.08.2026;1,00;c\n")
    assert len(pf.rows) == 1
    assert pf.importer_stats["filtered"] == 2
    assert pf.report.zero_dropped.count == 2
    assert pf.report.filtered.count == 0
    assert pf.covered_through == date(2026, 8, 5)


def test_credit_debit_pair() -> None:
    text = "Datum;Haben;Soll\n03.08.2026;10,00;\n04.08.2026;;4,50\n05.08.2026;;\n06.08.2026;1,00;1,00\n"
    pf = run(
        text,
        profile={
            "label": "t",
            "delimiter": ";",
            "header_marker": ["Datum", "Haben", "Soll"],
            "booked_on": "Datum",
            "date_format": "dd.MM.yyyy",
            "amount": {"credit": "Haben", "debit": "Soll"},
        },
    )
    assert [r.amount_minor for r in pf.rows] == [1000, -450]
    assert pf.importer_stats["filtered"] == 2  # both-empty and equal credit/debit are zero bookings


def test_invert_amounts() -> None:
    pf = run(HEADER + "03.08.2026;5,00;a\n04.08.2026;-2,00;b\n", invert_amounts=True)
    assert [r.amount_minor for r in pf.rows] == [-500, 200]


def test_placeholders_in_amount_and_date_cells() -> None:
    text = "Datum;Haben;Soll;Zweck\n03.08.2026;n/a;3,00;x\nn/a;1,00;;y\n04.08.2026;2,00;n/a;n/a\n"
    pf = run(
        text,
        profile={
            "label": "t",
            "delimiter": ";",
            "header_marker": ["Datum", "Haben"],
            "booked_on": "Datum",
            "date_format": "dd.MM.yyyy",
            "amount": {"credit": "Haben", "debit": "Soll"},
            "purpose": ["Zweck"],
            "placeholders": ["n/a"],
        },
    )
    assert [r.amount_minor for r in pf.rows] == [-300, 200]
    assert pf.rows[1].purpose is None
    assert pf.report.skipped.count == 1  # the placeholder date cell is empty: not a transaction


def test_empty_amount_in_single_column_fails() -> None:
    with pytest.raises(ParseFailed, match="amount"):
        run(HEADER + "03.08.2026;;a\n")


def test_value_date_that_does_not_parse_fails() -> None:
    with pytest.raises(ParseFailed, match="value_on"):
        run(
            "Datum;Valuta;Betrag\n03.08.2026;soon;1,00\n",
            header_marker=["Datum", "Valuta"],
            value_on="Valuta",
            purpose=[],
        )


def test_empty_value_date_is_none() -> None:
    pf = run(
        "Datum;Valuta;Betrag\n03.08.2026;;1,00\n",
        header_marker=["Datum", "Valuta"],
        value_on="Valuta",
        purpose=[],
    )
    assert pf.rows[0].value_on is None


def test_unknown_column_fails_naming_the_setting() -> None:
    with pytest.raises(ParseFailed, match="booking_text"):
        run(HEADER + "03.08.2026;1,00;a\n", booking_text="Nope")


# -- instructed amount ---------------------------------------------------------------------------

INSTR = "Datum;Fremd;Betrag#1;Kurs;Betrag#2\n"


def instr_profile(**over: object) -> dict[str, object]:
    return {
        "label": "t",
        "delimiter": ";",
        "header_marker": ["Datum", "Fremd"],
        "booked_on": "Datum",
        "date_format": "dd.MM.yyyy",
        "amount": {"column": "Betrag#2"},
        "instructed": {"amount": 3, "currency": "Fremd"},
        **over,
    }


def test_instructed_pair_kept_on_foreign_currency_rows() -> None:
    header = "Datum;Fremd;Betrag;Kurs;Betrag\n"
    pf = run(header + "03.08.2026;USD;-10,00;1,1;-9,09\n", profile=instr_profile())
    r = pf.rows[0]
    assert (r.amount_minor, r.instructed_amount_minor, r.instructed_currency) == (-909, -1000, "USD")


def test_instructed_pair_ignored_when_currency_is_the_accounts() -> None:
    header = "Datum;Fremd;Betrag;Kurs;Betrag\n"
    pf = run(header + "03.08.2026;EUR;-9,09;;-9,09\n03.08.2026;;-1,00;;-1,00\n", profile=instr_profile())
    assert all(r.instructed_amount_minor is None and r.instructed_currency is None for r in pf.rows)


def test_instructed_follows_invert_amounts() -> None:
    header = "Datum;Fremd;Betrag;Kurs;Betrag\n"
    pf = run(header + "03.08.2026;USD;10,00;1,1;9,09\n", profile=instr_profile(invert_amounts=True))
    r = pf.rows[0]
    assert (r.amount_minor, r.instructed_amount_minor) == (-909, -1000)


def test_instructed_amount_uses_the_instructed_currencys_exponent() -> None:
    header = "Datum;Fremd;Betrag;Kurs;Betrag\n"
    pf = run(header + "03.08.2026;JPY;-1.500;0,0065;-9,75\n", profile=instr_profile(thousands_sep="."))
    assert (pf.rows[0].amount_minor, pf.rows[0].instructed_amount_minor) == (-975, -1500)
    pf = run(header + "03.08.2026;KWD;-1,234;3,0;-3,70\n", profile=instr_profile())
    assert (pf.rows[0].amount_minor, pf.rows[0].instructed_amount_minor) == (-370, -1234)


def test_instructed_decimals_beyond_the_instructed_exponent_fail() -> None:
    header = "Datum;Fremd;Betrag;Kurs;Betrag\n"
    with pytest.raises(ParseFailed, match="instructed.amount"):
        run(header + "03.08.2026;JPY;-15,5;1;-9,75\n", profile=instr_profile())


def test_unknown_currency_in_the_lookup_fails_naming_it() -> None:
    header = "Datum;Fremd;Betrag;Kurs;Betrag\n"
    with pytest.raises(ParseFailed, match="XYZ"):
        run(header + "03.08.2026;XYZ;-10,00;1;-9,09\n", profile=instr_profile())
    with pytest.raises(ParseFailed, match="SEK"):
        run(HEADER + "03.08.2026;1,00;a\n", currency="SEK")


def test_account_amounts_use_the_account_currencys_exponent() -> None:
    pf = run(HEADER + "03.08.2026;1.500;a\n", currency="JPY", thousands_sep=".")
    assert pf.rows[0].amount_minor == 1500


# -- row filters and currency --------------------------------------------------------------------

FH = "Datum;Valuta;Betrag;Whrg\n"


def fprofile(**over: object) -> dict[str, object]:
    return {
        "label": "t",
        "delimiter": ";",
        "header_marker": ["Datum", "Valuta"],
        "booked_on": "Datum",
        "value_on": "Valuta",
        "date_format": "dd.MM.yyyy",
        "amount": {"column": "Betrag"},
        **over,
    }


def test_filter_equals_sees_the_cell_before_parsing() -> None:
    text = FH + "03.08.2026;04.08.2026;1,00;EUR\n31.12.2099;vorgemerkt;2,00;EUR\n"
    pf = run(text, profile=fprofile(filters=[{"column": "Valuta", "equals": "vorgemerkt"}]))
    assert len(pf.rows) == 1
    assert pf.report.filtered.count == 1
    assert pf.report.filtered.examples[0].row == 3
    assert pf.importer_stats["filtered"] == 0  # row filters never count in the stored stats


def test_filter_equals_is_exact_and_case_sensitive_matches_is_a_search() -> None:
    text = (
        FH
        + "03.08.2026;a;1,00;EUR\n04.08.2026;vorgemerkt;2,00;EUR\n"
        + "05.08.2026;nicht vorgemerkt;3,00;EUR\n06.08.2026;Vorgemerkt;4,00;EUR\n"
    )
    eq = run(text, profile=fprofile(value_on=None, filters=[{"column": "Valuta", "equals": "vorgemerkt"}]))
    assert [r.amount_minor for r in eq.rows] == [100, 300, 400]
    sub = run(text, profile=fprofile(value_on=None, filters=[{"column": "Valuta", "matches": "vorgemerkt"}]))
    assert [r.amount_minor for r in sub.rows] == [100, 400]


def test_currency_column_mismatch_is_reported_and_rows_unchanged() -> None:
    text = FH + "03.08.2026;03.08.2026;1,00;EUR\n04.08.2026;04.08.2026;2,00;USD\n"
    pf = run(text, profile=fprofile(currency="Whrg"))
    assert [r.currency for r in pf.rows] == ["EUR", "USD"]  # ingest raises ContractViolation
    assert pf.report.currency_mismatch.count == 1
    assert pf.report.currency_mismatch.examples[0].row == 3
    assert any("currency" in w for w in pf.report.warnings)


def test_filtered_foreign_currency_rows_do_not_mismatch() -> None:
    text = FH + "03.08.2026;03.08.2026;1,00;EUR\n04.08.2026;04.08.2026;2,00;USD\n"
    pf = run(text, profile=fprofile(currency="Whrg", filters=[{"column": "Whrg", "equals": "USD"}]))
    assert len(pf.rows) == 1 and pf.report.currency_mismatch.count == 0


def test_every_row_skipped_warns() -> None:
    text = HEADER + "x;1;a\ny;2;b\n"
    with pytest.raises(ParseFailed, match="coverage") as ei:
        run(text)
    assert ei.value.report is not None
    assert any("every row" in w for w in ei.value.report.warnings)


def test_all_filtered_without_stated_end_fails_no_coverage() -> None:
    with pytest.raises(ParseFailed, match="coverage"):
        run(HEADER + "03.08.2026;0,00;a\n")


def test_same_file_twice_gives_identical_parse() -> None:
    text = HEADER + "03.08.2026;1,00;a\n04.08.2026;-2,00;b\n"
    assert run(text) == run(text)


def test_sample_rows_truncate_cells_to_24() -> None:
    long = "x" * 40
    pf = run(HEADER + f"03.08.2026;1,00;{long}\n")
    cells = pf.report.sample[0].cells
    assert cells == ("03.08.2026", "1,00", "x" * 24)


def test_report_mapped_columns_and_header_line() -> None:
    pf = run("Preamble\n" + HEADER + "03.08.2026;1,00;a\n")
    assert pf.report.header_line == 2
    assert pf.report.delimiter == ";" and pf.report.encoding == "utf-8"
    cols = {(c.field, c.name, c.index) for c in pf.report.columns}
    assert (
        ("booked_on", "Datum", 0) in cols
        and ("amount", "Betrag", 1) in cols
        and ("purpose", "Zweck", 2) in cols
    )


def test_column_positions_are_one_based() -> None:
    pf = run(HEADER + "03.08.2026;-1,00;a\n", booked_on=1, amount={"column": 2}, purpose=[3])
    assert (pf.rows[0].booked_on, pf.rows[0].amount_minor, pf.rows[0].purpose) == (
        date(2026, 8, 3),
        -100,
        "a",
    )
    with pytest.raises(InvalidProfile, match="counts from 1"):
        run(HEADER + "03.08.2026;-1,00;a\n", booked_on=0)


def test_a_file_of_only_blank_lines_below_the_header_has_no_transactions() -> None:
    from tests.plugins.importers.csv.helpers import base_profile

    p = base_profile(
        coverage_end={"label": "Bis", "right": 1, "format": "dd.MM.yyyy"}, balance=None, purpose=[]
    )
    pf = run("Bis;19.08.2026\n" + HEADER + "\n \n;;\n", profile=p)
    assert pf.report.rows_read == 0 and pf.report.skipped.count == 0
    assert any("no rows" in w for w in pf.report.warnings)
    assert not any("every row" in w for w in pf.report.warnings)
