"""Reading a message (spec/plugins/importers/email.md §3, §4): its inner messages, identity, date, text, PDFs.

Nothing here interprets: it picks what a message states and hands it on.
"""

from __future__ import annotations

import email
import hashlib
import re
from dataclasses import dataclass
from datetime import date
from email import policy
from email.message import EmailMessage, Message
from email.utils import parsedate_to_datetime

from app.plugins.importers.email.html_text import html_to_text

MAX_PDFS = 3  # per inner message


@dataclass(frozen=True, slots=True)
class PdfPart:
    """A PDF attached to (or inline in) an inner message: its file name and its bytes."""

    name: str
    data: bytes


def parse_message(raw: bytes) -> EmailMessage:
    msg = email.message_from_bytes(raw, policy=policy.default)
    assert isinstance(msg, EmailMessage)
    return msg


def normalise_message_id(value: object) -> str | None:
    """A Message-ID without its angle brackets and surrounding whitespace; None where there is none."""
    if value is None:
        return None
    cleaned = str(value).strip().strip("<>").strip()
    return cleaned or None


def message_id(msg: Message) -> str | None:
    try:
        return normalise_message_id(msg["Message-ID"])
    except Exception:  # a header the parser cannot render states no identity
        return None


def identity_of(msg: EmailMessage, raw: bytes | None = None) -> str:
    """The message's Message-ID; without one, the SHA-256 of its raw bytes (hex)."""
    found = message_id(msg)
    if found is not None:
        return found
    return hashlib.sha256(raw if raw is not None else msg.as_bytes()).hexdigest()


def inner_messages(outer: EmailMessage) -> list[EmailMessage]:
    """Every first-level `message/rfc822` part, each its own message; the message itself where it has none."""
    found: list[EmailMessage] = []
    if outer.is_multipart():
        for part in outer.iter_parts():
            if part.get_content_type() != "message/rfc822":
                continue
            payload = part.get_payload()
            if isinstance(payload, list) and payload and isinstance(payload[0], EmailMessage):
                found.append(payload[0])
    return found or [outer]


def header_date(msg: Message) -> date | None:
    """The calendar date of the `Date` header in its own offset, never converted; None if unparseable."""
    try:
        value = msg["Date"]
        if value is None:
            return None
        return parsedate_to_datetime(str(value)).date()
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def message_date(inner: Message, outer: Message, arrived: date) -> date:
    """The inner `Date`, else the outer's, else the server's arrival date (spec §4)."""
    return header_date(inner) or header_date(outer) or arrived


def subject_of(msg: Message) -> str | None:
    try:
        value = msg["Subject"]
        return " ".join(str(value).split()) if value is not None else None
    except Exception:  # a header the parser cannot render
        return None


def _plain(content: str) -> str:
    lines = "\n".join(line.rstrip() for line in content.splitlines())
    return re.sub(r"\n{3,}", "\n\n", lines).strip()


def body_text(msg: EmailMessage) -> str | None:
    """The HTML body through the converter, else the plain-text body; None where neither has text."""
    for kind in ("html", "plain"):
        try:
            part = msg.get_body(preferencelist=(kind,))
            if part is None:
                continue
            content = part.get_content()
        except (LookupError, ValueError, KeyError, AttributeError, TypeError):  # unknown charset, bad part
            continue
        if not isinstance(content, str):
            continue
        text = html_to_text(content) if kind == "html" else _plain(content)
        if text:
            return text
    return None


def pdf_parts(msg: EmailMessage) -> tuple[PdfPart, ...]:
    """The first three PDFs: `application/pdf`, or `application/octet-stream` named `.pdf`; attachments and
    inline parts alike."""
    found: list[PdfPart] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        try:
            name = part.get_filename()
            ctype = part.get_content_type()
            if not (
                ctype == "application/pdf"
                or (ctype == "application/octet-stream" and (name or "").lower().endswith(".pdf"))
            ):
                continue
            data = part.get_payload(decode=True)
        except (LookupError, ValueError, KeyError, AttributeError, TypeError):
            continue
        if isinstance(data, bytes) and data:
            found.append(PdfPart(name or "attachment.pdf", data))
            if len(found) == MAX_PDFS:
                break
    return tuple(found)
