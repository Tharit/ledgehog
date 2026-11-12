"""CamtImporter end to end over hand-built OLB files: settings, records, dry run, failures."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.plugins.errors import InvalidProfile, ParseFailed
from app.core.plugins.importer import FileImporter
from app.plugins.importers.camt import CamtImporter
from tests.plugins.importers.camt.builders import (
    balance,
    detail,
    document,
    entry,
    report,
    run,
    simple,
)

D = date


class TestSettings:
    def test_it_is_a_file_importer(self) -> None:
        assert isinstance(CamtImporter(), FileImporter)

    def test_empty_settings_are_accepted(self) -> None:
        CamtImporter().validate_settings({})

    def test_any_setting_is_refused_by_name(self) -> None:
        with pytest.raises(InvalidProfile, match="delimiter"):
            CamtImporter().validate_settings({"delimiter": ";"})

    def test_parse_refuses_settings_too(self) -> None:
        with pytest.raises(InvalidProfile):
            CamtImporter().parse(
                simple().encode(),
                {"x": 1},
                account_currency="EUR",
                minor_units_of=lambda c: 2,
                today=D(2026, 8, 20),
                name="t",
            )


def test_a_file_end_to_end() -> None:
    entries = (
        entry(
            "110.10",
            "DEBIT",
            "2026-08-11",
            value="2026-08-12",
            details=(detail(name="ZINSEN", account=None, agent=None),),
        ),
        entry(
            "585",
            "CREDIT",
            "2026-08-12",
            details=(detail(mandate="MND-1", lines=("DARL-ABR 05/2026", "ZINS       110", ",10- ENTGELT")),),
        ),
        entry("0.00", "CREDIT", "2026-08-12"),
    )
    xml = document(
        (
            report(
                "MSG9",
                (
                    balance("OPBD", "194302.28", "DEBIT", "2026-08-10"),
                    balance("CLBD", "193827.38", "DEBIT", "2026-08-12"),
                ),
                entries,
            ),
        ),
        pending=(entry("5", "DEBIT", "2026-08-19", status="PDNG"),),
    )
    p = run(xml)
    assert [(r.amount_minor, r.booked_on, r.value_on) for r in p.rows] == [
        (-11010, D(2026, 8, 11), D(2026, 8, 12)),
        (58500, D(2026, 8, 12), None),
    ]
    assert p.rows[0].counterparty_name == "ZINSEN" and p.rows[0].counterparty_ref is None
    assert p.rows[1].purpose == "DARL-ABR 05/2026 ZINS 110 ,10- ENTGELT"
    assert p.rows[1].end_to_end_id is None and p.rows[1].mandate_ref == "MND-1"
    assert (p.reported_balance, p.balance_on, p.covered_through) == (
        -19382738,
        D(2026, 8, 12),
        D(2026, 8, 12),
    )
    assert p.data_start == D(2026, 8, 11) and dict(p.importer_stats) == {"filtered": 1}
    r = p.report
    assert (r.rows_read, r.emitted, r.zero_dropped.count, r.filtered.count) == (4, 2, 1, 1)
    assert (r.header_line, r.encoding, r.delimiter, r.columns) == (None, None, None, ())
    assert r.export_date == D(2026, 8, 20) and r.coverage == D(2026, 8, 12)
    assert any("camt.052" in w for w in r.warnings)
    assert [s.row for s in r.sample] == [1, 2]


def test_a_failure_carries_the_report_with_what_was_counted() -> None:
    bad = simple((entry("1", "CREDIT", "2026-08-11"),), closing="9")
    with pytest.raises(ParseFailed) as err:
        run(bad)
    rep = err.value.report
    assert rep is not None and rep.failure == str(err.value) and "MSG1" in rep.failure
    assert any("camt.052" in w for w in rep.warnings)


def test_a_reader_failure_carries_a_report_too() -> None:
    with pytest.raises(ParseFailed) as err:
        run("<Document/>")
    assert err.value.report is not None and "not read yet" in (err.value.report.failure or "")


def test_an_unknown_currency_is_a_parse_failure() -> None:
    def lookup(currency: str) -> int:
        raise KeyError(currency)

    with pytest.raises(ParseFailed, match="unknown currency"):
        run(simple((entry("1", "CREDIT", "2026-08-11"),), closing="101"), minor_units_of=lookup)


def test_an_entry_currency_other_than_the_accounts_is_reported() -> None:
    # balances in the account's currency, an entry in another: the per-report check refuses the mix
    xml = simple((entry("1", "CREDIT", "2026-08-11", currency="USD"),), closing="101")
    with pytest.raises(ParseFailed, match="one currency"):
        run(xml)


def test_a_whole_file_in_another_currency_fails_on_the_balance() -> None:
    xml = document(
        (
            report(
                "U",
                (
                    balance("OPBD", "1", "CREDIT", "2026-08-10", "USD"),
                    balance("CLBD", "2", "CREDIT", "2026-08-11", "USD"),
                ),
                (entry("1", "CREDIT", "2026-08-11", currency="USD"),),
            ),
        )
    )
    with pytest.raises(ParseFailed, match="account's currency") as err:
        run(xml)
    assert err.value.report is not None and err.value.report.currency_mismatch.count == 1
