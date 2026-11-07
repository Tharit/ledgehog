"""Hand-built messages, a fake mailbox, a stub extractor and builder: no network, no model."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any

from app.core.plugins.errors import InvalidProfile
from app.core.plugins.fetch import Answer, Prompt, SecretText
from app.core.plugins.importer import IncomingDocument, IncomingDocumentLine
from app.plugins.importers.email.extractor import (
    Extraction,
    MessageContext,
    Skipped,
)
from app.plugins.importers.email.importer import EmailImporter
from app.plugins.importers.email.mailbox import Connection, RawMessage
from app.plugins.importers.email.message import PdfPart

TODAY = date(2026, 1, 20)
SINCE = date(2026, 1, 1)
FAMILY = "family@example.com"
SHOP = "orders@shop.example"
AUTO = "<auto>"  # make_message: write a passing Authentication-Results


def base_settings(**over: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "host": "imap.example.com",
        "security": "tls",
        "username": "household",
        "senders": [FAMILY],
        "start_date": SINCE.isoformat(),
    }
    out.update(over)
    return {k: v for k, v in out.items() if v is not None}


def make_message(
    *,
    sender: str = SHOP,
    subject: str = "Your order",
    sent: str | None = "Mon, 5 Jan 2026 10:00:00 +0000",
    message_id: str | None = "<m1@shop.example>",
    html: str | None = "<p>Order 1</p>",
    text: str | None = "plain body",
    headers: Mapping[str, str] | None = None,
    pdfs: Sequence[tuple[str, str, str]] = (),
    attached: Sequence[EmailMessage] = (),
    auth: str | None = AUTO,
) -> EmailMessage:
    """`auth` is the Authentication-Results header: by default a passing one (DMARC for a listed `From`, else
    DKIM for the sender's domain); None writes none."""
    m = EmailMessage()
    if auth == AUTO:
        address = parseaddr(sender)[1].lower()
        domain = address.rpartition("@")[2]
        auth = (
            f"mx.example.com; dmarc=pass header.from={domain}"
            if address == FAMILY
            else f"mx.example.com; dkim=pass header.d={domain}"
        )
    if auth is not None:
        m["Authentication-Results"] = auth
    m["From"] = sender
    m["To"] = "household@example.com"
    m["Subject"] = subject
    if sent is not None:
        m["Date"] = sent
    if message_id is not None:
        m["Message-ID"] = message_id
    for name, value in (headers or {}).items():
        m[name] = value
    if text is not None:
        m.set_content(text)
        if html is not None:
            m.add_alternative(html, subtype="html")
    elif html is not None:
        m.set_content(html, subtype="html")
    for name, maintype, subtype in pdfs:
        m.add_attachment(b"%PDF-1.4 " + name.encode(), maintype=maintype, subtype=subtype, filename=name)
    for inner in attached:
        m.add_attachment(inner)
    return m


def with_raw_auth(msg: EmailMessage, raw: str) -> EmailMessage:
    """`msg` parsed off the wire with `raw` (folded lines allowed) as its topmost Authentication-Results."""
    from app.plugins.importers.email.message import parse_message

    return parse_message(
        b"Authentication-Results: " + raw.replace("\n", "\r\n").encode() + b"\r\n" + msg.as_bytes()
    )


def forward_by_hand(
    inner: EmailMessage, *, sender: str = FAMILY, message_id: str = "<fwd@family>"
) -> EmailMessage:
    return make_message(
        sender=sender,
        subject="Fwd: " + str(inner["Subject"]),
        message_id=message_id,
        html=None,
        text="see attached",
        attached=[inner],
    )


class FakeMailbox:
    """Satisfies `Mailbox`: UID -> (message, arrival date); records every call."""

    def __init__(
        self,
        messages: Mapping[int, tuple[EmailMessage | bytes, date]] | None = None,
        *,
        uidvalidity: int = 1,
        sizes: Mapping[int, int] | None = None,
        missing_folder: bool = False,
        uidnext: int | None = None,
    ) -> None:
        self._uidnext = uidnext
        self.messages: dict[int, tuple[EmailMessage | bytes, date]] = dict(messages or {})
        self.uidvalidity = uidvalidity
        self.sizes = dict(sizes or {})
        self.missing_folder = missing_folder
        self.calls: list[tuple[Any, ...]] = []
        self.logged_out = 0
        self.logout_error: Exception | None = None

    def add(self, uid: int, message: EmailMessage | bytes, arrived: date = date(2026, 1, 6)) -> None:
        self.messages[uid] = (message, arrived)

    def _raw(self, uid: int) -> bytes:
        m = self.messages[uid][0]
        return m if isinstance(m, bytes) else m.as_bytes()

    def examine(self, name: str) -> int:
        self.calls.append(("examine", name))
        if self.missing_folder:
            raise InvalidProfile("mailbox: the folder does not exist")
        return self.uidvalidity

    def uidnext(self) -> int:
        self.calls.append(("uidnext",))
        return self._uidnext if self._uidnext is not None else max(self.messages, default=0) + 1

    def uids_after(self, uid: int) -> list[int]:
        self.calls.append(("uids_after", uid))
        return sorted(u for u in self.messages if u > uid)

    def uids_since(self, day: date) -> list[int]:
        self.calls.append(("uids_since", day))
        return sorted(u for u, (_, arrived) in self.messages.items() if arrived >= day)

    def header_message_id(self, uid: int) -> str | None:
        self.calls.append(("header", uid))
        import email

        value = email.message_from_bytes(self._raw(uid))["Message-ID"]
        return None if value is None else str(value)

    def size(self, uid: int) -> int | None:
        self.calls.append(("size", uid))
        if uid not in self.messages:
            return None
        return self.sizes.get(uid, len(self._raw(uid)))

    def fetch(self, uid: int) -> RawMessage | None:
        self.calls.append(("fetch", uid))
        if uid not in self.messages:
            return None
        return RawMessage(self._raw(uid), self.messages[uid][1])

    def logout(self) -> None:
        self.logged_out += 1
        if self.logout_error:
            raise self.logout_error

    def fetched(self) -> list[int]:
        return [c[1] for c in self.calls if c[0] == "fetch"]


class Scripted:
    """A prompter answering the password; records what it was asked."""

    def __init__(self, answer: Answer = None) -> None:
        self.answer: Answer = SecretText("pw") if answer is None else answer
        self.asked: list[Prompt] = []

    def ask(
        self, prompt: Prompt, *, poll: Callable[[], bool] | None = None, timeout_s: float | None = None
    ) -> Answer:
        self.asked.append(prompt)
        return self.answer


@dataclass
class StubExtractor:
    """Records (text, pdfs); answers from `reply`, which may return a result or raise."""

    reply: Callable[[str | None, Sequence[PdfPart]], Extraction | Skipped] | None = None
    calls: list[tuple[str | None, tuple[PdfPart, ...]]] = field(default_factory=list)

    def extract(
        self,
        text: str | None,
        pdfs: Sequence[PdfPart],
        *,
        accept: Callable[[Extraction], bool] = lambda extraction: True,
    ) -> Extraction | Skipped:
        self.calls.append((text, tuple(pdfs)))
        if self.reply is not None:
            return self.reply(text, pdfs)
        return Extraction({"merchant": "Shop", "order_id": None, "total": 1}, "text", model="stub")


@dataclass
class StubBuilder:
    """A document per extraction: provider from `merchant`, `source_id` from `order_id` else the message."""

    seen: list[MessageContext] = field(default_factory=list)
    minor_units: list[Callable[[str], int]] = field(default_factory=list)

    def build(
        self, extraction: Extraction, context: MessageContext, *, minor_units_of: Callable[[str], int]
    ) -> IncomingDocument | Skipped:
        self.seen.append(context)
        self.minor_units.append(minor_units_of)
        a = extraction.answer
        return IncomingDocument(
            provider=str(a["merchant"]),
            source_id=str(a.get("order_id") or f"message:{context.identity}"),
            occurred_on=context.date,
            total_minor=-100,
            currency="EUR",
            raw={"uid": context.uid},
            title=context.subject,
            lines=(IncomingDocumentLine("Item", -100, 1),),
        )


class Rig:
    """An importer wired to a fake mailbox, with the stubs and the state a run keeps."""

    def __init__(self, mailbox: FakeMailbox | None = None, *, extractor: StubExtractor | None = None) -> None:
        self.mailbox = mailbox or FakeMailbox()
        self.extractor = extractor or StubExtractor()
        self.builder = StubBuilder()
        self.connections: list[tuple[Connection, SecretText]] = []
        self.prompter = Scripted()
        self.importer = EmailImporter(self.extractor, self.builder, connect=self._connect)
        self.state: dict[str, Any] = {}
        self.progress: list[tuple[int, int]] = []

    def _connect(self, connection: Connection, password: SecretText) -> FakeMailbox:
        self.connections.append((connection, password))
        return self.mailbox

    def run(self, settings: Mapping[str, Any] | None = None, *, today: date = TODAY, since: date = SINCE):  # type: ignore[no-untyped-def]
        session = self.importer.open(settings or base_settings(), self.state, self.prompter, today=today)
        try:
            return session.fetch_documents(
                since=since,
                today=today,
                minor_units_of=lambda c: 2,
                progress=lambda d, t: self.progress.append((d, t)),
            )
        finally:
            session.close()

    def run_and_apply(self, settings: Mapping[str, Any] | None = None, **kw: Any):  # type: ignore[no-untyped-def]
        delivery = self.run(settings, **kw)
        assert delivery.position is not None
        self.state.update(delivery.position)  # what the runner does once the documents are written
        return delivery
