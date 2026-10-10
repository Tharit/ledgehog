"""Bytes to records: decoding, delimiter detection, tokenising, the header row (csv.md §2)."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from app.core.plugins.errors import ParseFailed

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
    delimiter: str
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


def read_file(
    data: bytes, *, encoding: str | None, delimiter: str | None, quote: str, markers: Sequence[str]
) -> ReadFile:
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
