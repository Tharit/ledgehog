"""The imaplib seam (email.md §2, §8) against a fake `imaplib` connection: no network."""

from __future__ import annotations

import imaplib
import ssl
from datetime import date
from typing import Any

import pytest

from app.core.plugins.errors import AuthRejected, InvalidProfile, SourceUnavailable
from app.core.plugins.fetch import SecretText
from app.plugins.importers.email import mailbox as mb
from app.plugins.importers.email.mailbox import Connection, connect_imap, encode_mailbox_name, search_date

FORBIDDEN = {"STORE", "COPY", "MOVE", "EXPUNGE", "APPEND", "DELETE", "RENAME", "CREATE", "SELECT"}


class FakeImap:
    """Just enough of `imaplib.IMAP4`; every command is appended to `events`."""

    error = imaplib.IMAP4.error
    abort = imaplib.IMAP4.abort
    events: list[tuple[Any, ...]] = []
    capabilities: tuple[str, ...] = ("IMAP4REV1", "STARTTLS")
    login_error: Exception | None = None
    connect_error: Exception | None = None
    folder_ok = True
    uidvalidity: list[Any] = [b"77"]
    search_answer: list[Any] = [b"3 9 4"]
    fetch_answers: dict[str, list[Any]] = {}

    def __init__(self, host: str, port: int = 143, **kw: Any) -> None:
        if FakeImap.connect_error:
            raise FakeImap.connect_error
        FakeImap.events.append(("connect", type(self).__name__, host, port, kw))

    def starttls(self, ssl_context: ssl.SSLContext | None = None) -> None:
        FakeImap.events.append(("starttls", ssl_context))

    def login(self, user: str, password: str) -> tuple[str, list[bytes]]:
        FakeImap.events.append(("login", user))
        if FakeImap.login_error:
            raise FakeImap.login_error
        return "OK", [b"done"]

    def select(self, mailbox: str = "INBOX", readonly: bool = False) -> tuple[str, list[bytes]]:
        FakeImap.events.append(("EXAMINE" if readonly else "SELECT", mailbox))
        return ("OK", [b"5"]) if FakeImap.folder_ok else ("NO", [b"nope"])

    def response(self, code: str) -> tuple[str, list[Any]]:
        FakeImap.events.append(("response", code))
        return code, FakeImap.uidvalidity

    def uid(self, command: str, *args: str) -> tuple[str, list[Any]]:
        FakeImap.events.append(("UID " + command, *args))
        if command == "SEARCH":
            return "OK", FakeImap.search_answer
        return "OK", FakeImap.fetch_answers.get(args[0], [None])

    def logout(self) -> tuple[str, list[bytes]]:
        FakeImap.events.append(("logout",))
        return "BYE", [b""]


class FakeImapSsl(FakeImap):
    pass


@pytest.fixture(autouse=True)
def fake_imap(monkeypatch: pytest.MonkeyPatch):
    for name, default in (
        ("events", []),
        ("capabilities", ("IMAP4REV1", "STARTTLS")),
        ("login_error", None),
        ("connect_error", None),
        ("folder_ok", True),
        ("uidvalidity", [b"77"]),
        ("search_answer", [b"3 9 4"]),
        ("fetch_answers", {}),
    ):
        monkeypatch.setattr(FakeImap, name, default)
    monkeypatch.setattr(mb.imaplib, "IMAP4", FakeImap)
    monkeypatch.setattr(mb.imaplib, "IMAP4_SSL", FakeImapSsl)


def conn(security: str = "tls", port: int | None = None) -> Connection:
    return Connection("imap.example.com", port or (993 if security == "tls" else 143), security, "household")


def kinds() -> list[str]:
    return [e[0] for e in FakeImap.events]


# ---- TLS or STARTTLS, certificates verified --------------------------------------------------------


def test_tls_is_implicit_tls_with_verification_and_a_timeout():
    connect_imap(conn("tls"), SecretText("pw"))
    (_, cls, host, port, kw), login = FakeImap.events[0], FakeImap.events[1]
    assert (cls, host, port) == ("FakeImapSsl", "imap.example.com", 993)
    assert kw["timeout"] == 30.0
    ctx = kw["ssl_context"]
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is True
    assert login == ("login", "household") and "starttls" not in kinds()


def test_starttls_upgrades_with_a_verified_context_before_the_login():
    connect_imap(conn("starttls"), SecretText("pw"))
    assert kinds()[:3] == ["connect", "starttls", "login"]
    assert FakeImap.events[0][1:4] == ("FakeImap", "imap.example.com", 143)
    ctx = FakeImap.events[1][1]
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is True


def test_starttls_without_the_capability_is_invalid_security_and_never_logs_in():
    FakeImap.capabilities = ("IMAP4REV1",)
    with pytest.raises(InvalidProfile, match="security"):
        connect_imap(conn("starttls"), SecretText("pw"))
    assert "login" not in kinds() and "starttls" not in kinds()


def test_a_refused_login_is_auth_rejected_without_the_password():
    FakeImap.login_error = imaplib.IMAP4.error("[AUTHENTICATIONFAILED] bad pw-secret")
    with pytest.raises(AuthRejected) as err:
        connect_imap(conn(), SecretText("pw-secret"))
    assert "pw-secret" not in str(err.value) and "logout" in kinds()


def test_an_unreachable_server_a_failed_handshake_and_a_timeout_are_source_unavailable():
    for exc in (
        ConnectionRefusedError(),
        ssl.SSLCertVerificationError("bad cert"),
        TimeoutError(),
        OSError(),
    ):
        FakeImap.connect_error = exc
        with pytest.raises(SourceUnavailable):
            connect_imap(conn(), SecretText("pw"))


