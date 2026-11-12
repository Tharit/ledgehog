"""The OLB reader and the root-element detection (camt.md §3, §5), against hand-built files."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.plugins.errors import ParseFailed
from app.plugins.importers.camt.detect import read_statement
from app.plugins.importers.camt.olb import bank_day
from tests.plugins.importers.camt.builders import (
    balance,
    detail,
    document,
    entry,
    report,
    simple,
    utc,
)

D = date


def fails(xml: str | bytes, fragment: str) -> None:
    with pytest.raises(ParseFailed) as err:
        read_statement(xml if isinstance(xml, bytes) else xml.encode())
    assert fragment in str(err.value)


class TestDetection:
    def test_the_olb_root_is_read(self) -> None:
        s = read_statement(simple().encode())
        assert (s.reader, s.message_type, len(s.reports)) == ("olb", "camt.052", 1)

    def test_camt053_descriptor(self) -> None:
        assert read_statement(simple(descriptor="camt.053.001.08").encode()).message_type == "camt.053"

    def test_another_message_type_fails(self) -> None:
        fails(simple(descriptor="camt.054.001.08"), "neither camt.052 nor camt.053")

    def test_an_iso_document_is_not_read_yet(self) -> None:
        xml = '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt/></Document>'
        fails(xml, "not read yet")

    def test_an_unknown_root_is_named(self) -> None:
        fails("<Something/>", "'Something'")

    def test_not_well_formed(self) -> None:
        fails("<AccountMovementCamt><a></AccountMovementCamt>", "not well-formed")
        fails(b"", "not well-formed")

    @pytest.mark.parametrize(
        "doctype",
        [
            "<!DOCTYPE AccountMovementCamt>",
            '<!DOCTYPE AccountMovementCamt [<!ENTITY x "boom">]>',
        ],
    )
    def test_a_doctype_is_refused(self, doctype: str) -> None:
        fails(simple(doctype=doctype), "DOCTYPE")

    def test_a_doctype_is_refused_in_another_encoding(self) -> None:
        xml = '<?xml version="1.0" encoding="utf-16"?>' + simple(doctype="<!DOCTYPE a>")
        fails(xml.encode("utf-16"), "DOCTYPE")


class TestDates:
    @pytest.mark.parametrize(
        ("instant", "day"),
        [
            ("2026-05-28 22:00:00.0 UTC", D(2026, 5, 29)),  # summer time
            ("2026-10-29 23:00:00.0 UTC", D(2026, 10, 30)),  # after the clocks went back
            ("2026-03-27 23:00:00.0 UTC", D(2026, 3, 28)),  # the day before spring forward: UTC+1
            ("2026-03-29 22:00:00.0 UTC", D(2026, 3, 30)),  # the day after: UTC+2
            ("2026-10-24 22:00:00.0 UTC", D(2026, 10, 25)),  # the day before fall back: UTC+2
            ("2026-10-25 23:00:00.0 UTC", D(2026, 10, 26)),  # the day after: UTC+1
        ],
    )
    def test_a_berlin_midnight_is_that_day(self, instant: str, day: date) -> None:
        assert bank_day(instant, "x") == day

    @pytest.mark.parametrize(
        "instant",
        [
            "2026-05-28 21:00:00.0 UTC",  # 23:00 in Berlin
            "2026-05-28 23:00:00.0 UTC",  # 01:00 in Berlin
            "2026-05-28 22:00:01.0 UTC",
            "2026-05-28 22:00:00.5 UTC",
            "2026-05-28",
            "yesterday",
        ],
    )
    def test_anything_else_fails(self, instant: str) -> None:
        with pytest.raises(ParseFailed):
            bank_day(instant, "x")

    def test_the_builder_agrees_with_the_reader(self) -> None:
        assert bank_day(utc("2026-03-29"), "x") == D(2026, 3, 29)

    def test_a_non_midnight_date_in_a_file_fails_the_read(self) -> None:
        bad = entry("1.00", "CREDIT", "2026-08-11").replace(utc("2026-08-11"), "2026-08-10 21:00:00.0 UTC")
        fails(simple((bad,)), "not a midnight")

    def test_the_export_date_is_the_latest_creation_date(self) -> None:
        bal = (balance("OPBD", "1", "CREDIT", "2026-08-10"), balance("CLBD", "1", "CREDIT", "2026-08-10"))
        xml = document(
            (
                report("A", bal, created="2026-08-18"),
                report("B", bal, created="2026-08-20"),
                report("C", bal, created=None),
            )
        )
        assert read_statement(xml.encode()).export_date == D(2026, 8, 20)

    def test_no_creation_date_is_none(self) -> None:
        bal = (balance("OPBD", "1", "CREDIT", "2026-08-10"), balance("CLBD", "1", "CREDIT", "2026-08-10"))
        assert read_statement(document((report("A", bal, created=None),)).encode()).export_date is None


class TestEntries:
    def test_fields_of_an_entry(self) -> None:
        e = entry(
            "12.5",
            "DEBIT",
            "2026-08-11",
            value="2026-08-12",
            details=(detail(mandate="MND1", e2e="E2E1", lines=("A", "B")),),
        )
        s = read_statement(simple((e,)).encode())
        got = s.reports[0].entries[0]
        assert (got.amount, got.currency, got.credit) == (12.5, "EUR", False)
        assert (got.booked_on, got.value_on) == (D(2026, 8, 11), D(2026, 8, 12))
        d = got.details[0]
        assert (d.name, d.account, d.agent) == ("ACME GMBH", "DE89370400440532013000", "COBADEFFXXX")
        assert (d.end_to_end_id, d.mandate_id, d.remittance) == ("E2E1", "MND1", ("A", "B"))
        assert d.codes == ("PMNT-IDDT-ESDD", "NDDT+171+0000000+000")
        assert got.xml.startswith("<") and "outer-class" in got.xml and "<value>12.5</value>" in got.xml

    def test_the_value_date_may_be_absent(self) -> None:
        s = read_statement(simple((entry("1", "CREDIT", "2026-08-11"),)).encode())
        assert s.reports[0].entries[0].value_on is None

    def test_balances_are_found_by_code(self) -> None:
        r = read_statement(simple().encode()).reports[0]
        assert r.opening is not None and r.closing is not None
        assert (r.opening.credit, r.opening.on) == (True, D(2026, 8, 10))

    def test_a_non_booked_status_in_a_booked_report_fails(self) -> None:
        fails(simple((entry("1", "CREDIT", "2026-08-11", status="PDNG"),)), "not BOOK")
        fails(simple((entry("1", "CREDIT", "2026-08-11", status=None),)), "not BOOK")

    def test_pending_entries_are_counted(self) -> None:
        pending = (
            entry("1", "CREDIT", "2026-08-19", status="PDNG"),
            entry("2", "DEBIT", "2026-08-19", status="PDNG"),
        )
        assert read_statement(simple(pending=pending).encode()).pending == 2

    def test_several_details_are_all_read(self) -> None:
        e = entry("3", "DEBIT", "2026-08-11", details=(detail(lines=("a",)), detail(lines=("b",))))
        assert len(read_statement(simple((e,)).encode()).reports[0].entries[0].details) == 2

    def test_a_credit_mark_that_is_neither_fails(self) -> None:
        fails(simple((entry("1", "CRDT", "2026-08-11"),)), "credDebtIndex")

    def test_an_amount_that_does_not_parse_fails(self) -> None:
        fails(simple((entry("abc", "CREDIT", "2026-08-11"),)), "does not parse")

    def test_a_report_without_a_message_id_fails(self) -> None:
        xml = simple().replace("<messageId>MSG1</messageId>", "")
        fails(xml, "messageId")
