"""Text helpers shared by the classifier plugins and core's snapshot (rules.md, history.md)."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection
from functools import lru_cache

_WHITESPACE = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[\W_]+")

TOKEN_MIN_LENGTH = 3


def normalise_name(s: str | None) -> str:
    """Rules' name normalisation: NFKC, casefold, whitespace runs to one space, trimmed.

    Punctuation is kept (rules.md §2), so `PAYPAL *` tells `PAYPAL *X` from `PayPal Europe`.
    """
    if not s:
        return ""
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", s).casefold()).strip()


@lru_cache(maxsize=1 << 16)
def purpose_tokens(purpose: str | None) -> frozenset[str]:
    """The tokens of a purpose (history.md §2): NFKC, casefolded, split on anything not alphanumeric,
    tokens of at least 3 characters with no digit kept. The counterparty name is not part of it."""
    if not purpose:
        return frozenset()
    folded = unicodedata.normalize("NFKC", purpose).casefold()
    return frozenset(
        tok
        for tok in _NON_ALNUM.split(folded)
        if len(tok) >= TOKEN_MIN_LENGTH and not any(ch.isdigit() for ch in tok)
    )


def jaccard(a: Collection[str], b: Collection[str]) -> float:
    """|a & b| / |a | b|; 0.0 when both are empty."""
    sa, sb = set(a), set(b)
    union = len(sa | sb)
    return len(sa & sb) / union if union else 0.0
