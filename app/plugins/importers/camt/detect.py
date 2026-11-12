"""Choosing the reader by the document's root element (camt.md §1, §5).

The file is untrusted input: it is parsed with the standard library, and a document carrying a DOCTYPE
is refused before any entity is expanded.
"""

from __future__ import annotations

from xml.etree import ElementTree as ET

from app.core.plugins.errors import ParseFailed
from app.plugins.importers.camt import olb
from app.plugins.importers.camt.model import Statement


class _Doctype(Exception):
    pass


class _Builder(ET.TreeBuilder):
    def doctype(self, name: str, pubid: str, system: str) -> None:
        raise _Doctype


def _root(data: bytes) -> ET.Element:
    parser = ET.XMLParser(target=_Builder())
    try:
        parser.feed(data)
        return parser.close()
    except _Doctype:
        raise ParseFailed("the file carries a DOCTYPE, which a camt export never does: refused") from None
    except ET.ParseError:
        raise ParseFailed("the file is not well-formed XML") from None


def read_statement(data: bytes) -> Statement:
    root = _root(data)
    name = root.tag.rpartition("}")[2]
    if name == olb.ROOT and "}" not in root.tag:
        return olb.read(root)
    if name == "Document":
        raise ParseFailed("an ISO 20022 camt document (root Document): this format is not read yet")
    raise ParseFailed(f"no reader recognises the file: its root element is {name[:40]!r}")
