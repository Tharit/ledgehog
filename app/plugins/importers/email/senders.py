"""The sender guard (spec/plugins/importers/email.md §3): a message is accepted when one of its addresses is
in the whitelist, whole addresses compared without regard to case.

This is a guard, not authentication: every header read here can be written by whoever sends the message.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from email.message import Message
from email.utils import getaddresses

# parsed as address headers: only the address counts, never a display name
PARSED_HEADERS = ("From", "Resent-From", "Resent-Sender")
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


def addresses_of(msg: Message) -> set[str]:
    """Every address the guard reads from the message's headers, lower-cased."""
    found: set[str] = set()
    for name in PARSED_HEADERS:
        for _, address in getaddresses(_values(msg, name)):
            if address:
                found.add(address.strip().lower())
    for name in TOKEN_HEADERS:
        for value in _values(msg, name):
            found.update(token.strip(".").lower() for token in _TOKEN.findall(value))
    return found


def is_accepted(msg: Message, senders: Collection[str]) -> bool:
    allowed = {s.strip().lower() for s in senders}
    return not allowed.isdisjoint(addresses_of(msg))
