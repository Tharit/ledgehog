"""Who may send (spec/plugins/importers/email.md §3): a message is read when it names a listed address, whole
addresses compared without regard to case, and its sender is authenticated.

Every header naming an address can be written by whoever sends the message, so the inbox provider's verdict
counts: the topmost `Authentication-Results` header (RFC 8601), read as recorded; no signature is verified
here.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from email.message import Message
from email.utils import getaddresses
from enum import Enum

# parsed as address headers: only the address counts, never a display name
PARSED_HEADERS = ("From", "Resent-From", "Resent-Sender")
# the forwarding headers: every one of the above but From, and the token headers
FORWARDING_PARSED = ("Resent-From", "Resent-Sender")
# every address-looking token, every occurrence of the header
TOKEN_HEADERS = ("X-Forwarded-For", "X-MS-Exchange-Inbox-Rules-Loop", "Delivered-To", "X-Original-To")

_TOKEN = re.compile(r"[^\s<>,;:\"()\[\]\\]+@[^\s<>,;:\"()\[\]\\]+")


def _values(msg: Message, name: str) -> list[str]:
    out: list[str] = []
    for value in msg.get_all(name, []):
        try:
            out.append(str(value))
        except Exception:  # a header the parser cannot render is no address
            continue
    return out


def _addresses(msg: Message, parsed: tuple[str, ...], tokens: tuple[str, ...]) -> set[str]:
    found: set[str] = set()
    for name in parsed:
        for _, address in getaddresses(_values(msg, name)):
            if address:
                found.add(address.strip().lower())
    for name in tokens:
        for value in _values(msg, name):
            found.update(token.strip(".").lower() for token in _TOKEN.findall(value))
    return found


def addresses_of(msg: Message) -> set[str]:
    """Every address read from the message's headers, lower-cased."""
    return _addresses(msg, PARSED_HEADERS, TOKEN_HEADERS)


def forwarding_addresses_of(msg: Message) -> set[str]:
    """The addresses of the forwarding headers: everything but `From`."""
    return _addresses(msg, FORWARDING_PARSED, TOKEN_HEADERS)


def from_address(msg: Message) -> str | None:
    for _, address in getaddresses(_values(msg, "From")):
        if address:
            return address.strip().lower()
    return None


# ---- Authentication-Results (RFC 8601) -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthResult:
    method: str
    result: str
    properties: dict[str, str]  # "header.d" -> value, lower-cased names


def _sections(text: str) -> list[str]:
    """The `;`-separated sections of a header value, one scan: comments (nested parentheses) are dropped,
    quoted strings are kept whole, a backslash escapes the next character in both. Only an unquoted,
    uncommented `;` splits."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    quoted = False
    escaped = False
    for ch in text:
        if escaped:
            escaped = False
            if depth == 0:
                current.append(ch)
        elif ch == "\\":
            escaped = True
            if depth == 0:
                current.append(ch)
        elif quoted:
            current.append(ch)
            quoted = ch != '"'
        elif depth > 0:
            depth += (ch == "(") - (ch == ")")
        elif ch == "(":
            depth = 1
        elif ch == '"':
            quoted = True
            current.append(ch)
        elif ch == ";":
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return parts


_PAIR = re.compile(r'([A-Za-z0-9][A-Za-z0-9._+/-]*)\s*=\s*("(?:[^"\\]|\\.)*"|[^\s;]*)')


def parse_authentication_results(value: str) -> list[AuthResult]:
    """The method results of one header, `authserv-id; method=result ptype.property=value ...; ...`.
    The authserv-id and a `none` are no result."""
    sections = _sections(value)
    results: list[AuthResult] = []
    for section in sections[1:]:  # the first is the authserv-id
        current: AuthResult | None = None
        for key, raw in _PAIR.findall(section):
            val = raw[1:-1] if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2 else raw
            key = key.lower()
            if current is None:
                if "." in key:
                    break  # a property before a method: not a result
                current = AuthResult(key.split("/")[0], val.strip().lower(), {})
                results.append(current)
            elif "." in key:
                current.properties.setdefault(key, val.strip().lower())
    return results


def topmost_results(msg: Message) -> list[AuthResult]:
    """The results of the topmost `Authentication-Results` header (the last added), none where there is no
    header."""
    values = _values(msg, "Authentication-Results")
    return parse_authentication_results(values[0]) if values else []


def _domain_of(address: str) -> str:
    return address.rpartition("@")[2]


def _under(domain: str, signing: str) -> bool:
    """`signing` is `domain` or a parent domain of it: relaxed alignment without the public suffix list, so a
    signing domain must itself have a dot."""
    return "." in signing and (domain == signing or domain.endswith("." + signing))


def _dmarc_passes(results: list[AuthResult], domain: str) -> bool:
    return any(
        r.method == "dmarc"
        and r.result == "pass"
        and r.properties.get("header.from", domain).removeprefix("@") == domain
        for r in results
    )


def _dkim_passes(results: list[AuthResult], domain: str) -> bool:
    return any(
        r.method == "dkim"
        and r.result == "pass"
        and _under(domain, r.properties.get("header.d", "").removeprefix("@"))
        for r in results
    )


def _arc_passes(results: list[AuthResult]) -> bool:
    return any(r.method == "arc" and r.result == "pass" for r in results)


class Verdict(Enum):
    ACCEPTED = "accepted"
    NOT_ACCEPTED = "not_accepted"  # no listed address
    NOT_AUTHENTICATED = "not_authenticated"  # a listed address the provider did not vouch for


def check_sender(msg: Message, senders: Collection[str]) -> Verdict:
    """Accepted when a listed address is named and the topmost `Authentication-Results` shows: for a forward
    by hand, its listed `From` with a DMARC pass or a DKIM pass aligned with it; for an automatic forward, a
    DKIM pass for the `From`'s domain (or a parent) or an ARC pass, and a forwarding header naming a listed
    address."""
    allowed = {s.strip().lower() for s in senders}
    sender = from_address(msg)
    forwarded = not allowed.isdisjoint(forwarding_addresses_of(msg))
    by_hand = sender is not None and sender in allowed
    if not (by_hand or forwarded or not allowed.isdisjoint(addresses_of(msg))):
        return Verdict.NOT_ACCEPTED
    results = topmost_results(msg)
    if sender is not None:
        domain = _domain_of(sender)
        if by_hand and (_dmarc_passes(results, domain) or _dkim_passes(results, domain)):
            return Verdict.ACCEPTED
        if forwarded and (_dkim_passes(results, domain) or _arc_passes(results)):
            return Verdict.ACCEPTED
    elif forwarded and _arc_passes(results):
        return Verdict.ACCEPTED
    return Verdict.NOT_AUTHENTICATED


def is_accepted(msg: Message, senders: Collection[str]) -> bool:
    return check_sender(msg, senders) is Verdict.ACCEPTED
