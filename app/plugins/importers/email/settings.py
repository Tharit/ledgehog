"""The email importer's settings (spec/plugins/importers/email.md §1): what the user types, checked.

Every error names the setting, never its value (an address, a login name): `InvalidProfile`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from app.core.plugins.errors import InvalidProfile

SETTING_KEYS = ("host", "security", "port", "username", "mailbox", "senders", "start_date")
DEFAULT_PORTS: Mapping[str, int] = {"tls": 993, "starttls": 143}
DEFAULT_MAILBOX = "INBOX"

_ADDRESS = re.compile(r"^[^\s@<>,;:\"()\[\]\\]+@[^\s@<>,;:\"()\[\]\\]+$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True, slots=True)
class EmailSettings:
    host: str
    security: Literal["tls", "starttls"]
    port: int
    username: str
    mailbox: str
    senders: frozenset[str]
    start_date: date


def _bad(key: str, why: str) -> InvalidProfile:
    return InvalidProfile(f"{key}: {why}")


def _text(settings: Mapping[str, Any], key: str, *, required: bool) -> str:
    value = settings.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise _bad(key, "is required")
        return ""
    if not isinstance(value, str):
        raise _bad(key, "must be text")
    if _CONTROL.search(value):
        raise _bad(key, "must not contain control characters")
    return value.strip()


def _host(settings: Mapping[str, Any]) -> str:
    host = _text(settings, "host", required=True)
    if "://" in host or "/" in host or ":" in host or "@" in host or any(c.isspace() for c in host):
        raise _bad("host", "must be a host name only: no scheme, port, path or credentials")
    return host


def _security(settings: Mapping[str, Any]) -> Literal["tls", "starttls"]:
    value = settings.get("security")
    if value == "tls":
        return "tls"
    if value == "starttls":
        return "starttls"
    raise _bad("security", "must be tls or starttls")


def _port(settings: Mapping[str, Any], security: str) -> int:
    value = settings.get("port")
    if value is None or value == "":
        return DEFAULT_PORTS[security]
    if type(value) is not int or not 1 <= value <= 65535:
        raise _bad("port", "must be a whole number from 1 to 65535")
    return value


def _senders(settings: Mapping[str, Any]) -> frozenset[str]:
    raw = settings.get("senders")
    if not isinstance(raw, list | tuple) or not raw:
        raise _bad("senders", "needs at least one address")
    found: list[str] = []
    for entry in raw:
        if not isinstance(entry, str) or not _ADDRESS.match(entry.strip()):
            raise _bad("senders", "every entry must be one address (local@domain)")
        found.append(entry.strip().lower())
    if len(set(found)) != len(found):
        raise _bad("senders", "an address is listed twice")
    return frozenset(found)


def _start_date(settings: Mapping[str, Any]) -> date:
    value = settings.get("start_date")
    if not isinstance(value, str):
        raise _bad("start_date", "is required, as an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _bad("start_date", "must be an ISO date") from None


def parse_settings(settings: Mapping[str, Any]) -> EmailSettings:
    """The settings as typed values; raises `InvalidProfile` naming the first setting that breaks its rule."""
    for key in settings:
        if key not in SETTING_KEYS:
            raise InvalidProfile(f"{key}: unknown setting")
    security = _security(settings)
    return EmailSettings(
        host=_host(settings),
        security=security,
        port=_port(settings, security),
        username=_text(settings, "username", required=True),
        mailbox=_text(settings, "mailbox", required=False) or DEFAULT_MAILBOX,
        senders=_senders(settings),
        start_date=_start_date(settings),
    )
