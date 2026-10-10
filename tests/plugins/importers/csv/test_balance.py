from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.core.plugins.errors import ParseFailed
from tests.plugins.importers.csv.helpers import run

D = date

EXPORT = {"label": "Exportdatum", "below": 1, "format": "dd.MM.yyyy HH:mm:ss"}


def labelled(**over: Any) -> dict[str, Any]:
    b: dict[str, Any] = {
        "mode": "labelled",
        "label": "Saldo",
        "below": 1,
        "date": {"format": "dd.MM.yyyy", "right": 2, "below": 1},
    }
    b.update(over)
    return b


def file(figure_date: str = "20.08.2026", extra_rows: str = "", figure: str = "1.000,00") -> str:
    return (
        "Titel\n"
        "Exportdatum;Konto\n"
        "20.08.2026 10:00:00;X\n"
        "\n"
        "Saldo;Whrg;Datum\n"
        f"{figure};EUR;{figure_date}\n"
        "\n"
        "Datum;Betrag;Zweck\n"
        "20.08.2026;-10,00;a\n"
        "19.08.2026;-5,00;b\n"
        "18.08.2026;3,00;c\n" + extra_rows
    )


def prof(**over: Any) -> dict[str, Any]:
    from tests.plugins.importers.csv.helpers import base_profile

    return base_profile(**{"balance": labelled(), "export_date": EXPORT, **over})


def test_figure_dated_on_export_day_is_rolled_back_to_the_closed_day() -> None:
    pf = run(file(), profile=prof(), today=D(2030, 1, 1))
    # closed day = 19.08; booked rows after it: -10,00 -> figure less their sum
    assert pf.balance_on == D(2026, 8, 19)
    assert pf.reported_balance == 100000 + 1000
    r = pf.report
    assert r.export_date == D(2026, 8, 20) and "Exportdatum" in (r.export_date_source or "")
    assert r.balance is not None
    assert (r.balance.figure_minor, r.balance.figure_on) == (100000, D(2026, 8, 20))
    assert (r.balance.rolled_back_by_minor, r.balance.rolled_back_rows) == (-1000, 1)
    assert "Saldo" in r.balance.source


def test_roll_back_excludes_filtered_and_pending_rows() -> None:
    extra = "20.08.2026;-50,00;pending\n21.08.2026;-7,00;pending\n"
    pf = run(
        file(extra_rows=extra),
        profile=prof(filters=[{"column": "Zweck", "equals": "pending"}]),
    )
    assert pf.reported_balance == 101000  # only the -10,00 is rolled back


def test_roll_back_ignores_zero_bookings_and_uses_ledger_sign() -> None:
    pf = run(file(extra_rows="20.08.2026;0,00;z\n"), profile=prof())
    assert pf.reported_balance == 101000
    assert pf.importer_stats["filtered"] == 1


def test_figure_before_the_closed_day_is_used_at_its_own_date() -> None:
    pf = run(file(figure_date="17.08.2026"), profile=prof())
    assert (pf.reported_balance, pf.balance_on) == (100000, D(2026, 8, 17))
    assert pf.report.balance is not None and pf.report.balance.rolled_back_rows == 0


def test_figure_on_the_closed_day_is_used_as_is() -> None:
    pf = run(file(figure_date="19.08.2026"), profile=prof())
    assert (pf.reported_balance, pf.balance_on) == (100000, D(2026, 8, 19))


def test_export_date_falls_back_to_today() -> None:
    p = prof()
    del p["export_date"]
    pf = run(file(figure_date="20.08.2026"), profile=p, today=D(2026, 8, 20))
    assert pf.balance_on == D(2026, 8, 19)
    assert pf.report.export_date == D(2026, 8, 20)
    assert "upload date" in (pf.report.export_date_source or "")
    pf2 = run(file(figure_date="20.08.2026"), profile=p, today=D(2026, 8, 25))
    assert (pf2.reported_balance, pf2.balance_on) == (100000, D(2026, 8, 20))  # on/before closed day


def test_export_date_label_missing_fails_naming_it() -> None:
    p = prof(export_date={**EXPORT, "label": "Nirgends"})
    with pytest.raises(ParseFailed, match="Nirgends"):
        run(file(), profile=p)


def test_export_date_that_does_not_parse_fails() -> None:
    p = prof(export_date={**EXPORT, "format": "yyyy-MM-dd"})
    with pytest.raises(ParseFailed, match="export_date"):
        run(file(), profile=p)


