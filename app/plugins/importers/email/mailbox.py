"""The one narrow seam to the IMAP server (spec/plugins/importers/email.md §2, §8, §10), over `imaplib`.

The importer's logic is written against `Mailbox` and tested against a fake of it. `connect_imap` is the real
one: implicit TLS or STARTTLS with the system's trust store and host name checked, the mailbox opened
read-only (`EXAMINE`), every message read with `BODY.PEEK[]`. Nothing is marked seen, moved or deleted.
Failures of the connection are `SourceUnavailable`; their messages name the rule, never a setting.
"""

from __future__ import annotations

import base64
import email
import imaplib
import logging
import re
import ssl
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from app.core.plugins.errors import AuthRejected, InvalidProfile, SourceUnavailable
from app.core.plugins.fetch import SecretText

log = logging.getLogger("ledgehog.email")

COMMAND_TIMEOUT_S = 30.0
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass(frozen=True, slots=True)
class Connection:
    """Where and as whom to connect: from the settings, with the password the user typed."""

    host: str
    port: int
    security: str  # "tls" | "starttls"
    username: str


@dataclass(frozen=True, slots=True)
class RawMessage:
    """A message's bytes and the date it arrived at the server (INTERNALDATE's calendar date)."""

    raw: bytes
    arrived: date


class Mailbox(Protocol):
    """A logged-in connection. Every method blocks. A message that is gone answers None."""

    def examine(self, name: str) -> int:
        """Open the folder read-only; its UIDVALIDITY. A missing one is `InvalidProfile` naming `mailbox`."""
        ...

    def uids_after(self, uid: int) -> list[int]:
        """The UIDs above `uid`, ascending (`UID SEARCH UID uid+1:*` answers the highest UID even where it is
        lower, so the answer is filtered)."""
        ...

    def uids_since(self, day: date) -> list[int]:
        """The UIDs of messages that arrived on `day` or later (`UID SEARCH SINCE`), ascending."""
        ...

    def header_message_id(self, uid: int) -> str | None:
        """The raw `Message-ID` header value, from the headers alone; None where there is none."""
        ...

    def size(self, uid: int) -> int | None:
        """`RFC822.SIZE`."""
        ...

    def fetch(self, uid: int) -> RawMessage | None:
        """The whole message, `BODY.PEEK[]`."""
        ...

    def logout(self) -> None: ...


Connect = Callable[[Connection, SecretText], Mailbox]


# ---- IMAP encodings ---------------------------------------------------------------------------------


def encode_mailbox_name(name: str) -> str:
    """A folder name as IMAP sends it: modified UTF-7 for anything outside printable ASCII, then quoted."""
    out: list[str] = []
    pending: list[str] = []

    def flush() -> None:
        if pending:
            data = "".join(pending).encode("utf-16-be")
            out.append("&" + base64.b64encode(data).decode("ascii").rstrip("=").replace("/", ",") + "-")
            pending.clear()

    for ch in name:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            pending.append(ch)
    flush()
    return '"' + "".join(out).replace("\\", "\\\\").replace('"', '\\"') + '"'


def search_date(day: date) -> str:
    """A date as IMAP's search takes it (`01-Jan-2026`), with English month names whatever the locale."""
    return f"{day.day:02d}-{MONTHS[day.month - 1]}-{day.year}"


_INTERNALDATE = re.compile(rb'INTERNALDATE "\s*(\d{1,2})-([A-Za-z]{3})-(\d{4}) ')
_SIZE = re.compile(rb"RFC822\.SIZE (\d+)")


def _arrival(parts: list[bytes]) -> date | None:
    for part in parts:
        found = _INTERNALDATE.search(part)
        if found and found.group(2).decode("ascii").title() in MONTHS:
            month = MONTHS.index(found.group(2).decode("ascii").title()) + 1
            return date(int(found.group(3)), month, int(found.group(1)))
    return None


@contextmanager
def _transport_errors() -> Iterator[None]:
    """A failed connection, a time-out, a dropped session or a refused command: the source is unavailable."""
    try:
        yield
    except (imaplib.IMAP4.error, OSError, EOFError) as exc:  # ssl.SSLError and TimeoutError are OSErrors
        raise SourceUnavailable(f"the mail server could not be used ({type(exc).__name__})") from None


