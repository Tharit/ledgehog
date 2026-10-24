"""The email importer (spec/plugins/importers/email.md): reads receipts from one IMAP mailbox.

This module is the mailbox side: settings, the password asked per sync, which messages are read, the guard,
inner messages, the position. What a message's text and PDFs become — the model, completeness, the provider —
is behind `Extractor` and `DocumentBuilder` (extractor.py).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, MutableMapping
from datetime import date, timedelta
from email.message import EmailMessage
from typing import Any

from app.core.plugins.errors import ChallengeAbandoned
from app.core.plugins.fetch import FetchSession, FetchSessionBase, Prompter, SecretPrompt, SecretText
from app.core.plugins.importer import DocumentDelivery, IncomingDocument
from app.plugins.importers.email.extractor import (
    ALREADY_SEEN,
    BEFORE_START,
    DOCUMENTS,
    GAVE_UP,
    NO_CONTENT,
    NOT_ACCEPTED,
    STAT_KEYS,
    SUPERSEDED,
    TOO_LARGE,
    AttemptFailed,
    DocumentBuilder,
    Extraction,
    Extractor,
    MessageContext,
    Skipped,
)
from app.plugins.importers.email.mailbox import Connect, Connection, Mailbox, connect_imap
from app.plugins.importers.email.message import (
    body_text,
    identity_of,
    inner_messages,
    message_date,
    normalise_message_id,
    parse_message,
    pdf_parts,
    subject_of,
)
from app.plugins.importers.email.position import (
    Position,
    fingerprint,
    position_update,
    read_position,
    record_failure,
)
from app.plugins.importers.email.senders import is_accepted
from app.plugins.importers.email.settings import EmailSettings, parse_settings

log = logging.getLogger("ledgehog.email")

MAX_MESSAGE_BYTES = 25 * 1024 * 1024
MAX_TEXT_CHARS = 40_000
COVERAGE_LAG_DAYS = 2  # the day before the fetch, less one day for forwarding


class _Session(FetchSessionBase):
    def __init__(
        self,
        importer: EmailImporter,
        settings: EmailSettings,
        state: MutableMapping[str, Any],
        mailbox: Mailbox,
        uidvalidity: int,
    ) -> None:
        self._importer = importer
        self._settings = settings
        self._state = state
        self._mailbox = mailbox
        self._uidvalidity = uidvalidity

    def close(self) -> None:
        try:
            self._mailbox.logout()
        except Exception as exc:  # an error closing is logged by type and dropped
            log.info("closing the mail connection failed: %s", type(exc).__name__)

    def fetch_documents(
        self, *, since: date, today: date, minor_units_of: Callable[[str], int]
    ) -> DocumentDelivery:
        run = _Run(self, since, today, minor_units_of)
        return run.deliver()


class _Run:
    """One `fetch_documents`: the candidates, each handled once, the delivery with its counts and position."""

    def __init__(
        self, session: _Session, since: date, today: date, minor_units_of: Callable[[str], int]
    ) -> None:
        self.session = session
        self.mailbox = session._mailbox
        self.settings = session._settings
        self.state = session._state
        self.uidvalidity = session._uidvalidity
        self.extractor: Extractor = session._importer.extractor
        self.builder: DocumentBuilder = session._importer.builder
        self.since = since
        self.today = today
        self.minor_units_of = minor_units_of
        self.stats: dict[str, int] = dict.fromkeys(STAT_KEYS, 0)
        self.documents: dict[tuple[str, str], IncomingDocument] = {}
        self.seen_before: Mapping[str, date] = {}
        self.seen_now: dict[str, date] = {}

    # -- the run ------------------------------------------------------------------------------------

    def candidates(self, position: Position | None) -> list[int]:
        """The union of §2: after the position, the overlap, and the first-run search."""
        if position is None:
            return self.mailbox.uids_since(self.since - timedelta(days=1))
        overlap = self.mailbox.uids_since(position.fetched_on - timedelta(days=1))
        if position.uidvalidity != self.uidvalidity:
            return sorted(set(overlap))
        return sorted(set(self.mailbox.uids_after(position.last_uid)) | set(overlap))

    def deliver(self) -> DocumentDelivery:
        position = read_position(self.state, self.settings)
        if position is None:
            if "position_for" in self.state:  # built for other settings: its UIDs mean nothing here
                self.state.pop("stuck", None)
        else:
            self.seen_before = position.seen
        if position is not None and position.uidvalidity == self.uidvalidity:
            last_uid = position.last_uid
        else:
            # a first read, or the mailbox was renumbered: mail before the start date is never read, so the
            # next run begins at what is there now, not at the first message handled
            last_uid = max(self.mailbox.uidnext() - 1, 0)
        for uid in self.candidates(position):
            self.handle(uid)
            last_uid = max(last_uid, uid)
        self.state.pop("stuck", None)  # the run got past every message
        self.stats[DOCUMENTS] = len(self.documents)
        log.info("run: %s", ", ".join(f"{k}={v}" for k, v in self.stats.items() if v))
        covered_through = self.today - timedelta(days=COVERAGE_LAG_DAYS)
        return DocumentDelivery(
            documents=tuple(self.documents.values()),
            covered_through=covered_through,
            covered_from=min(self.since, covered_through),
            importer_stats=dict(self.stats),
            position=position_update(
                self.settings,
                uidvalidity=self.uidvalidity,
                last_uid=last_uid,
                today=self.today,
                seen={**self.seen_before, **self.seen_now},
            ),
        )

    # -- one message --------------------------------------------------------------------------------

    def count(self, uid: int, outcome: str) -> None:
        self.stats[outcome] += 1
        log.info("uid %s: %s", uid, outcome)

    def is_seen(self, identity: str) -> bool:
        fp = fingerprint(identity)
        return fp in self.seen_before or fp in self.seen_now

    def remember(self, identity: str) -> None:
        self.seen_now.setdefault(fingerprint(identity), self.today)

    def handle(self, uid: int) -> None:
        header_id = normalise_message_id(self.mailbox.header_message_id(uid))
        if header_id is not None and self.is_seen(header_id):
            self.count(uid, ALREADY_SEEN)  # skipped on its headers: the body is never fetched
            return
        size = self.mailbox.size(uid)
        if size is None:
            log.info("uid %s: gone", uid)
            return
        if size > MAX_MESSAGE_BYTES:
            self.count(uid, TOO_LARGE)
            if header_id is not None:
                self.remember(header_id)
            return
        fetched = self.mailbox.fetch(uid)
        if fetched is None:
            log.info("uid %s: gone", uid)
            return
        outer = parse_message(fetched.raw)
        outer_id = identity_of(outer, fetched.raw)
        if header_id is None and self.is_seen(outer_id):  # no Message-ID: the hash of its bytes
            self.count(uid, ALREADY_SEEN)
            return
        self.remember(outer_id)
        if not is_accepted(outer, self.settings.senders):
            self.count(uid, NOT_ACCEPTED)
            return
        for inner in inner_messages(outer):
            inner_id = outer_id if inner is outer else identity_of(inner)
            if inner is not outer:
                if self.is_seen(inner_id):
                    self.count(uid, ALREADY_SEEN)
                    continue
                self.remember(inner_id)
            self.handle_inner(uid, outer, inner, inner_id, outer_id, fetched.arrived)

    def handle_inner(
        self, uid: int, outer: EmailMessage, inner: EmailMessage, inner_id: str, outer_id: str, arrived: date
    ) -> None:
        day = message_date(inner, outer, arrived)
        if day < self.since:
            self.count(uid, BEFORE_START)
            return
        text = body_text(inner)
        pdfs = pdf_parts(inner)
        if text is not None and len(text) > MAX_TEXT_CHARS:
            if not pdfs:
                self.count(uid, TOO_LARGE)
                return
            text = None  # too long to send: the PDFs are what is read
        if text is None and not pdfs:
            self.count(uid, NO_CONTENT)
            return
        context = MessageContext(
            identity=inner_id,
            outer_identity=outer_id,
            uid=uid,
            uidvalidity=self.uidvalidity,
            date=day,
            subject=subject_of(inner),
        )

        def build(extraction: Extraction) -> IncomingDocument | Skipped:
            return self.builder.build(extraction, context, minor_units_of=self.minor_units_of)

        try:
            extraction = self.extractor.extract(
                text, pdfs, accept=lambda e: not isinstance(build(e), Skipped)
            )
            result = extraction if isinstance(extraction, Skipped) else build(extraction)
        except AttemptFailed:
            if not record_failure(self.state, uid, self.uidvalidity):
                raise  # the run fails; `stuck` is written, the position stays
            self.count(uid, GAVE_UP)
            return
        if isinstance(result, Skipped):
            self.count(uid, result.reason)
            return
        key = (result.provider, result.external_id)
        if self.documents.pop(key, None) is not None:  # the later one by UID, then by order, wins
            self.stats[SUPERSEDED] += 1
        self.documents[key] = result
        log.info("uid %s: document", uid)


class EmailImporter:
    """Satisfies `FetchImporter` (documents only). Reads neither the database nor the clock."""

    emits: frozenset[str] = frozenset({"documents"})
    providers: frozenset[str] = frozenset()

    def __init__(
        self, extractor: Extractor, builder: DocumentBuilder, *, connect: Connect = connect_imap
    ) -> None:
        self.extractor = extractor
        self.builder = builder
        self._connect = connect

    def delivers(self, settings: Mapping[str, Any], provider: str) -> bool:
        return True  # receipts come from any shop (spec §7)

    def validate_settings(self, settings: Mapping[str, Any]) -> None:
        parse_settings(settings)

    def default_fetch_start(self, settings: Mapping[str, Any], *, today: date) -> date:
        return parse_settings(settings).start_date

    def open(
        self,
        settings: Mapping[str, Any],
        state: MutableMapping[str, Any],
        prompter: Prompter,
        *,
        today: date,
    ) -> FetchSession:
        parsed = parse_settings(settings)
        password = prompter.ask(SecretPrompt("password"))  # before anything touches the network
        if not isinstance(password, SecretText) or not password:
            raise ChallengeAbandoned("no password was given")
        mailbox = self._connect(
            Connection(parsed.host, parsed.port, parsed.security, parsed.username), password
        )
        try:
            uidvalidity = mailbox.examine(parsed.mailbox)
        except BaseException:
            try:
                mailbox.logout()
            except Exception as exc:
                log.info("closing the mail connection failed: %s", type(exc).__name__)
            raise
        return _Session(self, parsed, state, mailbox, uidvalidity)
