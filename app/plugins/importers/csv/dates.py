"""Date formats written with the tokens `dd d MM M yyyy` (+ `HH mm ss`), csv.md §3, §5."""

from __future__ import annotations

import re
from datetime import date
from functools import lru_cache

from app.plugins.importers.csv.cells import DateCell

_TOKENS = re.compile(r"(yyyy|dd|d|MM|M|HH|mm|ss)")
_DAY, _MONTH = ("dd", "d"), ("MM", "M")


def _tokens(fmt: str) -> list[str]:
    return [t for t in _TOKENS.findall(fmt)]


def validate_format(fmt: str) -> None:
    """A usable format has one year (four digits), one month and one day token."""
    if not isinstance(fmt, str) or not fmt:
        raise ValueError("a date format is required")
    toks = _tokens(fmt)
    if toks.count("yyyy") != 1:
        raise ValueError("the format needs exactly one four-digit year token, yyyy")
    if sum(toks.count(t) for t in _MONTH) != 1:
        raise ValueError("the format needs exactly one month token, MM or M")
    if sum(toks.count(t) for t in _DAY) != 1:
        raise ValueError("the format needs exactly one day token, dd or d")
    for t in ("HH", "mm", "ss"):
        if toks.count(t) > 1:
            raise ValueError(f"the token {t} may occur only once")


@lru_cache(maxsize=64)
def _compile(fmt: str) -> re.Pattern[str]:
    validate_format(fmt)
    out: list[str] = []
    for part in _TOKENS.split(fmt):
        if part == "yyyy":
            out.append(r"(?P<y>\d{4})")
        elif part in _DAY:
            out.append(r"(?P<d>\d{1,2})")
        elif part in _MONTH:
            out.append(r"(?P<m>\d{1,2})")
        elif part in ("HH", "mm", "ss"):
            out.append(r"\d{2}")
        else:
            out.append(r"\s+".join(re.escape(w) for w in re.split(r"\s+", part)))
    return re.compile("".join(out))


def parse_date(text: str, fmt: str) -> date | None:
    """The date in `text` (whole trimmed text), or None if it does not match or is no date.

    A cell a spreadsheet stored as a date is that date; the format applies to text only.
    """
    if isinstance(text, DateCell):
        return text.value
    m = _compile(fmt).fullmatch(text.strip())
    if m is None:
        return None
    try:
        return date(int(m["y"]), int(m["m"]), int(m["d"]))
    except ValueError:
        return None