class ImapMailbox:
    """`Mailbox` over an `imaplib` connection that is already logged in."""

    def __init__(self, imap: imaplib.IMAP4) -> None:
        self._imap = imap

    def examine(self, name: str) -> int:
        with _transport_errors():
            status, _ = self._imap.select(encode_mailbox_name(name), readonly=True)  # EXAMINE
            if status != "OK":
                raise InvalidProfile("mailbox: the folder does not exist")
            _, values = self._imap.response("UIDVALIDITY")
            if not values or values[0] is None:
                raise SourceUnavailable("the mail server gave no UIDVALIDITY")
            return int(values[0])

    def _search(self, *criteria: str) -> list[int]:
        with _transport_errors():
            status, data = self._imap.uid("SEARCH", *criteria)
            if status != "OK":
                raise SourceUnavailable("the mail server refused a search")
        first = data[0] if data else None
        return sorted({int(token) for token in (first.split() if isinstance(first, bytes) else [])})

    def uids_after(self, uid: int) -> list[int]:
        return [u for u in self._search("UID", f"{uid + 1}:*") if u > uid]

    def uids_since(self, day: date) -> list[int]:
        return self._search("SINCE", search_date(day))

    def _fetch(self, uid: int, items: str) -> list[object]:
        with _transport_errors():
            status, data = self._imap.uid("FETCH", str(uid), items)
            if status != "OK":
                raise SourceUnavailable("the mail server refused a fetch")
        return list(data or [])

    def header_message_id(self, uid: int) -> str | None:
        for item in self._fetch(uid, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])"):
            if isinstance(item, tuple) and isinstance(item[1], bytes):
                value = email.message_from_bytes(item[1])["Message-ID"]
                return str(value) if value is not None else None
        return None

    def size(self, uid: int) -> int | None:
        for item in self._fetch(uid, "(RFC822.SIZE)"):
            blob = item[0] if isinstance(item, tuple) else item
            found = _SIZE.search(blob) if isinstance(blob, bytes) else None
            if found:
                return int(found.group(1))
        return None

    def fetch(self, uid: int) -> RawMessage | None:
        data = self._fetch(uid, "(INTERNALDATE BODY.PEEK[])")
        raw: bytes | None = None
        texts: list[bytes] = []
        for item in data:
            if isinstance(item, tuple):
                texts.append(item[0])
                if raw is None and isinstance(item[1], bytes):
                    raw = item[1]
            elif isinstance(item, bytes):
                texts.append(item)
        if raw is None:
            return None
        return RawMessage(raw, _arrival(texts) or date.min)

    def logout(self) -> None:
        self._imap.logout()


def connect_imap(connection: Connection, password: SecretText) -> Mailbox:
    """Connect, secure the connection and log in.

    `tls` is implicit TLS; `starttls` upgrades a plain connection before the login and fails with
    `InvalidProfile` (naming `security`) if the server offers none. Certificates are always verified.
    """
    context = ssl.create_default_context()
    with _transport_errors():
        if connection.security == "tls":
            imap: imaplib.IMAP4 = imaplib.IMAP4_SSL(
                connection.host, connection.port, ssl_context=context, timeout=COMMAND_TIMEOUT_S
            )
        else:
            imap = imaplib.IMAP4(connection.host, connection.port, timeout=COMMAND_TIMEOUT_S)
            if "STARTTLS" not in imap.capabilities:
                _drop(imap)
                raise InvalidProfile("security: the server offers no STARTTLS")
            imap.starttls(ssl_context=context)
    try:
        _login(imap, connection.username, password)
    except BaseException:
        _drop(imap)
        raise
    return ImapMailbox(imap)


def _login(imap: imaplib.IMAP4, username: str, password: SecretText) -> None:
    try:
        imap.login(username, password.reveal())
    except UnicodeEncodeError:
        raise AuthRejected(
            "the login cannot be sent: it holds characters IMAP's login does not allow"
        ) from None
    except imaplib.IMAP4.abort as exc:
        raise SourceUnavailable(f"the mail server dropped the connection ({type(exc).__name__})") from None
    except imaplib.IMAP4.error:
        raise AuthRejected("the mail server refused the login") from None
    except OSError as exc:
        raise SourceUnavailable(f"the mail server could not be used ({type(exc).__name__})") from None


def _drop(imap: imaplib.IMAP4) -> None:
    try:
        imap.logout()
    except (imaplib.IMAP4.error, OSError, EOFError) as exc:
        log.info("closing the mail connection failed: %s", type(exc).__name__)
