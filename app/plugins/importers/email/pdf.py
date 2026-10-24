"""A PDF as page images for the vision model (spec/plugins/importers/email.md §4).

The first four pages, rendered with pypdfium2 in grayscale at 150 DPI, scaled down so the longest side is at
most 2,000 px, as PNG (written here: no imaging library). pypdfium2 is imported where it is used.
"""

from __future__ import annotations

import struct
import zlib
from typing import Any

MAX_PAGES = 4
DPI = 150
MAX_SIDE = 2000  # px; the longest side after rendering


def render_scale(width_pt: float, height_pt: float) -> float:
    """pypdfium2's scale for a page of the given size in PDF points: 150 DPI, reduced so that the longest side
    is at most `MAX_SIDE`."""
    return min(DPI / 72, MAX_SIDE / max(width_pt, height_pt))


def png_bytes(width: int, height: int, rows: list[bytes]) -> bytes:
    """An 8-bit grayscale PNG of `height` rows of `width` bytes; filter 0 (none)."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    raw = b"".join(b"\x00" + row for row in rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _gray_rows(page: Any, scale: float) -> tuple[int, int, list[bytes]]:
    """(width, height, rows) of the rendered page. The one place that touches the pypdfium2 bitmap API."""
    bitmap = page.render(scale=scale, grayscale=True)
    try:
        if bitmap.n_channels != 1:
            raise ValueError("the page did not render in grayscale")
        data = bytes(bitmap.buffer)
        rows = [data[y * bitmap.stride : y * bitmap.stride + bitmap.width] for y in range(bitmap.height)]
        return bitmap.width, bitmap.height, rows
    finally:
        bitmap.close()


def render_pdf(data: bytes, limit: int = MAX_PAGES) -> list[bytes]:
    """PNG bytes of the first `limit` pages. Raises whatever pypdfium2 raises for a PDF it cannot open."""
    import pypdfium2

    pdf = pypdfium2.PdfDocument(data)
    try:
        images: list[bytes] = []
        for i in range(min(len(pdf), limit)):
            page = pdf[i]
            try:
                width_pt, height_pt = page.get_size()
                width, height, rows = _gray_rows(page, render_scale(width_pt, height_pt))
            finally:
                page.close()
            images.append(png_bytes(width, height, rows))
        return images
    finally:
        pdf.close()
