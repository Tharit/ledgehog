from __future__ import annotations

from datetime import date

import pytest

from app.plugins.importers.csv import CsvImporter, load_presets
from tests.plugins.importers.csv.fixtures import LONG_PURPOSE, PRIVATE, card_a_bytes, card_b_bytes, giro_bytes
from tests.plugins.importers.csv.helpers import run

NAMES = ["giro_with_preamble", "card_footer_balance", "card_inverted_signs"]


def test_presets_are_loaded_by_neutral_name_and_validate() -> None:
    presets = load_presets()
    assert sorted(presets) == sorted(NAMES)
    for settings in presets.values():
        CsvImporter().validate_settings(settings)


def test_presets_carry_no_account_details() -> None:
    blob = repr(load_presets())
    assert "DE00" not in blob and PRIVATE not in blob


def test_load_presets_returns_independent_copies() -> None:
    a = load_presets()
    a["giro_with_preamble"]["quote"] = "changed"
    assert load_presets()["giro_with_preamble"]["quote"] != "changed"


def giro(**kw: object) -> object:
    return run(
        giro_bytes(**kw), profile=load_presets()["giro_with_preamble"], today=date(2030, 1, 1), name="giro"
    )  # type: ignore[arg-type]


def test_giro_rows_pending_placeholders_and_zero() -> None:
    pf = giro()
    assert [r.amount_minor for r in pf.rows] == [-1000, 150000, -4550]
    first = pf.rows[0]
    assert first.booked_on == date(2026, 8, 20) and first.value_on == date(2026, 8, 20)
    assert first.counterparty_name == "Beispiel Markt"
    assert first.counterparty_ref == "DE00 2222 2222 2222 2222 22"
    assert first.counterparty_bic is None  # n/a placeholder
    assert first.purpose == f"Lastschrift {LONG_PURPOSE}"
    assert first.source_format == "csv:giro"
    assert pf.importer_stats["filtered"] == 1  # the zero booking only, not the pending row
    assert pf.report.filtered.count == 1


def test_giro_export_date_from_the_file_balance_rolled_back_and_coverage() -> None:
    pf = giro()
    assert pf.report.export_date == date(2026, 8, 20)
    assert pf.covered_through == date(2026, 8, 20) and pf.data_start == date(2026, 8, 18)
    # the figure 1.234,56 is dated the export day: rolled back to the 19th by the -10,00 booked on the 20th
    assert (pf.reported_balance, pf.balance_on) == (124456, date(2026, 8, 19))
    assert pf.importer_stats["synthetic_skipped"] == 0 and pf.report.synthetic is None


@pytest.mark.parametrize("kw", [{"crlf": True}, {"trailing_newline": True}, {"extra_preamble": 2}])
def test_giro_survives_crlf_trailing_newline_and_a_longer_preamble(kw: dict[str, object]) -> None:
    assert giro(**kw).rows == giro().rows
    assert giro(**kw).reported_balance == 124456


def test_card_a() -> None:
    pf = run(card_a_bytes(), profile=load_presets()["card_footer_balance"], today=date(2026, 8, 10))
    assert [r.amount_minor for r in pf.rows[:3]] == [-1200, -909, -3001]
    ticket = pf.rows[1]
    assert (ticket.instructed_amount_minor, ticket.instructed_currency) == (-1000, "USD")
    assert pf.rows[0].instructed_amount_minor is None  # Fremdwährung = EUR: ignored
    assert pf.rows[0].value_on == date(2026, 8, 1) and pf.rows[0].booked_on == date(2026, 8, 2)
    assert pf.covered_through == date(2026, 8, 3)
    assert (pf.reported_balance, pf.balance_on) == (-5110, date(2026, 8, 3))
    synth = pf.rows[-1]
    assert synth.source_format == "csv:synthetic" and synth.amount_minor == 5110
    assert synth.booked_on == date(2026, 8, 7)
    assert len(pf.rows) == 4


def test_card_b() -> None:
    pf = run(card_b_bytes(), profile=load_presets()["card_inverted_signs"], today=date(2026, 8, 10))
    assert [r.amount_minor for r in pf.rows] == [-1250, 10000, -123456]
    assert pf.rows[0].purpose == "BEISPIEL SHOP"
    assert pf.reported_balance is None and pf.balance_on is None
    assert pf.covered_through == date(2026, 8, 7) and pf.data_start == date(2026, 8, 5)
    assert pf.importer_stats["synthetic_skipped"] == 0 and len(pf.rows) == 3
    assert pf.report.delimiter == ","
    assert pf.report.encoding == "utf-8"
    assert pf.rows[0].raw["cells"][5] == "Musterstr. 1\n12345 Musterstadt"


def test_reports_never_hold_preamble_content_or_untruncated_cells() -> None:
    for name, data in (
        ("giro_with_preamble", giro_bytes()),
        ("card_footer_balance", card_a_bytes()),
        ("card_inverted_signs", card_b_bytes()),
    ):
        pf = run(data, profile=load_presets()[name], today=date(2026, 8, 10))
        blob = repr(pf.report)
        assert PRIVATE not in blob and "DE00 0000" not in blob and "Kundennummer" not in blob
        assert LONG_PURPOSE not in blob
        for s in pf.report.sample:
            assert all(len(c) <= 24 for c in s.cells)


def test_failure_reports_hold_no_preamble_either() -> None:
    from app.core.plugins.errors import ParseFailed

    profile = load_presets()["giro_with_preamble"]
    profile["balance"]["label"] = "Kontostand Nirgends"
    with pytest.raises(ParseFailed, match="Nirgends") as ei:
        run(giro_bytes(), profile=profile, today=date(2026, 8, 10))
    assert PRIVATE not in str(ei.value) and PRIVATE not in repr(ei.value.report)
