"""The sender guard (email.md §3): whole addresses, case-insensitive, outer message only."""

from __future__ import annotations

import pytest

from app.plugins.importers.email.senders import addresses_of, is_accepted
from tests.plugins.importers.email.helpers import FAMILY, SHOP, make_message

ALLOWED = [FAMILY]


@pytest.mark.parametrize(
    ("headers", "sender"),
    [
        ({}, FAMILY),  # a forward by hand: From the forwarder
        ({"Resent-From": FAMILY}, SHOP),
        ({"Resent-Sender": f"Mum <{FAMILY}>"}, SHOP),
        ({"X-Forwarded-For": f"{FAMILY} dedicated@inbox.example"}, SHOP),  # Gmail: forwarder destination
        ({"X-MS-Exchange-Inbox-Rules-Loop": FAMILY}, SHOP),
        ({"Delivered-To": FAMILY}, SHOP),
        ({"X-Original-To": FAMILY}, SHOP),
    ],
)
def test_each_header_the_guard_reads_accepts(headers: dict[str, str], sender: str):
    assert is_accepted(make_message(sender=sender, headers=headers), ALLOWED)


def test_the_match_ignores_case_in_the_message_and_in_the_list():
    msg = make_message(sender=SHOP, headers={"Delivered-To": "Family@Example.COM"})
    assert is_accepted(msg, ["FAMILY@example.com"])


def test_every_occurrence_of_delivered_to_counts():
    msg = make_message(sender=SHOP)
    msg["Delivered-To"] = "a@hop.example"
    msg["Delivered-To"] = FAMILY
    assert is_accepted(msg, ALLOWED)


def test_a_display_name_that_contains_an_address_does_not_count():
    assert not is_accepted(make_message(sender=f'"{FAMILY}" <spam@evil.example>'), ALLOWED)
    assert addresses_of(make_message(sender=f'"{FAMILY}" <spam@evil.example>')) == {"spam@evil.example"}


@pytest.mark.parametrize(
    "other",
    [
        "family+shop@example.com",
        "xfamily@example.com",
        "family@mail.example.com",
        "family@example.com.evil.example",
        "fam.ily@example.com",
    ],
)
def test_only_whole_addresses_match_so_an_alias_is_its_own_entry(other: str):
    assert not is_accepted(make_message(sender=other, headers={"Delivered-To": other}), ALLOWED)


def test_an_unlisted_message_is_not_accepted_and_the_to_header_is_not_read():
    msg = make_message(sender="newsletter@spam.example")
    msg.replace_header("To", FAMILY)
    msg["Cc"] = FAMILY
    assert not is_accepted(msg, ALLOWED)


def test_a_header_with_several_addresses_is_read_for_each():
    msg = make_message(sender=SHOP, headers={"X-Forwarded-For": f"a@one.example, {FAMILY}; b@two.example"})
    assert FAMILY in addresses_of(msg) and "b@two.example" in addresses_of(msg)
