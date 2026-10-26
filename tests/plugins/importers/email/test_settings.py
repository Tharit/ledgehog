"""The email importer's settings (email.md §1)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.core.plugins.errors import InvalidProfile
from app.core.plugins.fetch import FetchImporter
from app.plugins.importers.email.settings import parse_settings
from tests.plugins.importers.email.helpers import FAMILY, Rig, base_settings


def bad(key: str, **over: Any) -> None:
    with pytest.raises(InvalidProfile, match=key):
        parse_settings(base_settings(**over))


def test_a_complete_profile_is_typed_with_its_defaults():
    s = parse_settings(base_settings())
    assert (s.host, s.security, s.port, s.username, s.mailbox) == (
        "imap.example.com",
        "tls",
        993,
        "household",
        "INBOX",
    )
    assert s.senders == {FAMILY} and s.start_date == date(2026, 1, 1)


def test_the_default_port_follows_the_security_and_an_explicit_port_wins():
    assert parse_settings(base_settings(security="starttls")).port == 143
    assert parse_settings(base_settings(security="starttls", port=1143)).port == 1143
    assert parse_settings(base_settings(port="")).port == 993
    assert parse_settings(base_settings(port=None)).port == 993


@pytest.mark.parametrize("port", [0, 65536, -1, "993", 99.5, True])
def test_a_port_outside_1_to_65535_is_refused(port: Any):
    bad("port", port=port)


@pytest.mark.parametrize("security", [None, "", "ssl", "none", "TLS", 1])
def test_there_is_no_unencrypted_option(security: Any):
    with pytest.raises(InvalidProfile, match="security"):
        parse_settings({**base_settings(), "security": security})


@pytest.mark.parametrize(
    "host", ["imap://x.com", "x.com:993", "user@x.com", "x.com/path", "my host", "", "   "]
)
def test_the_host_is_a_host_only(host: str):
    bad("host", host=host)


def test_the_username_is_required():
    bad("username", username="  ")


def test_the_mailbox_is_optional_and_trimmed_and_has_no_control_characters():
    assert parse_settings(base_settings(mailbox="  Receipts ")).mailbox == "Receipts"
    assert parse_settings(base_settings(mailbox="")).mailbox == "INBOX"
    bad("mailbox", mailbox="IN\r\nBOX")


def test_senders_need_one_address_each_without_duplicates_and_are_normalised():
    assert parse_settings(base_settings(senders=["  Family@Example.com "])).senders == {FAMILY}
    bad("senders", senders=[])
    bad("senders", senders="family@example.com")
    bad("senders", senders=["not an address"])
    bad("senders", senders=["a@b.com, c@d.com"])
    bad("senders", senders=["Name <a@b.com>"])
    bad("senders", senders=["a@b.com", "A@B.com"])


@pytest.mark.parametrize("start", [None, "", "yesterday", "2026-13-01", 20260101])
def test_the_start_date_is_required_and_an_iso_date(start: Any):
    with pytest.raises(InvalidProfile, match="start_date"):
        parse_settings({**base_settings(), "start_date": start})


def test_an_unknown_key_is_refused_by_name():
    with pytest.raises(InvalidProfile, match="password"):
        parse_settings(base_settings(password="x"))


def test_an_error_never_quotes_a_value():
    with pytest.raises(InvalidProfile) as err:
        parse_settings(base_settings(senders=["secret.name@example.com", "x"], username="u"))
    assert "secret.name" not in str(err.value)


def test_the_importer_is_a_fetch_importer_for_documents():
    imp = Rig().importer
    assert isinstance(imp, FetchImporter)
    assert imp.emits == {"documents"} and imp.providers == frozenset()
    imp.validate_settings(base_settings())
    with pytest.raises(InvalidProfile):
        imp.validate_settings({})
    assert imp.default_fetch_start(base_settings(start_date="2026-03-04"), today=date(2026, 9, 9)) == date(
        2026, 3, 4
    )
