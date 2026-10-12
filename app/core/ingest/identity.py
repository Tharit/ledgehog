"""Identity of a source transaction (spec §5.2, I4; decision D103).

A row's identity is its `source_id` where the source assigns one, otherwise a
content hash computed here, by ingest. A `source_id` is the identity itself and
is never also a hash input (D103 supersedes D46). Pure: no DB, no env.
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from app.core.plugins.importer import IncomingRow


@lru_cache(maxsize=1 << 16)
def canonical_text(s: str | None) -> str:
    """Unicode NFKC, then casefold, then keep alphanumerics only (spec §5.2).

    None and "" both give "". Whitespace, punctuation and symbols vanish.
    Combining marks are not alphanumeric (category M*), so a mark that does not
    compose with its base under NFKC is dropped; composable pairs such as
    e + U+0301 become the precomposed letter first and survive. `ß` folds to
    `ss`. (The spec does not mention marks; this is the literal reading of
    "alphanumerics only".)
    """
    if not s:
        return ""
    folded = unicodedata.normalize("NFKC", s).casefold()
    return "".join(ch for ch in folded if ch.isalnum())


def _field(name: str, value: str) -> bytes:
    n = name.encode("ascii")
    v = value.encode("utf-8")
    return len(n).to_bytes(4, "big") + n + len(v).to_bytes(8, "big") + v


def content_hash(
    amount_minor: int,
    currency: str,
    booked_on: date,
    counterparty_ref: str | None,
    purpose: str | None,
    ordinal: int,
) -> bytes:
    """SHA-256 over named, length-prefixed fields.

    Every field is `len(name) name len(value) value`, so no value in one field
    can reproduce another field's input. Text fields are canonicalised here.
    """
    payload = b"".join(
        (
            _field("amount", str(amount_minor)),
            _field("currency", currency),
            _field("booked_on", booked_on.isoformat()),
            _field("counterparty_ref", canonical_text(counterparty_ref)),
            _field("purpose", canonical_text(purpose)),
            _field("ordinal", str(ordinal)),
        )
    )
    return hashlib.sha256(payload).digest()


@dataclass(frozen=True, slots=True)
class SourceId:
    value: str


@dataclass(frozen=True, slots=True)
class ContentHash:
    value: bytes

    def hex(self) -> str:
        """Text form for the `source_transaction.content_hash` text column."""
        return self.value.hex()


Identity = SourceId | ContentHash


def _group_key(row: IncomingRow) -> tuple[int, str, date, str, str]:
    return (
        row.amount_minor,
        row.currency,
        row.booked_on,
        canonical_text(row.counterparty_ref),
        canonical_text(row.purpose),
    )


def assign_ordinals(rows: Sequence[IncomingRow]) -> list[int]:
    """Ordinal of each row among rows identical in every canonicalised hashed
    field within the delivery, 0-based, in delivery order.

    Rows carrying a `source_id` need none (the id tells them apart): they get 0
    and are not counted in any group.
    """
    seen: dict[tuple[int, str, date, str, str], int] = {}
    out: list[int] = []
    for row in rows:
        if row.source_id is not None:
            out.append(0)
            continue
        key = _group_key(row)
        out.append(seen.get(key, 0))
        seen[key] = out[-1] + 1
    return out


def identity_of(row: IncomingRow, ordinal: int) -> Identity:
    """`SourceId` if the importer supplied one, else `ContentHash`; never both."""
    if row.source_id is not None:
        return SourceId(row.source_id)
    return ContentHash(
        content_hash(
            row.amount_minor,
            row.currency,
            row.booked_on,
            row.counterparty_ref,
            row.purpose,
            ordinal,
        )
    )
