"""HTML to plain text for the model (spec/plugins/importers/email.md §4): drops presentation only.

`<head>`, `<script>`, `<style>` and comments are dropped; a table cell becomes a tab, a row or a block
element a line, a list item a line with `- `; an image is its `[alt]` text; other tags are dropped; entities
are decoded; whitespace runs collapse and empty cells and blank lines go. Superscript is marked `^` and
subscript `_`, so a price whose cents are only markup keeps the cue (`43<sup>55</sup>` is `43^55`).
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

DROP_CONTENT = frozenset({"head", "script", "style"})
BLOCKS = frozenset(
    {
        "p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "br", "hr", "table", "tr", "ul", "ol",
        "section", "article", "header", "footer", "blockquote", "center", "dl", "dt", "dd", "pre",
        "address", "main", "nav",
    }
)  # fmt: skip


class _TextConverter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0  # depth inside a dropped element

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in DROP_CONTENT:
            self.skip += 1
        elif not self.skip:
            if tag in ("td", "th"):
                self.out.append("\t")
            elif tag in BLOCKS:
                self.out.append("\n- " if tag == "li" else "\n")
            elif tag in ("sup", "sub"):
                self.out.append("^" if tag == "sup" else "_")
            elif tag == "img":
                alt = dict(attrs).get("alt")
                if alt and alt.strip():
                    self.out.append(f"[{alt.strip()}]")

    def handle_endtag(self, tag: str) -> None:
        if tag in DROP_CONTENT:
            self.skip = max(0, self.skip - 1)
        elif not self.skip and tag in BLOCKS:
            self.out.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.out.append(data)


def html_to_text(html: str) -> str:
    converter = _TextConverter()
    converter.feed(html)
    converter.close()
    lines = []
    for line in "".join(converter.out).split("\n"):
        cells = (" ".join(cell.split()) for cell in line.split("\t"))  # split() also eats nbsp
        lines.append("\t".join(cell for cell in cells if cell))  # empty cells are layout noise
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