def test_label_not_found_fails_naming_the_label() -> None:
    p = prof(balance=labelled(label="Kontostand"))
    with pytest.raises(ParseFailed, match="Kontostand") as ei:
        run(file(), profile=p)
    assert ei.value.report is not None and ei.value.report.failure


def test_value_that_does_not_parse_fails_naming_the_label() -> None:
    with pytest.raises(ParseFailed, match="Saldo"):
        run(file(figure="viel"), profile=prof())


def test_date_that_does_not_parse_fails() -> None:
    with pytest.raises(ParseFailed, match="Saldo"):
        run(file(figure_date="gestern"), profile=prof())


def test_whole_cell_match_beats_an_earlier_contains_match() -> None:
    text = "Währung für Saldo;x\n9.999,00;y\nSaldo;z\n100,00;EUR\nDatum;Betrag\n01.08.2026;1,00\n"
    pf = run(
        text,
        profile=prof(
            balance={"mode": "labelled", "label": "Saldo", "below": 1, "date": None},
            export_date=None,
            purpose=[],
        ),
        today=D(2026, 8, 2),
    )
    assert pf.reported_balance == 10000 - 0  # no rows after the closed day (4.8)
    assert pf.report.balance is not None and pf.report.balance.figure_minor == 10000


def test_contains_match_when_no_whole_cell_and_first_in_file_order() -> None:
    text = "Kontosaldo alt;x\n1,00;y\nKontosaldo neu;x\n2,00;y\nDatum;Betrag\n01.08.2026;1,00\n"
    pf = run(
        text,
        profile=prof(
            balance={"mode": "labelled", "label": "Kontosaldo", "below": 1, "date": None},
            export_date=None,
            purpose=[],
        ),
        today=D(2026, 8, 2),
    )
    assert pf.report.balance is not None and pf.report.balance.figure_minor == 100


CARD = (
    "Titel\n"
    "Abrechnungsdatum: 3.8.2026\n"
    "\n"
    "Belegdatum;Eingangstag;Zweck;Betrag\n"
    "1.8.2026;2.8.2026;Shop;-12,00\n"
    "2.8.2026;3.8.2026;Shop;-30,01\n"
    "Saldo:;;;-42,01;EUR\n"
)


def card_profile(**over: Any) -> dict[str, Any]:
    p: dict[str, Any] = {
        "label": "card",
        "delimiter": ";",
        "header_marker": ["Belegdatum", "Eingangstag"],
        "booked_on": "Eingangstag",
        "value_on": "Belegdatum",
        "date_format": "d.M.yyyy",
        "amount": {"column": "Betrag"},
        "purpose": ["Zweck"],
        "balance": {
            "mode": "labelled",
            "label": "Saldo:",
            "right": 3,
            "date": {
                "format": "d.M.yyyy",
                "label": "Abrechnungsdatum",
                "pattern": r"(\d{1,2}\.\d{1,2}\.\d{4})",
            },
        },
        "coverage_end": {
            "format": "d.M.yyyy",
            "label": "Abrechnungsdatum",
            "pattern": r"(\d{1,2}\.\d{1,2}\.\d{4})",
        },
    }
    p.update(over)
    return p


def test_footer_figure_offset_right_pattern_date_and_stated_coverage() -> None:
    pf = run(CARD, profile=card_profile(), today=D(2026, 8, 10))
    assert (pf.reported_balance, pf.balance_on) == (-4201, D(2026, 8, 3))
    assert pf.covered_through == D(2026, 8, 3)
    assert pf.report.coverage_source is not None and "stated" in pf.report.coverage_source


def test_invert_balance_and_invert_amounts_are_independent() -> None:
    pf = run(CARD, profile=card_profile(invert_balance=True), today=D(2026, 8, 10))
    assert pf.reported_balance == 4201
    assert [r.amount_minor for r in pf.rows] == [-1200, -3001]
    pf = run(CARD, profile=card_profile(invert_amounts=True), today=D(2026, 8, 10))
    assert pf.reported_balance == -4201
    assert [r.amount_minor for r in pf.rows] == [1200, 3001]


def test_rows_after_a_stated_end_are_kept_and_coverage_stays() -> None:
    text = CARD.replace("Saldo:", "5.8.2026;5.8.2026;Late;-1,00\nSaldo:")
    pf = run(text, profile=card_profile(), today=D(2026, 8, 10))
    assert len(pf.rows) == 3
    assert pf.covered_through == D(2026, 8, 3)


def test_stated_end_with_no_rows_still_covers() -> None:
    text = "Abrechnungsdatum: 3.8.2026\nBelegdatum;Eingangstag;Zweck;Betrag\n"
    pf = run(text, profile=card_profile(balance=None))
    assert pf.rows == () and pf.covered_through == D(2026, 8, 3) and pf.data_start is None


