"""MT940 field 86 in the German DK layout, read by us and not by the mt-940 library (fints.md §6).

The library's reading of the free text varies with the bank's layout (a glued IBAN, padded and
newlined references), so one parser of ours reads the raw text and the corpus tests pin it.

The layout: `GVC?00posting text?10prima nota?20…?29purpose?30BIC or bank code?31IBAN or account?32name
?33name?34text key addition?60…?63purpose`. Lines are joined without a separator (the DK
convention); a subfield may break anywhere inside. In the purpose subfields (`?20`–`?29`, `?60`–`?63`)
the SEPA identifiers sit as `TAG+value`, **each tag at the start of a subfield**: a tag-like text
anywhere else (a payer typing `SVWZ+` mid-sentence) is ordinary purpose text, and so is a tag that is
not in the DK list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# The identifiers of the DK's SEPA conventions (the tags field 86 carries as `TAG+`).
KNOWN_TAGS: frozenset[str] = frozenset(
    {
        "EREF",  # end-to-end reference
        "KREF",  # customer reference
        "MREF",  # mandate reference
        "CRED",  # creditor identifier
        "DEBT",  # originator identifier
        "COAM",  # compensation amount
        "OAMT",  # original amount
        "SVWZ",  # remittance information
        "ABWA",  # deviating payer
        "ABWE",  # deviating payee
        "IBAN",  # counterparty IBAN
        "BIC",  # counterparty BIC
        "BREF",  # bank reference
        "RREF",  # return reference
    }
)

_PURPOSE_SUBFIELDS = (*range(20, 30), *range(60, 64))
_STRUCTURED = re.compile(r"^\d{3}\?\d{2}")
_SUBFIELD = re.compile(r"\?(\d{2})")
_TAG = re.compile(r"^([A-Z]{2,4})\+")
_BIC = re.compile(r"^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?$")
_IBAN = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]+$")

# IBAN length by country (the registry), the check that a candidate is an IBAN and not an account number.
IBAN_LENGTH: dict[str, int] = {
    "AD": 24, "AL": 28, "AT": 20, "BA": 20, "BE": 16, "BG": 22, "CH": 21, "CY": 28, "CZ": 24, "DE": 22,
    "DK": 18, "EE": 20, "ES": 24, "FI": 18, "FO": 18, "FR": 27, "GB": 22, "GI": 23, "GL": 18, "GR": 27,
    "HR": 21, "HU": 28, "IE": 22, "IS": 26, "IT": 27, "LI": 21, "LT": 20, "LU": 20, "LV": 21, "MC": 27,
    "MD": 24, "ME": 22, "MK": 19, "MT": 31, "NL": 18, "NO": 15, "PL": 28, "PT": 25, "RO": 24, "RS": 22,
    "SE": 24, "SI": 19, "SK": 24, "SM": 27, "TR": 26, "VA": 22, "XK": 20,
}  # fmt: skip


def valid_iban(text: str) -> str | None:
    """The IBAN `text` is (upper case, no spaces), or None: country length and mod-97 must both hold."""
    candidate = re.sub(r"\s+", "", text).upper()
    if not _IBAN.match(candidate) or IBAN_LENGTH.get(candidate[:2]) != len(candidate):
        return None
    digits = "".join(str(int(c, 36)) for c in candidate[4:] + candidate[:4])
    return candidate if int(digits) % 97 == 1 else None


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _squeeze(text: str) -> str:
    return re.sub(r"\s+", "", text)


@dataclass(frozen=True, slots=True)
class Field86:
    booking_text: str | None = None
    counterparty_iban: str | None = None
    counterparty_bic: str | None = None
    counterparty_name: str | None = None
    purpose: str | None = None
    end_to_end_id: str | None = None
    mandate_ref: str | None = None


def _subfields(joined: str) -> dict[int, str]:
    parts = _SUBFIELD.split(joined)
    found: dict[int, str] = {}
    for number, text in zip(parts[1::2], parts[2::2], strict=True):
        found[int(number)] = found.get(int(number), "") + text
    return found


def _segments(subfields: list[str]) -> list[tuple[str | None, str]]:
    """The purpose text cut at the tags that start a subfield: (tag or None, value)."""
    segments: list[tuple[str | None, str]] = []
    for text in subfields:
        tag = _TAG.match(text)
        if tag is not None and tag.group(1) in KNOWN_TAGS:
            segments.append((tag.group(1), text[tag.end() :]))
        elif segments:
            segments[-1] = (segments[-1][0], segments[-1][1] + text)
        else:
            segments.append((None, text))
    return segments


def parse_field86(text: str) -> Field86:
    joined = "".join(line.strip("\r\n") for line in text.splitlines())
    if _STRUCTURED.match(joined):
        sub = _subfields(joined)
        posting = _collapse(sub.get(0, "")) or None
        purpose_parts = [sub[n] for n in _PURPOSE_SUBFIELDS if n in sub]
        bic_text = _squeeze(sub.get(30, "")).upper()
        account_text = sub.get(31, "")
        name = _collapse(sub.get(32, "") + sub.get(33, ""))
    else:  # no subfields: the whole text is purpose, and a tag may still open it
        posting, purpose_parts, bic_text, account_text, name = None, [joined], "", "", ""
    segments = _segments(purpose_parts)
    tagged: dict[str, str] = {}
    for tag, value in segments:
        if tag is not None:
            tagged.setdefault(tag, value)

    iban = valid_iban(account_text)
    if iban is None:  # a leading IBAN glued to the name
        country_length = IBAN_LENGTH.get(name[:2].upper())
        glued = valid_iban(name[:country_length]) if country_length else None
        if glued is not None:
            iban, name = glued, _collapse(name[country_length:])
    if iban is None and "IBAN" in tagged:
        iban = valid_iban(tagged["IBAN"])
    bic = bic_text if _BIC.match(bic_text) else None
    if bic is None and "BIC" in tagged:
        candidate = _squeeze(tagged["BIC"]).upper()
        bic = candidate if _BIC.match(candidate) else None

    eref = _squeeze(tagged.get("EREF", ""))
    return Field86(
        booking_text=posting,
        counterparty_iban=iban,
        counterparty_bic=bic,
        counterparty_name=name or None,
        purpose=_collapse(" ".join(v for t, v in segments if t in (None, "SVWZ"))) or None,
        end_to_end_id=None if not eref or eref.upper() == "NOTPROVIDED" else eref,
        mandate_ref=_squeeze(tagged.get("MREF", "")) or None,
    )
