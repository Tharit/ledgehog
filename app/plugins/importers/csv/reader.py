"""Bytes to records: decoding, delimiter detection, tokenising, the header row (csv.md §2)."""

from __future__ import annotations

import csv
import importlib
import io
import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.core.plugins.errors import ParseFailed
from app.plugins.importers.csv.cells import DateCell, NumberCell

_CANDIDATES = (";", ",", "\t", "|")


@dataclass(frozen=True, slots=True)
class Record:
    """One logical record. `line` is the line it starts on (1-based); `text` is its original text."""

    line: int
    cells: list[str]
    text: str


@dataclass(frozen=True, slots=True)
class ReadFile:
    encoding: str
    delimiter: str | None  # None for a spreadsheet
    records: list[Record]  # the whole file, preamble and footer included
    header_index: int
    header: list[str]


def _clean(cell: str) -> str:
    return cell.replace("﻿", "").strip()


def decode(data: bytes, encoding: str | None) -> tuple[str, str]:
    """Return (text, encoding used). A byte-order mark decides; else UTF-8; else cp1252."""
    try:
        if encoding is not None:
            name = "utf-8-sig" if encoding.lower().replace("_", "-") in ("utf-8", "utf8") else encoding
            return data.decode(name), name
        if data.startswith(b"\xef\xbb\xbf"):
            return data.decode("utf-8-sig"), "utf-8-sig"
        try:
            return data.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            return data.decode("cp1252"), "cp1252"
    except UnicodeDecodeError as exc:
        raise ParseFailed(f"the file cannot be decoded as {encoding or 'UTF-8 or cp1252'}") from exc


class _Lines:
    """Feeds `csv.reader` while remembering which physical lines made up each record."""

    def __init__(self, text: str) -> None:
        self._it = iter(io.StringIO(text, newline=""))
        self.buf: list[str] = []

    def __iter__(self) -> Iterator[str]:
        return self

    def __next__(self) -> str:
        line = next(self._it)
        self.buf.append(line)
        return line


def _tokenise(text: str, delimiter: str, quote: str) -> list[Record]:
    lines = _Lines(text)
    reader = csv.reader(lines, delimiter=delimiter, quotechar=quote)
    records: list[Record] = []
    try:
        for cells in reader:
            joined = "".join(lines.buf)
            start = reader.line_num - len(lines.buf) + 1
            lines.buf.clear()
            records.append(Record(start, cells, joined.rstrip("\r\n")))
    except csv.Error as exc:
        raise ParseFailed(f"the file cannot be tokenised ({exc})") from exc
    return records


def _is_header(cells: Sequence[str], markers: Sequence[str]) -> bool:
    cleaned = {_clean(c) for c in cells}
    return all(m.strip() in cleaned for m in markers)


def _detect_delimiter(text: str, quote: str, markers: Sequence[str]) -> str | None:
    """Score candidates on the header-marker line only: the number of cells it splits into."""
    best: tuple[int, str] | None = None
    for cand in _CANDIDATES:
        if cand == quote:
            continue
        for line in text.splitlines():
            try:
                cells = next(csv.reader([line], delimiter=cand, quotechar=quote), [])
            except csv.Error:
                continue
            if _is_header(cells, markers):
                if best is None or len(cells) > best[0]:
                    best = (len(cells), cand)
                break
    return None if best is None else best[1]


_ZIP = b"PK\x03\x04"  # xlsx and ods are zip containers
_OLE2 = b"\xd0\xcf\x11\xe0"  # xls (BIFF in an OLE2 compound file)


def is_spreadsheet(data: bytes) -> bool:
    """Whether the first bytes are those of an `.xls`, `.xlsx` or `.ods` file (csv.md §2)."""
    return data.startswith((_ZIP, _OLE2))


def _typed(value: object) -> str:
    """One sheet cell as a cell: a stored date or number keeps its value, anything else is its text."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime):
        return DateCell(value.date())
    if isinstance(value, date):
        return DateCell(value)
    if isinstance(value, int):
        return NumberCell(Decimal(value))
    if isinstance(value, float):
        # 15 significant digits, as a spreadsheet itself shows a number: floating-point noise
        # (0.30000000000000004 -> 0.3) disappears, real excess precision (12.345 in EUR) remains
        return NumberCell(Decimal(format(value, ".15g"))) if math.isfinite(value) else repr(value)
    return str(value)


def _read_sheet(data: bytes, markers: Sequence[str]) -> ReadFile:
    """The first sheet as records: one per sheet row, `line` the row number counted from 1."""
    try:
        calamine = importlib.import_module("python_calamine")
        book = calamine.CalamineWorkbook.from_filelike(io.BytesIO(data))
        if not book.sheet_names:
            raise ParseFailed("the spreadsheet has no sheet")
        rows = book.get_sheet_by_index(0).to_python(skip_empty_area=False)
    except ParseFailed:
        raise
    except Exception as exc:  # the library raises its own error types, and others on a damaged file
        raise ParseFailed("the file cannot be read as a spreadsheet (corrupt or unsupported)") from exc
    records: list[Record] = []
    for n, row in enumerate(rows, start=1):
        cells = [_typed(v) for v in row]
        records.append(Record(n, cells, "\t".join(str(c) for c in cells).rstrip("\t")))
    for i, rec in enumerate(records):
        if _is_header(rec.cells, markers):
            return ReadFile("spreadsheet", None, records, i, [_clean(c) for c in rec.cells])
    raise ParseFailed(f"no header row found: no row contains all of {list(markers)}")


def read_file(
    data: bytes, *, encoding: str | None, delimiter: str | None, quote: str, markers: Sequence[str]
) -> ReadFile:
    if is_spreadsheet(data):
        return _read_sheet(data, markers)
    text, used = decode(data, encoding)
    delim = delimiter if delimiter is not None else _detect_delimiter(text, quote, markers)
    if delim is None:
        raise ParseFailed(f"no header row found: no row contains all of {list(markers)}")
    records = _tokenise(text, delim, quote)
    for i, rec in enumerate(records):
        if _is_header(rec.cells, markers):
            return ReadFile(used, delim, records, i, [_clean(c) for c in rec.cells])
    raise ParseFailed(f"no header row found: no row contains all of {list(markers)}")


def resolve_column(header: Sequence[str], ref: str | int, setting: str) -> int:
    """Index of the column `ref` names: a header name, `Name#2` (nth of that name) or a 1-based position."""
    if isinstance(ref, int):
        if 1 <= ref <= len(header):
            return ref - 1
        raise ParseFailed(f"{setting}: column position {ref} is outside the header's {len(header)} columns")
    wanted = ref.strip()
    if wanted in header:
        return list(header).index(wanted)
    name, sep, nth = wanted.rpartition("#")
    if sep and nth.isdigit() and int(nth) >= 1:
        hits = [i for i, h in enumerate(header) if h == name.strip()]
        if int(nth) <= len(hits):
            return hits[int(nth) - 1]
    raise ParseFailed(f"{setting}: no column {ref!r} in the header")
