"""From an extraction to a document (spec/plugins/importers/email.md §6): completeness, signs, the provider.

Deterministic and free of the model: the same extraction gives the same document. A complete document only:
a total of at least 0, a line of non-zero amount, whole minor units, and what the lines leave of the total no
larger than the lines themselves. A refund is the same with the opposite signs, keyed by its message. The
check guards against misreads; what the lines leave is the core's to spread (spec §5.8), so no line is added
for it.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Callable, Mapping
from decimal import Decimal, localcontext
from typing import Any

from app.core.plugins.importer import IncomingDocument, IncomingDocumentLine
from app.plugins.importers.email.extractor import (
    INCOMPLETE,
    NO_MERCHANT,
    UNKNOWN_CURRENCY,
    Extraction,
    MessageContext,
    Skipped,
)

MERCHANT_NAME_MAX = 200
TITLE_MAX = 200
PROVIDER_MAX = 100
MAX_MINOR = 10**15  # well inside the database's bigint
MAX_QTY = 2_000_000_000  # the database's integer

# ---- the provider ------------------------------------------------------------------------------------

_SECOND_LEVELS = frozenset({"co", "com", "org", "net", "ac", "gov", "ne"})
_DOMAIN = re.compile(r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}")
# trailing legal forms, each a whole word with its punctuation; the longest is tried first
LEGAL_FORMS: tuple[str, ...] = (
    "GmbH & Co. KGaA", "GmbH & Co. KG", "GmbH", "gGmbH", "UG (haftungsbeschränkt)", "UG", "AG", "KGaA", "KG",
    "OHG", "GbR", "e.K.", "e.V.", "SE", "Ltd", "Limited", "PLC", "LLP", "LLC", "Inc", "Corp", "Corporation",
    "Co", "S.A.", "SA", "S.à r.l.", "S.a.r.l.", "SARL", "SAS", "S.L.", "SL", "S.p.A.", "S.r.l.", "B.V.", "BV",
    "N.V.", "NV", "AB", "AS", "A/S", "ApS", "Oy", "Sp. z o.o.",
)  # fmt: skip


def _form_pattern(form: str) -> str:
    """The form with its spaces as any whitespace; its final dot is the pattern's optional one."""
    return r"\s+".join(re.escape(word) for word in form.rstrip(".").split(" "))


_TRAILING_FORM = re.compile(
    r"(?<!\w)(?:"
    + "|".join(_form_pattern(f) for f in sorted(LEGAL_FORMS, key=len, reverse=True))
    + r")\.?\s*$",
    re.IGNORECASE,
)
_TRAILING_PUNCTUATION = " ,.-"


def collapse(text: str) -> str:
    return " ".join(text.split())


# a reply or forwarding marker, with its optional counter: `Re:`, `AW:`, `Fwd[2]:`, `Wg (3):`
_SUBJECT_MARKER = re.compile(r"\s*(?:re|fwd?|aw|wg)\s*(?:\[\s*\d+\s*\]|\(\s*\d+\s*\))?\s*:", re.IGNORECASE)


def strip_subject_markers(subject: str) -> str:
    """The subject without the reply and forwarding markers in front of it (plugins/importers/email.md §6).

    Repeatedly, without regard to case, until it starts with something else; `Rechnung: 1` is no `Re:`.
    """
    while match := _SUBJECT_MARKER.match(subject):
        subject = subject[match.end() :]
    return subject.strip()


def _domain_label(name: str) -> str:
    """A bare domain's registrable label (`www.zalando.de` is `zalando`); any other name as it is."""
    if not _DOMAIN.fullmatch(name):
        return name
    labels = name.split(".")
    if labels[0].lower() == "www":
        labels = labels[1:]
    country = labels.pop()  # the last label
    if len(labels) >= 2 and len(country) == 2 and labels[-1].lower() in _SECOND_LEVELS:
        labels.pop()
    return labels[-1] if labels else name


def canonical_provider(merchant: str) -> str:
    """The provider a merchant names (§6): NFKC, whitespace collapsed, a bare domain as its label, trailing
    legal forms and punctuation removed, case kept, at most 100 characters. Empty: there is none."""
    name = _domain_label(collapse(unicodedata.normalize("NFKC", merchant)))
    while True:
        stripped = name.rstrip(_TRAILING_PUNCTUATION)
        stripped = _TRAILING_FORM.sub("", stripped).rstrip(_TRAILING_PUNCTUATION)
        if stripped == name:
            break
        name = stripped
    return name[:PROVIDER_MAX].rstrip(_TRAILING_PUNCTUATION)


# ---- amounts -----------------------------------------------------------------------------------------


