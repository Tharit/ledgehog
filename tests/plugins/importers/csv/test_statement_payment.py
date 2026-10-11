from __future__ import annotations

from datetime import date

import pytest

from app.core.plugins.errors import InvalidProfile, ParseFailed
from app.core.plugins.importer import IncomingRow
from app.plugins.importers.csv import CsvImporter
from app.plugins.importers.csv.profile import Profile
from app.plugins.importers.csv.report import ReportBuilder
from app.plugins.importers.csv.statement_payment import statement_payment
from tests.plugins.importers.csv.helpers import CARD, card_profile, run

PAY = {
    "counter_account_ref": "DE00 0000 0000 0000 0000 00",
    "purpose": "Card statement {statement_date}",
    "date_offset_days": 4,
}
TODAY = date(2026, 8, 10)


def test_net_negative_emits_one_synthetic_payment_after_coverage() -> None:
    pf = run(CARD, profile=card_profile(statement_payment=PAY), today=TODAY)
    *real, synth = pf.rows
    assert len(real) == 2
    assert synth.amount_minor == 4201  # the negated net of -12,00 and -30,01
    assert synth.booked_on == date(2026, 8, 7)  # coverage 3.8. + 4
    assert synth.value_on is None
    assert synth.currency == "EUR"
    assert synth.source_format == "csv:synthetic"
    assert synth.counterparty_ref == PAY["counter_account_ref"]
    assert synth.purpose == "Card statement 2026-08-03"
    assert synth.source_id is None
    assert synth.raw["row_count"] == 2
    assert synth.raw["sum_minor"] == -4201
    assert synth.raw["statement_date"] == "2026-08-03"
    assert synth.raw["settings"]["statement_payment"]["date_offset_days"] == 4
    assert dict(pf.importer_stats) == {"filtered": 0, "synthetic_skipped": 0}


def test_balance_record_stays_dated_at_coverage_and_data_start_ignores_the_payment() -> None:
    pf = run(CARD, profile=card_profile(statement_payment=PAY), today=TODAY)
    assert pf.covered_through == date(2026, 8, 3)
    assert pf.balance_on == date(2026, 8, 3)
    assert pf.reported_balance == -4201
    assert pf.data_start == date(2026, 8, 2)


def test_report_shows_the_synthetic_payment() -> None:
    pf = run(CARD, profile=card_profile(statement_payment=PAY), today=TODAY)
    s = pf.report.synthetic
    assert s is not None
    assert (s.amount_minor, s.booked_on, s.row_count, s.sum_minor) == (4201, date(2026, 8, 7), 2, -4201)
    assert pf.report.emitted == 2  # the synthetic row is not one of the file's rows


def test_net_positive_emits_nothing_and_counts_skipped() -> None:
    text = CARD.replace("Saldo:", "3.8.2026;3.8.2026;Refund;100,00\nSaldo:")
    pf = run(text, profile=card_profile(statement_payment=PAY, balance=None), today=TODAY)
    assert len(pf.rows) == 3
    assert all(r.source_format == "csv:card" for r in pf.rows)
    assert pf.importer_stats["synthetic_skipped"] == 1
    assert pf.report.synthetic is None


def test_net_exactly_zero() -> None:
    text = (
        "Abrechnungsdatum: 3.8.2026\nBelegdatum;Eingangstag;Zweck;Betrag\n"
        "1.8.2026;1.8.2026;a;-5,00\n2.8.2026;2.8.2026;b;5,00\n"
    )
    pf = run(text, profile=card_profile(statement_payment=PAY, balance=None))
    assert len(pf.rows) == 2 and pf.importer_stats["synthetic_skipped"] == 1


def test_net_is_over_all_rows_after_filtering_including_those_after_a_stated_end() -> None:
    text = CARD.replace("Saldo:", "5.8.2026;5.8.2026;Late;-1,00\nSaldo:")
    text = text.replace(
        "2.8.2026;3.8.2026;Shop;-30,01", "2.8.2026;3.8.2026;pending;-9,00\n2.8.2026;3.8.2026;Shop;-30,01"
    )
    pf = run(
        text,
        profile=card_profile(
            statement_payment=PAY, balance=None, filters=[{"column": "Zweck", "equals": "pending"}]
        ),
        today=TODAY,
    )
    assert pf.rows[-1].amount_minor == 4301  # -12,00 - 30,01 - 1,00; the filtered row is out
    assert pf.rows[-1].booked_on == date(2026, 8, 7)  # coverage stays the stated end


def test_off_by_default() -> None:
    pf = run(CARD, profile=card_profile(), today=TODAY)
    assert len(pf.rows) == 2 and pf.importer_stats["synthetic_skipped"] == 0


def test_same_file_twice_gives_identical_rows() -> None:
    a = run(CARD, profile=card_profile(statement_payment=PAY), today=TODAY)
    b = run(CARD, profile=card_profile(statement_payment=PAY), today=TODAY)
    assert a.rows == b.rows and a == b


def test_offset_below_one_is_rejected_when_the_profile_is_loaded() -> None:
    bad = card_profile(statement_payment={**PAY, "date_offset_days": 0})
    with pytest.raises(InvalidProfile, match="date_offset_days"):
        CsvImporter().validate_settings(bad)


def test_the_longest_offset_is_a_year_and_a_day() -> None:
    CsvImporter().validate_settings(card_profile(statement_payment={**PAY, "date_offset_days": 366}))


def test_a_date_beyond_the_calendar_is_a_parse_failure_not_an_overflow() -> None:
    prof = Profile.from_dict(card_profile(statement_payment=PAY))
    row = IncomingRow(
        amount_minor=-100, currency="EUR", booked_on=date(9999, 12, 30), source_format="x", raw={}
    )
    with pytest.raises(ParseFailed, match="statement_payment"):
        statement_payment(prof, [row], date(9999, 12, 31), "EUR", ReportBuilder(limit=3))