def test_a_dropped_connection_during_login_is_source_unavailable_not_a_rejection():
    FakeImap.login_error = imaplib.IMAP4.abort("socket error: EOF")
    with pytest.raises(SourceUnavailable):
        connect_imap(conn(), SecretText("pw"))


# ---- read-only ---------------------------------------------------------------------------------------


def test_the_mailbox_is_examined_read_only_with_its_uidvalidity():
    box = connect_imap(conn(), SecretText("pw"))
    assert box.examine("Receipts") == 77
    assert ("EXAMINE", '"Receipts"') in FakeImap.events and "SELECT" not in kinds()


def test_a_missing_mailbox_is_invalid_naming_mailbox():
    FakeImap.folder_ok = False
    box = connect_imap(conn(), SecretText("pw"))
    with pytest.raises(InvalidProfile, match="mailbox"):
        box.examine("Nope")


def test_a_non_ascii_folder_name_is_sent_in_modified_utf7_quoted():
    box = connect_imap(conn(), SecretText("pw"))
    box.examine("Entwürfe")
    assert ("EXAMINE", '"Entw&APw-rfe"') in FakeImap.events


def test_only_peek_and_search_commands_are_ever_sent():
    FakeImap.fetch_answers = {
        "5": [(b'1 (UID 5 INTERNALDATE "05-Jan-2026 10:00:00 +0100" BODY[] {7}', b"Subject:"), b")"],
    }
    box = connect_imap(conn(), SecretText("pw"))
    box.examine("INBOX")
    box.uids_after(2)
    box.uids_since(date(2026, 1, 3))
    box.header_message_id(5)
    box.size(5)
    box.fetch(5)
    box.logout()
    sent = [e for e in FakeImap.events if str(e[0]).startswith("UID ") or e[0] in FORBIDDEN]
    assert not [e for e in sent if e[0] in FORBIDDEN]
    fetches = [e for e in sent if e[0] == "UID FETCH"]
    assert len(fetches) == 3
    for e in fetches:
        assert "BODY.PEEK[" in e[2] or e[2] == "(RFC822.SIZE)", e
        assert "BODY[" not in e[2].replace("BODY.PEEK[", "")


# ---- searches, fetches ------------------------------------------------------------------------------


def test_uids_after_filters_the_answer_because_n_star_answers_the_highest_even_when_lower():
    FakeImap.search_answer = [b"3"]  # `UID SEARCH UID 8:*` of a mailbox whose highest UID is 3
    box = connect_imap(conn(), SecretText("pw"))
    assert box.uids_after(7) == []
    assert ("UID SEARCH", "UID", "8:*") in FakeImap.events
    FakeImap.search_answer = [b"9 3 12"]
    assert box.uids_after(2) == [3, 9, 12]


def test_an_empty_search_answer_is_no_uids():
    box = connect_imap(conn(), SecretText("pw"))
    for answer in ([b""], [None], []):
        FakeImap.search_answer = answer
        assert box.uids_since(date(2026, 1, 1)) == []
    assert ("UID SEARCH", "SINCE", "01-Jan-2026") in FakeImap.events


def test_size_header_and_the_message_are_read_from_the_fetch_responses():
    FakeImap.fetch_answers = {
        "5": [(b"1 (UID 5 RFC822.SIZE 4242)", b"")],
    }
    box = connect_imap(conn(), SecretText("pw"))
    assert box.size(5) == 4242 and box.size(6) is None
    FakeImap.fetch_answers = {
        "5": [(b"1 (UID 5 BODY[HEADER.FIELDS (MESSAGE-ID)] {30}", b"Message-ID: <a@b>\r\n\r\n"), b")"]
    }
    assert box.header_message_id(5) == "<a@b>"
    FakeImap.fetch_answers = {"5": [(b"1 (UID 5 BODY[HEADER.FIELDS (MESSAGE-ID)] {4}", b"\r\n\r\n"), b")"]}
    assert box.header_message_id(5) is None
    FakeImap.fetch_answers = {
        "5": [(b'1 (UID 5 INTERNALDATE " 5-Jan-2026 23:30:00 -0500" BODY[] {5}', b"hello"), b")"]
    }
    got = box.fetch(5)
    assert (
        got is not None and got.raw == b"hello" and got.arrived == date(2026, 1, 5)
    )  # as the server wrote it
    assert box.fetch(6) is None


def test_a_server_that_drops_the_session_mid_run_is_source_unavailable():
    box = connect_imap(conn(), SecretText("pw"))

    def boom(*a: Any) -> Any:
        raise imaplib.IMAP4.abort("EOF")

    FakeImap.uid = boom  # type: ignore[method-assign,assignment]
    try:
        with pytest.raises(SourceUnavailable):
            box.uids_since(date(2026, 1, 1))
    finally:
        del FakeImap.uid  # back to the class's own method


# ---- encodings ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "encoded"),
    [
        ("INBOX", '"INBOX"'),
        ("a&b", '"a&-b"'),
        ("Entwürfe", '"Entw&APw-rfe"'),
        ("日本語", '"&ZeVnLIqe-"'),
        ("A/日b", '"A/&ZeU-b"'),
        ('we"ird\\', '"we\\"ird\\\\"'),
    ],
)
def test_mailbox_names_are_modified_utf7_and_quoted(name: str, encoded: str):
    assert encode_mailbox_name(name) == encoded


def test_search_dates_use_english_month_names():
    assert search_date(date(2026, 3, 4)) == "04-Mar-2026" and search_date(date(2026, 12, 31)) == "31-Dec-2026"
