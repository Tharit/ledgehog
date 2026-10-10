from __future__ import annotations

import pytest

from app.core.plugins.errors import ParseFailed
from app.plugins.importers.csv.reader import read_file, resolve_column

MARK = ("Datum", "Betrag")


def rd(data: bytes, **kw: object) -> object:
    args: dict[str, object] = {"encoding": None, "delimiter": None, "quote": '"', "markers": MARK}
    args.update(kw)
    return read_file(data, **args)  # type: ignore[arg-type]


def test_utf8_bom_is_stripped_and_decides_encoding() -> None:
    f = rd("﻿Datum;Betrag\n1;2\n".encode())
    assert f.encoding == "utf-8-sig"
    assert f.header == ["Datum", "Betrag"]


def test_utf8_without_bom() -> None:
    f = rd("Datum;Betrag;Zweck\n1;2;Bäckerei\n".encode())
    assert f.encoding == "utf-8"
    assert f.records[f.header_index + 1].cells[2] == "Bäckerei"


def test_cp1252_fallback() -> None:
    f = rd("Datum;Betrag;Zweck\n1;2;Bäckerei\n".encode("cp1252"))
    assert f.encoding == "cp1252"
    assert f.records[f.header_index + 1].cells[2] == "Bäckerei"


def test_profile_encoding_wins() -> None:
    f = rd("Datum;Betrag;Zweck\n1;2;ä\n".encode("latin-1"), encoding="latin-1")
    assert f.records[f.header_index + 1].cells[2] == "ä"


def test_undecodable_bytes_fail() -> None:
    with pytest.raises(ParseFailed, match="decode"):
        rd(b"Datum;Betrag\n1;\x81\xff\n")  # invalid UTF-8 and undefined in cp1252
    with pytest.raises(ParseFailed, match="decode"):
        rd(b"Datum;Betrag\n\xff\n", encoding="utf-8")


def test_delimiter_detected_on_header_not_whole_file() -> None:
    data = b'Datum,Betrag,Text\n01/01/2026,"-12,50",x\n01/01/2026,"-1,50",y\n'
    f = rd(data)
    assert f.delimiter == ","
    assert f.records[1].cells == ["01/01/2026", "-12,50", "x"]


def test_delimiter_semicolon_and_tab_and_override() -> None:
    assert rd(b"Datum;Betrag\n").delimiter == ";"
    assert rd(b"Datum\tBetrag\n").delimiter == "\t"
    f = rd(b"Datum|Betrag|x;y\n", delimiter="|")
    assert f.delimiter == "|"
    assert f.header == ["Datum", "Betrag", "x;y"]


def test_short_preamble_lines_do_not_fool_detection() -> None:
    data = b"Export, vom heute;;\n\nDatum;Betrag\n1;2\n"
    f = rd(data)
    assert f.delimiter == ";"
    assert f.header_index == 2


def test_header_not_on_line_one_and_growing_preamble() -> None:
    base = b"Titel\nKonto;Inhaber\nX;Y\n\nDatum;Betrag\n1;2\n"
    grown = b"Titel\nNoch eine\nZeile mehr\nKonto;Inhaber\nX;Y\n\nDatum;Betrag\n1;2\n"
    assert rd(base).records[rd(base).header_index].line == 5
    assert rd(grown).records[rd(grown).header_index].line == 7


def test_decoy_row_with_some_markers_is_not_the_header() -> None:
    f = rd(b"Datum;Info\nx;y\nDatum;Betrag\n1;2\n")
    assert f.records[f.header_index].line == 3


def test_header_cells_are_trimmed_with_trailing_space() -> None:
    f = rd("Buchung ;Valuta;Betrag\n".encode(), markers=("Buchung", "Betrag"))
    assert f.header == ["Buchung", "Valuta", "Betrag"]


def test_no_header_row_fails() -> None:
    with pytest.raises(ParseFailed, match="header"):
        rd(b"Datum;Info\n1;2\n")


def test_quoted_multiline_cell_is_one_record_with_original_text() -> None:
    data = b'Datum,Betrag,Adresse\r\n01/01/2026,"1,00","Zeile 1\r\nZeile 2"\r\n02/01/2026,"2,00",x\r\n'
    f = rd(data)
    rec = f.records[1]
    assert rec.cells[2] == "Zeile 1\r\nZeile 2"
    assert rec.line == 2
    assert rec.text == '01/01/2026,"1,00","Zeile 1\r\nZeile 2"'
    assert f.records[2].line == 4  # error rows refer to the logical record's first line


def test_crlf_and_missing_trailing_newline() -> None:
    f = rd(b"Datum;Betrag\r\n1;2\r\n3;4")
    assert [r.cells for r in f.records] == [["Datum", "Betrag"], ["1", "2"], ["3", "4"]]
    assert f.records[-1].text == "3;4"


def test_blank_lines_are_kept_as_empty_records() -> None:
    f = rd(b"Datum;Betrag\n\n1;2\n")
    assert f.records[1].cells == []


@pytest.mark.parametrize(
    ("ref", "idx"),
    [("Datum", 0), ("Betrag", 1), ("Betrag#1", 1), ("Betrag#2", 3), (3, 2), (1, 0), ("Zweck", 2)],
)
def test_resolve_column(ref: str | int, idx: int) -> None:
    assert resolve_column(["Datum", "Betrag", "Zweck", "Betrag"], ref, "amount") == idx


@pytest.mark.parametrize("ref", ["Nope", "Betrag#3", 5, "Datum#2"])
def test_resolve_column_missing_names_the_setting(ref: str | int) -> None:
    with pytest.raises(ParseFailed, match="amount"):
        resolve_column(["Datum", "Betrag", "Zweck", "Betrag"], ref, "amount")
