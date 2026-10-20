"""MT940 statements to records, over a hand-built corpus (tests/.../statements/*.sta): invented data only,
documentation-range IBANs and "PAYEE n" (fints.md §6, spec §5.1)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.core.plugins.errors import ParseFailed
from app.core.plugins.importer import IncomingRow
from app.plugins.importers.fints.field86 import parse_field86, valid_iban
from app.plugins.importers.fints.statements import Read, read_statements

CORPUS = Path(__file__).parent / "statements"
UNTIL = date(2026, 10, 31)


def read(name: str, until: date = UNTIL) -> Read:
    return read_statements(
        (CORPUS / f"{name}.sta").read_text(encoding="latin-1"), until=until, minor_units_of=lambda c: 2
    )


def only(name: str) -> list[IncomingRow]:
    return list(read(name).rows)


# ---- a booking becomes a record ---------------------------------------------------------------------


def test_the_dk_layout_with_eref_kref_and_svwz_fills_the_columns() -> None:
    debit, credit = only("dk_basic")
    assert (debit.amount_minor, debit.currency) == (-1234, "EUR")
    assert (debit.booked_on, debit.value_on) == (date(2026, 10, 2), date(2026, 10, 2))
    assert debit.end_to_end_id == "E2E-0001"
    assert (
        debit.purpose == "Miete Oktober 2026"
    )  # KREF is no purpose; the subfields joined, whitespace collapsed
    assert debit.counterparty_ref == "DE89370400440532013000"
    assert (debit.counterparty_bic, debit.counterparty_name) == ("GENODEF1ABC", "PAYEE 1")
    assert debit.booking_text == "SEPA-UEBERWEISUNG"
    assert debit.source_id is None and debit.source_format == "mt940"
    assert debit.mandate_ref is None and debit.instructed_amount_minor is None
    assert (credit.amount_minor, credit.counterparty_ref, credit.counterparty_bic) == (
        10000,
        "GB82WEST12345698765432",
        "NOLADE21XYZ",
    )


def test_the_raw_payload_keeps_the_unparsed_field_86_and_the_library_s_fields() -> None:
    (debit, _) = only("dk_basic")
    assert debit.raw["statement"] == "STARTUMS"
    assert debit.raw["field86"].startswith("177?00SEPA-UEBERWEISUNG?10931?20EREF+E2E-0001")
    assert "\n?23 2026" in debit.raw["field86"]  # unparsed: the line break is still there
    assert debit.raw["line61"]["amount"] == "-12.34 EUR"
    assert all(isinstance(v, str) for v in debit.raw["line61"].values())


def test_mandate_creditor_and_deviating_payer_tags() -> None:
    (row,) = only("dk_mandate")
    assert row.mandate_ref == "MANDATE-77" and row.end_to_end_id == "E2E-0003"
    assert row.purpose == "Beitrag Q4"  # CRED and ABWA have no column and are no purpose: they stay in raw
    assert "CRED+DE98ZZZ09999999999" in row.raw["field86"]
    assert (row.counterparty_ref, row.counterparty_bic) == ("FR1420041010050500013M02606", "COBADEFF")


def test_an_iban_glued_to_the_name_is_split_off() -> None:
    (row,) = only("glued_iban")
    assert (row.counterparty_ref, row.counterparty_name) == ("NL91ABNA0417164300", "PAYEE 4")


def test_a_candidate_that_fails_mod_97_is_not_an_iban_and_stays_in_the_name() -> None:
    (row,) = only("bad_iban")
    assert row.counterparty_ref is None  # also: ?31 held an account number
    assert row.counterparty_name == "DE89370400440532013001PAYEE 5"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("DE89370400440532013000", "DE89370400440532013000"),
        ("de89 3704 0044 0532 0130 00", "DE89370400440532013000"),
        ("DE89370400440532013001", None),  # check digits
        ("DE8937040044053201300", None),  # length of the country
        ("XX89370400440532013000", None),  # unknown country
        ("0532013000", None),
    ],
)
def test_iban_validation(text: str, expected: str | None) -> None:
    assert valid_iban(text) == expected


def test_notprovided_in_any_case_and_an_empty_eref_mean_none() -> None:
    rows = only("notprovided")
    assert [r.end_to_end_id for r in rows] == [None, None, None]
    assert [r.purpose for r in rows] == ["eins", "zwei", "drei"]


def test_padded_and_newlined_references_come_out_whole() -> None:
    (row,) = only("padded_refs")
    assert (row.end_to_end_id, row.mandate_ref) == ("ABCDEFGHIJKLMNOP", "MANDATE-9")
    assert row.purpose == "Rechnung 4711"


# ---- purpose: a tag is a tag only at the start of a subfield, and only a known one --------------------


def test_a_tag_typed_by_the_payer_in_the_middle_of_a_subfield_is_ordinary_purpose() -> None:
    first = only("purpose_rules")[0]
    assert first.end_to_end_id == "E2E-9"  # the real tag, at the start of ?20
    assert first.purpose == "Hallo SVWZ+ da EREF+FAKE"  # EREF+FAKE is no tag here


def test_a_tag_at_the_start_of_a_subfield_is_recognised_wherever_it_follows() -> None:
    second = only("purpose_rules")[1]
    assert second.mandate_ref == "M-5"
    assert second.purpose == "Alpha Beta"  # both SVWZ parts; KREF and MREF are not purpose


def test_an_unknown_tag_stays_purpose() -> None:
    third = only("purpose_rules")[2]
    assert third.purpose == "ZZZZ+Rest bleibt Text"


def test_a_field_without_subfields_is_all_purpose() -> None:
    fourth = only("purpose_rules")[3]
    assert fourth.purpose == "Gutschrift Lohn Oktober"
    assert (fourth.counterparty_name, fourth.booking_text, fourth.end_to_end_id) == (None, None, None)


def test_a_tag_opening_an_unstructured_field_is_still_a_tag() -> None:
    parsed = parse_field86("EREF+X1 SVWZ+not at a start")
    assert parsed.end_to_end_id == "X1SVWZ+notatastart" and parsed.purpose is None


def test_iban_and_bic_tags_fill_the_counterparty_when_the_subfields_do_not() -> None:
    parsed = parse_field86("166?00GUTSCHRIFT?20IBAN+NL91ABNA0417164300?21BIC+ABNANL2A?32PAYEE 20")
    assert (parsed.counterparty_iban, parsed.counterparty_bic) == ("NL91ABNA0417164300", "ABNANL2A")
    assert parsed.purpose is None  # IBAN and BIC are columns, not remittance text


def test_subfield_31_wins_over_the_iban_tag() -> None:
    parsed = parse_field86("166?20IBAN+NL91ABNA0417164300?31DE89370400440532013000?32PAYEE 21")
    assert parsed.counterparty_iban == "DE89370400440532013000"


# ---- amounts, dates ----------------------------------------------------------------------------------


def test_reversal_marks_are_signed_as_the_money_moves() -> None:
    rc, rd = only("reversal")
    assert (rc.amount_minor, rd.amount_minor) == (-1000, 400)


def test_a_zero_booking_is_dropped_and_counted() -> None:
    result = read("zero_booking")
    assert [r.amount_minor for r in result.rows] == [-176] and result.filtered == 1


def test_the_entry_date_is_booked_on_and_its_year_follows_the_value_date_across_new_year() -> None:
    late_entry, early_entry = only("year_wrap")
    assert (late_entry.booked_on, late_entry.value_on) == (date(2026, 12, 31), date(2027, 1, 2))
    assert (early_entry.booked_on, early_entry.value_on) == (date(2027, 1, 1), date(2026, 12, 31))


def test_a_statement_in_another_currency_is_delivered_in_it_and_ingest_judges() -> None:
    (row,) = only("foreign_currency")
    assert (row.currency, row.amount_minor) == ("USD", -100)


def test_a_value_that_is_not_a_whole_number_of_minor_units_fails_the_run() -> None:
    with pytest.raises(ParseFailed, match="minor units"):
        read_statements(
            (CORPUS / "dk_basic.sta").read_text(encoding="latin-1"), until=UNTIL, minor_units_of=lambda c: 1
        )


# ---- the check of every statement -------------------------------------------------------------------


def test_a_statement_that_does_not_add_up_fails_naming_reference_and_dates_but_no_amount() -> None:
    with pytest.raises(ParseFailed) as err:
        read("unbalanced")
    message = str(err.value)
    assert "STARTUMS" in message and "2026-10-14" in message and "2026-10-15" in message
    assert not any(figure in message for figure in ("100,00", "95,00", "10,00", "9500", "1000"))


def test_no_statement_means_no_rows_and_no_balance() -> None:
    assert read_statements("", until=UNTIL, minor_units_of=lambda c: 2) == Read((), 0, None, None)
    assert read_statements("\r\n", until=UNTIL, minor_units_of=lambda c: 2).balance_minor is None


def test_text_that_is_not_mt940_fails_as_parse_failed() -> None:
    with pytest.raises(ParseFailed):
        read_statements(":20:X\n:61:garbage\n", until=UNTIL, minor_units_of=lambda c: 2)


# ---- the closing balance -----------------------------------------------------------------------------


def test_the_balance_is_the_closing_figure_of_the_last_final_statement_dated_at_its_balance_date() -> None:
    result = read("dk_basic")
    assert (result.balance_minor, result.balance_on) == (108766, date(2026, 10, 5))


def test_a_closing_balance_that_is_only_intermediate_gives_no_balance() -> None:
    result = read("only_62m")
    assert len(result.rows) == 1 and (result.balance_minor, result.balance_on) == (None, None)


def test_the_last_final_statement_wins_and_an_intermediate_one_after_it_does_not() -> None:
    result = read("two_statements")
    assert len(result.rows) == 3
    assert (result.balance_minor, result.balance_on) == (9500, date(2026, 10, 21))


def test_a_statement_dated_after_the_last_closed_day_is_rolled_back_to_it() -> None:
    result = read("two_statements", until=date(2026, 10, 20))
    assert (result.balance_minor, result.balance_on) == (9000, date(2026, 10, 20))


def test_one_statement_running_into_today_is_rolled_back_to_the_last_closed_day() -> None:
    result = read("runs_into_today", until=date(2026, 10, 19))
    # 85,00 at the 20th includes today's booking (-5,00): at the 19th the balance was 90,00
    assert (result.balance_minor, result.balance_on) == (9000, date(2026, 10, 19))
    # today's row is kept
    assert [r.booked_on for r in result.rows] == [date(2026, 10, 19), date(2026, 10, 20)]


def test_a_forward_dated_line_the_balance_includes_moves_the_figure_to_that_line() -> None:
    result = read("forward_dated")
    assert (result.balance_minor, result.balance_on) == (17000, date(2026, 10, 19))


def test_a_figure_dated_after_the_last_closed_day_loses_the_rows_booked_after_it() -> None:
    result = read("forward_dated", until=date(2026, 10, 17))
    # 170,00 includes the line of the 19th (-20,00); at the 17th the balance was 190,00
    assert (result.balance_minor, result.balance_on) == (19000, date(2026, 10, 17))


def test_the_year_wrap_statement_balance() -> None:
    result = read("year_wrap", until=date(2027, 1, 10))
    assert (result.balance_minor, result.balance_on) == (4600, date(2027, 1, 2))
