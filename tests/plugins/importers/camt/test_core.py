"""The core against the statement model directly, no reader involved (camt.md §4, §7)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as Dec

import pytest

from app.core.plugins.errors import ParseFailed
from app.core.plugins.importer import ParsedFile
from app.core.plugins.report import ReportBuilder
from app.plugins.importers.camt import core
from app.plugins.importers.camt.model import Balance, Detail, Entry, Report, Statement
from tests.plugins.importers.camt.builders import TODAY, exponent_of

D = date
EXPORT = D(2026, 8, 20)


def bal(amount: str, on: date, credit: bool = True, currency: str = "EUR") -> Balance:
    return Balance(Dec(amount), currency, credit, on)


def ent(
    amount: str,
    booked: date,
    credit: bool = True,
    currency: str = "EUR",
    details: tuple[Detail, ...] = (Detail(name="Acme", account="DE89370400440532013000"),),
) -> Entry:
    return Entry(Dec(amount), currency, credit, booked, None, details, "<e/>")


def rep(opening: Balance | None, closing: Balance | None, *entries: Entry, mid: str = "M1") -> Report:
    return Report(mid, opening, closing, entries)


def stmt(*reports: Report, export: date | None = EXPORT, pending: int = 0) -> Statement:
    return Statement("olb", "camt.052", export, reports, pending)


def go(s: Statement, currency: str = "EUR", today: date = TODAY, samples: int = 5) -> ParsedFile:
    return core.run(s, ReportBuilder(limit=samples), currency, exponent_of, today)


def refuses(s: Statement, fragment: str, **kw: object) -> str:
    with pytest.raises(ParseFailed) as err:
        go(s, **kw)  # type: ignore[arg-type]
    assert fragment in str(err.value)
    return str(err.value)


class TestCheck:
    def test_passes_when_the_entries_bridge_the_balances(self) -> None:
        r = rep(
            bal("100", D(2026, 8, 10)),
            bal("85.50", D(2026, 8, 12)),
            ent("20", D(2026, 8, 11), False),
            ent("5.5", D(2026, 8, 12)),
        )
        assert len(go(stmt(r)).rows) == 2

    def test_a_mismatch_names_the_message_and_no_amounts(self) -> None:
        r = rep(
            bal("100", D(2026, 8, 10)),
            bal("85.51", D(2026, 8, 12)),
            ent("20", D(2026, 8, 11), False),
            mid="CAMT-77",
        )
        msg = refuses(stmt(r), "CAMT-77")
        assert not any(ch.isdigit() for ch in msg.replace("CAMT-77", ""))

    def test_the_second_report_is_checked_too(self) -> None:
        good = rep(bal("0", D(2026, 8, 1)), bal("0", D(2026, 8, 2)), mid="A")
        bad = rep(bal("0", D(2026, 8, 3)), bal("1", D(2026, 8, 4)), mid="B")
        refuses(stmt(good, bad), "report B")

    def test_a_debit_balance_is_negative(self) -> None:
        r = rep(
            bal("100", D(2026, 8, 10), False), bal("90", D(2026, 8, 11), False), ent("10", D(2026, 8, 11))
        )
        assert go(stmt(r)).rows[0].amount_minor == 1000

    def test_a_report_without_both_balances_fails(self) -> None:
        refuses(stmt(rep(bal("1", D(2026, 8, 10)), None)), "report M1")
        refuses(stmt(rep(None, bal("1", D(2026, 8, 10)))), "report M1")

    def test_mixed_currencies_in_a_report_fail(self) -> None:
        r = rep(bal("0", D(2026, 8, 10)), bal("0", D(2026, 8, 11)), ent("1", D(2026, 8, 11), currency="USD"))
        refuses(stmt(r), "one currency")

    def test_no_report_fails(self) -> None:
        refuses(stmt(), "no booked report")


class TestRecords:
    def test_sign_follows_the_credit_mark(self) -> None:
        r = rep(
            bal("0", D(2026, 8, 10)),
            bal("9", D(2026, 8, 11), False),
            ent("3", D(2026, 8, 11), False),
            ent("1", D(2026, 8, 11), False),
            ent("3", D(2026, 8, 11)),
            ent("8", D(2026, 8, 11), False),
        )
        assert [x.amount_minor for x in go(stmt(r)).rows] == [-300, -100, 300, -800]

    def test_minor_units_follow_the_currency(self) -> None:
        r = rep(
            bal("0", D(2026, 8, 10), currency="JPY"),
            bal("500", D(2026, 8, 11), currency="JPY"),
            ent("500", D(2026, 8, 11), currency="JPY"),
        )
        assert go(stmt(r), currency="JPY").rows[0].amount_minor == 500

    def test_a_non_whole_minor_amount_fails(self) -> None:
        r = rep(bal("0", D(2026, 8, 10)), bal("0.001", D(2026, 8, 11)), ent("0.001", D(2026, 8, 11)))
        refuses(stmt(r), "whole number of minor units")

    def test_trailing_zeros_are_whole(self) -> None:
        r = rep(bal("0", D(2026, 8, 10)), bal("1.100", D(2026, 8, 11)), ent("1.100", D(2026, 8, 11)))
        assert go(stmt(r)).rows[0].amount_minor == 110

    def test_zero_bookings_are_dropped_and_counted(self) -> None:
        r = rep(
            bal("5", D(2026, 8, 10)),
            bal("5", D(2026, 8, 11)),
            ent("0", D(2026, 8, 11)),
            ent("0.00", D(2026, 8, 11), False),
        )
        p = go(stmt(r))
        assert p.rows == () and p.importer_stats == {"filtered": 2}
        assert (p.report.rows_read, p.report.emitted, p.report.zero_dropped.count) == (2, 0, 2)

    def test_pending_entries_are_counted_never_imported(self) -> None:
        r = rep(bal("0", D(2026, 8, 10)), bal("1", D(2026, 8, 11)), ent("1", D(2026, 8, 11)))
        p = go(stmt(r, pending=3))
        assert len(p.rows) == 1 and p.importer_stats == {"filtered": 0}
        assert p.report.filtered.count == 3 and "pending" in p.report.filtered.examples[0].reason

    def test_columns_of_a_single_detail_entry(self) -> None:
        d = Detail(
            name="  Acme\n GmbH ",
            account="DE89370400440532013000",
            agent="COBADEFFXXX",
            end_to_end_id="E2E-1",
            mandate_id="M-9",
            remittance=("Rechnung  17", " vom 3.", "Mai"),
            codes=("PMNT-IDDT-ESDD",),
        )
        r = rep(bal("0", D(2026, 8, 10)), bal("1", D(2026, 8, 11)), ent("1", D(2026, 8, 11), details=(d,)))
        row = go(stmt(r)).rows[0]
        assert (row.counterparty_name, row.counterparty_ref, row.counterparty_bic) == (
            "Acme GmbH",
            "DE89370400440532013000",
            "COBADEFFXXX",
        )
        assert (row.end_to_end_id, row.mandate_ref, row.purpose) == ("E2E-1", "M-9", "Rechnung 17 vom 3. Mai")
        assert (row.booking_text, row.source_id, row.source_format) == (None, None, "camt052:olb")
        assert row.raw == {"report": "M1", "entry": "<e/>"}

    @pytest.mark.parametrize("e2e", ["NOTPROVIDED", "notprovided", "NotProvided", "", None])
    def test_no_end_to_end_id(self, e2e: str | None) -> None:
        r = rep(
            bal("0", D(2026, 8, 10)),
            bal("1", D(2026, 8, 11)),
            ent("1", D(2026, 8, 11), details=(Detail(end_to_end_id=e2e),)),
        )
        assert go(stmt(r)).rows[0].end_to_end_id is None

    def test_several_details_make_one_row_without_counterparty(self) -> None:
        a = Detail(name="A", account="X1", end_to_end_id="E1", remittance=("one",))
        b = Detail(name="B", account="X2", remittance=("two", "three"))
        r = rep(
            bal("0", D(2026, 8, 10)),
            bal("-9", D(2026, 8, 11)),
            ent("9", D(2026, 8, 11), False, details=(a, b)),
        )
        row = go(stmt(r)).rows[0]
        assert row.amount_minor == -900
        assert (row.counterparty_name, row.counterparty_ref, row.counterparty_bic, row.end_to_end_id) == (
            None,
            None,
            None,
            None,
        )
        assert row.purpose == "one two three"

    def test_no_details_no_purpose(self) -> None:
        r = rep(bal("0", D(2026, 8, 10)), bal("1", D(2026, 8, 11)), ent("1", D(2026, 8, 11), details=()))
        assert go(stmt(r)).rows[0].purpose is None

    def test_a_report_in_another_currency_fails_on_its_closing_balance(self) -> None:
        r = rep(
            bal("0", D(2026, 8, 10), currency="USD"),
            bal("1", D(2026, 8, 11), currency="USD"),
            ent("1", D(2026, 8, 11), currency="USD"),
        )
        with pytest.raises(ParseFailed) as err:
            go(stmt(r))  # the closing balance is not in the account's currency
        assert "currency" in str(err.value)

    def test_the_sample_is_limited(self) -> None:
        es = tuple(ent("1", D(2026, 8, 11)) for _ in range(4))
        r = rep(bal("0", D(2026, 8, 10)), bal("4", D(2026, 8, 11)), *es)
        assert len(go(stmt(r), samples=2).report.sample) == 2


class TestCoverage:
    def test_the_closing_date_of_the_last_report(self) -> None:
        a = rep(bal("0", D(2026, 8, 1)), bal("0", D(2026, 8, 5)), mid="A")
        b = rep(bal("0", D(2026, 8, 6)), bal("0", D(2026, 8, 12)), mid="B")
        p = go(stmt(a, b))
        assert p.covered_through == D(2026, 8, 12) and p.report.coverage == D(2026, 8, 12)

    def test_capped_before_the_export_date(self) -> None:
        r = rep(bal("0", D(2026, 8, 10)), bal("0", D(2026, 8, 20)))
        assert go(stmt(r)).covered_through == D(2026, 8, 19)
        assert go(stmt(r, export=D(2026, 8, 25))).covered_through == D(2026, 8, 20)

    def test_without_an_export_date_it_is_before_today(self) -> None:
        r = rep(bal("0", D(2026, 8, 10)), bal("0", D(2026, 9, 1)))
        p = go(stmt(r, export=None), today=D(2026, 8, 30))
        assert p.covered_through == D(2026, 8, 29)
        assert p.report.export_date == D(2026, 8, 30) and "upload" in (p.report.export_date_source or "")

    def test_data_starts_at_the_earliest_booking_or_the_first_opening(self) -> None:
        r = rep(
            bal("0", D(2026, 8, 3)),
            bal("2", D(2026, 8, 11)),
            ent("1", D(2026, 8, 9)),
            ent("1", D(2026, 8, 5)),
        )
        assert go(stmt(r)).data_start == D(2026, 8, 5)
        assert go(stmt(rep(bal("0", D(2026, 8, 3)), bal("0", D(2026, 8, 11))))).data_start == D(2026, 8, 3)


class TestBalance:
    def test_the_closing_balance_of_the_last_report(self) -> None:
        a = rep(bal("0", D(2026, 8, 1)), bal("5", D(2026, 8, 5)), ent("5", D(2026, 8, 5)), mid="A")
        b = rep(
            bal("5", D(2026, 8, 6)), bal("2", D(2026, 8, 12), False), ent("7", D(2026, 8, 12), False), mid="B"
        )
        p = go(stmt(a, b))
        assert (p.reported_balance, p.balance_on) == (-200, D(2026, 8, 12))
        assert p.report.balance is not None and p.report.balance.rolled_back_rows == 0

    def test_a_debit_closing_balance_is_negative(self) -> None:
        r = rep(bal("10", D(2026, 8, 10), False), bal("10", D(2026, 8, 11), False))
        assert go(stmt(r)).reported_balance == -1000

    def test_the_figure_is_dated_at_a_later_booking_and_rolled_back_to_the_coverage(self) -> None:
        r = rep(bal("0", D(2026, 8, 10)), bal("4", D(2026, 8, 10)), ent("4", D(2026, 8, 12)))
        p = go(stmt(r))
        assert p.report.balance is not None and p.report.balance.figure_on == D(2026, 8, 12)
        assert (p.reported_balance, p.balance_on) == (0, D(2026, 8, 10))
        assert p.report.balance.rolled_back_by_minor == 400

    def test_rolled_back_to_the_last_closed_day(self) -> None:
        # a figure dated on the export day is dated the day before it, the day's booking taken off
        r = rep(
            bal("100", D(2026, 8, 18)),
            bal("130", D(2026, 8, 20)),
            ent("10", D(2026, 8, 19)),
            ent("20", D(2026, 8, 20)),
        )
        p = go(stmt(r))
        assert p.report.coverage == D(2026, 8, 19)
        assert (p.reported_balance, p.balance_on) == (11000, D(2026, 8, 19))
        b = p.report.balance
        assert b is not None and (b.figure_minor, b.rolled_back_by_minor, b.rolled_back_rows) == (
            13000,
            2000,
            1,
        )

    def test_rolled_back_to_the_coverage(self) -> None:
        # the figure is dated after the coverage: only possible with a booking after the closing date
        r = rep(bal("0", D(2026, 8, 10)), bal("3", D(2026, 8, 10)), ent("3", D(2026, 8, 14)))
        p = go(stmt(r, export=D(2026, 8, 13)))
        assert (p.reported_balance, p.balance_on, p.covered_through) == (0, D(2026, 8, 10), D(2026, 8, 10))
        assert p.report.balance is not None and p.report.balance.rolled_back_rows == 1

    def test_a_quiet_account_is_dated_at_its_coverage(self) -> None:
        r = rep(bal("5", D(2026, 8, 3)), bal("5", D(2026, 8, 3)))
        p = go(stmt(r))
        assert (p.reported_balance, p.balance_on) == (500, D(2026, 8, 3))

    def test_a_closing_balance_in_another_currency_fails(self) -> None:
        r = rep(bal("0", D(2026, 8, 10), currency="USD"), bal("0", D(2026, 8, 11), currency="USD"))
        refuses(stmt(r), "account's currency")

    def test_a_non_whole_closing_balance_fails(self) -> None:
        r = rep(bal("0.001", D(2026, 8, 10)), bal("0.001", D(2026, 8, 11)))
        refuses(stmt(r), "whole number of minor units")