def _decimal(value: object) -> Decimal | None:
    """A JSON number as written (a float through its shortest representation, never its binary value);
    None for anything else, and for a number that is not finite."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float) and math.isfinite(value):
        return Decimal(repr(value))
    return None


def _minor(value: Decimal, exponent: int) -> int | None:
    """Whole minor units, else None."""
    with localcontext() as ctx:
        ctx.prec = 60
        scaled = value.scaleb(exponent)
        if scaled != scaled.to_integral_value() or abs(scaled) > MAX_MINOR:
            return None
        return int(scaled)


def _amounts(
    answer: Mapping[str, Any], exponent: int
) -> tuple[int, list[tuple[str, int, Decimal | None]]] | None:
    """(total, [(name, amount, quantity)]) in minor units, or None where it is incomplete: a total of at least
    0, at least one line, every line named and amounted, everything in whole minor units."""
    total_value = _decimal(answer.get("total"))
    items = answer.get("items")
    if total_value is None or total_value < 0 or not isinstance(items, list) or not items:
        return None
    total = _minor(total_value, exponent)
    if total is None:
        return None
    lines: list[tuple[str, int, Decimal | None]] = []
    for item in items:
        name = item.get("name") if isinstance(item, Mapping) else None
        if not isinstance(name, str) or not collapse(name):
            return None
        amount_value = _decimal(item.get("amount"))
        amount = None if amount_value is None else _minor(amount_value, exponent)
        if amount is None:
            return None
        lines.append((collapse(name), amount, _decimal(item.get("quantity"))))
    return total, lines


def _as_quantity(quantity: Decimal | None) -> int | None:
    """The line's `qty`: the quantity where it is a whole number from 1."""
    if quantity is None or quantity < 1 or quantity != quantity.to_integral_value() or quantity > MAX_QTY:
        return None
    return int(quantity)


def _line_amounts(total: int, lines: list[tuple[str, int, Decimal | None]]) -> list[int] | None:
    """The amounts the lines carry: as given, unless those do not sum to the total and each times its quantity
    (none taken as 1), each still a whole number of minor units, does. None where the lines are not complete:
    no line of non-zero amount, or what they leave of the total (|total - sum|) larger than the sum of their
    magnitudes."""
    amounts = [amount for _, amount, _ in lines]
    if sum(amounts) != total:
        products: list[int] = []
        for _, amount, quantity in lines:
            product = _minor(Decimal(amount) * (quantity if quantity is not None else 1), 0)
            if product is None:
                break  # not a whole number of minor units
            products.append(product)
        else:
            if sum(products) == total:
                amounts = products
    magnitude = sum(abs(a) for a in amounts)
    if magnitude == 0 or abs(total - sum(amounts)) > magnitude:
        return None
    return amounts


# ---- the document ------------------------------------------------------------------------------------


class EmailDocumentBuilder:
    """Satisfies `DocumentBuilder`."""

    def build(
        self, extraction: Extraction, context: MessageContext, *, minor_units_of: Callable[[str], int]
    ) -> IncomingDocument | Skipped:
        answer = extraction.answer
        refund = answer.get("refund") is True
        currency = answer.get("currency")
        code = currency.strip().upper() if isinstance(currency, str) else ""
        if not code:
            return Skipped(INCOMPLETE)
        try:
            if not re.fullmatch(r"[A-Z]{3}", code):
                raise KeyError(code)
            exponent = minor_units_of(code)
        except KeyError:
            return Skipped(UNKNOWN_CURRENCY)
        parsed = _amounts(answer, exponent)
        if parsed is None:
            return Skipped(INCOMPLETE)
        total, lines = parsed
        amounts = _line_amounts(total, lines)
        if amounts is None:
            return Skipped(INCOMPLETE)
        merchant = answer.get("merchant")
        provider = canonical_provider(merchant) if isinstance(merchant, str) else ""
        if not isinstance(merchant, str) or not provider:
            return Skipped(NO_MERCHANT)
        order_id = answer.get("order_id")
        order = collapse(order_id) if isinstance(order_id, str) else ""
        subject = strip_subject_markers(collapse(context.subject)) if context.subject else ""
        return IncomingDocument(
            provider=provider,
            source_id=f"message:{context.identity}" if refund or not order else order,
            reference=order or None,
            occurred_on=context.date,
            total_minor=total if refund else -total,
            currency=code,
            merchant_name=collapse(merchant)[:MERCHANT_NAME_MAX] or None,
            title=subject[:TITLE_MAX] or None,
            lines=tuple(
                IncomingDocumentLine(name, amount if refund else -amount, _as_quantity(quantity))
                for (name, _, quantity), amount in zip(lines, amounts, strict=True)
                if amount != 0
            ),
            raw={
                "message_id": context.identity,
                "outer_message_id": context.outer_identity,
                "uid": context.uid,
                "uidvalidity": context.uidvalidity,
                "date": context.date.isoformat(),
                "source": extraction.source,
                "pdf": extraction.pdf,
                "extraction": dict(answer),
                "model": extraction.model,
            },
        )
