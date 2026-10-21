"""A minimal `.xlsx` writer for the spreadsheet tests. An xlsx is a zip of XML parts; this writes
only what a reader needs: inline strings, numbers, and dates (a serial number with a date style).
All data a test puts in is synthetic."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Sequence
from datetime import date
from xml.sax.saxutils import escape

Cell = str | int | float | date | None

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_EPOCH = date(1899, 12, 30)
_DATE_STYLE = 1  # cellXfs[1] is the built-in short date format (numFmtId 14)


def _col(i: int) -> str:
    return chr(ord("A") + i)


def _cell(row: int, col: int, value: Cell) -> str:
    ref = f"{_col(col)}{row}"
    if value is None:
        return ""
    if isinstance(value, str):
        return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(value)}</t></is></c>'
    if isinstance(value, date):
        return f'<c r="{ref}" s="{_DATE_STYLE}"><v>{(value - _EPOCH).days}</v></c>'
    return f'<c r="{ref}"><v>{value!r}</v></c>'


def _sheet(rows: Sequence[Sequence[Cell]]) -> str:
    body = "".join(
        f'<row r="{n}">{"".join(_cell(n, c, v) for c, v in enumerate(row))}</row>'
        for n, row in enumerate(rows, start=1)
    )
    head = f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{_NS}">'
    return f"{head}<sheetData>{body}</sheetData></worksheet>"


def xlsx_bytes(*sheets: Sequence[Sequence[Cell]]) -> bytes:
    """A workbook with one worksheet per argument; each is a list of rows of cells (None = empty)."""
    names = [f"Sheet{i}" for i in range(1, len(sheets) + 1)]
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        + "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        + "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{_REL_NS}/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    workbook = (
        f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="{_NS}" xmlns:r="{_REL_NS}"><sheets>'
        + "".join(f'<sheet name="{n}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(names, start=1))
        + "</sheets></workbook>"
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{i}" Type="{_REL_NS}/worksheet" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        + f'<Relationship Id="rId{len(sheets) + 1}" Type="{_REL_NS}/styles" Target="styles.xml"/>'
        "</Relationships>"
    )
    styles = (
        f'<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="{_NS}">'
        '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>'
        "</styleSheet>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        z.writestr("xl/styles.xml", styles)
        for i, rows in enumerate(sheets, start=1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet(rows))
    return buf.getvalue()