def test_stated_end_label_missing_fails() -> None:
    with pytest.raises(ParseFailed, match="coverage_end"):
        run(CARD.replace("Abrechnungsdatum", "Stichtag"), profile=card_profile(balance=None))


def test_balance_date_never_later_than_coverage() -> None:
    # export 22.08 -> closed 21.08; the figure is dated 20.08 (<= closed) but the last booking is 18.08
    text = file(figure_date="20.08.2026").replace("20.08.2026;-10,00;a\n", "")
    p = prof()
    del p["export_date"]
    pf = run(text, profile=p, today=D(2026, 8, 22))
    assert pf.reported_balance is None and pf.balance_on is None
    assert pf.covered_through == D(2026, 8, 19)
    assert any("balance" in w for w in pf.report.warnings)


RUNNING = "Datum;Betrag;Saldo\n{rows}"


def running_profile(**over: Any) -> dict[str, Any]:
    from tests.plugins.importers.csv.helpers import base_profile

    return base_profile(**{"purpose": [], "balance": {"mode": "running_column", "column": "Saldo"}, **over})


DESC = "20.08.2026;-10,00;890,00\n19.08.2026;-5,00;900,00\n18.08.2026;3,00;905,00\n17.08.2026;2,00;902,00\n"


def test_running_balance_descending_file_takes_last_row_by_date_not_position() -> None:
    pf = run(RUNNING.format(rows=DESC), profile=running_profile(), today=D(2026, 8, 20))
    # closed day 19.08: the row dated 19.08 closes it, wherever it sits in the file
    assert (pf.reported_balance, pf.balance_on) == (90000, D(2026, 8, 19))
    assert pf.report.balance is not None and pf.report.balance.rolled_back_rows == 0


def test_running_balance_ascending_file_same_result() -> None:
    asc = "".join(reversed(DESC.splitlines(keepends=True)))
    pf = run(RUNNING.format(rows=asc), profile=running_profile(), today=D(2026, 8, 20))
    assert (pf.reported_balance, pf.balance_on) == (90000, D(2026, 8, 19))


def test_running_balance_dated_at_the_row_when_earlier_than_closed_day() -> None:
    pf = run(RUNNING.format(rows=DESC), profile=running_profile(), today=D(2026, 8, 25))
    assert (pf.reported_balance, pf.balance_on) == (89000, D(2026, 8, 20))
    pf = run(RUNNING.format(rows="18.08.2026;3,00;905,00\n"), profile=running_profile(), today=D(2026, 8, 25))
    assert pf.balance_on == D(2026, 8, 18)


def test_running_balance_same_day_rows_use_the_end_of_day_row_by_file_direction() -> None:
    desc = "19.08.2026;-1,00;98,00\n19.08.2026;-2,00;99,00\n18.08.2026;1,00;101,00\n"
    pf = run(RUNNING.format(rows=desc), profile=running_profile(), today=D(2026, 8, 20))
    assert pf.reported_balance == 9800  # newest-first: the first row of the day is the last booked
    asc = "18.08.2026;1,00;101,00\n19.08.2026;-2,00;99,00\n19.08.2026;-1,00;98,00\n"
    pf = run(RUNNING.format(rows=asc), profile=running_profile(), today=D(2026, 8, 20))
    assert pf.reported_balance == 9800


def test_running_balance_no_row_on_or_before_closed_day_reports_none() -> None:
    pf = run(
        RUNNING.format(rows="20.08.2026;-10,00;890,00\n"), profile=running_profile(), today=D(2026, 8, 20)
    )
    assert pf.reported_balance is None
    assert any("balance" in w for w in pf.report.warnings)


def test_running_balance_unparseable_value_fails_naming_the_column() -> None:
    with pytest.raises(ParseFailed, match="Saldo"):
        run(RUNNING.format(rows="18.08.2026;3,00;viel\n"), profile=running_profile(), today=D(2026, 8, 25))


def test_running_balance_respects_invert_balance() -> None:
    pf = run(
        RUNNING.format(rows="18.08.2026;3,00;905,00\n"),
        profile=running_profile(invert_balance=True),
        today=D(2026, 8, 25),
    )
    assert pf.reported_balance == -90500


def test_no_balance_profile_reports_none() -> None:
    from tests.plugins.importers.csv.helpers import base_profile

    pf = run("Datum;Betrag\n18.08.2026;3,00\n", profile=base_profile(purpose=[]))
    assert pf.reported_balance is None and pf.balance_on is None and pf.report.balance is None
