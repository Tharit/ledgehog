"""Who may send (email.md §3): whole addresses (a plus address stands for its listed base),
case-insensitive, outer message only, authenticated."""

from __future__ import annotations

import pytest

from app.plugins.importers.email.senders import (
    Verdict,
    addresses_of,
    check_sender,
    is_accepted,
    parse_authentication_results,
)
from tests.plugins.importers.email.helpers import FAMILY, SHOP, make_message, with_raw_auth

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


# ---- authentication: the topmost Authentication-Results header -------------------------------------------

FWD = {"X-Forwarded-For": FAMILY}


def verdict(auth: str | None, *, sender: str = SHOP, headers: dict[str, str] | None = None) -> Verdict:
    return check_sender(make_message(sender=sender, headers=headers, auth=auth), ALLOWED)


def test_a_forward_by_hand_needs_dmarc_pass_for_its_listed_from():
    assert verdict("mx.x; dmarc=pass header.from=example.com", sender=FAMILY) is Verdict.ACCEPTED
    assert verdict("mx.x; dmarc=fail header.from=example.com", sender=FAMILY) is Verdict.NOT_AUTHENTICATED
    # a dmarc pass for another domain than the From's is no vouching for the From
    assert verdict("mx.x; dmarc=pass header.from=evil.example", sender=FAMILY) is Verdict.NOT_AUTHENTICATED


NETCUP = (
    "mxf914;\n"
    "    dkim=pass header.d=mkleinhans.de;\n"
    "    spf=pass (sender IP is 79.135.106.27) smtp.mailfrom=mail@mkleinhans.de\n"
    "    smtp.helo=mail-10627.protonmail.ch"
)


def by_hand(auth: str, *, sender: str = "mail@mkleinhans.de") -> Verdict:
    return check_sender(with_raw_auth(make_message(sender=sender, auth=None), auth), [sender])


def test_a_forward_by_hand_passes_on_an_aligned_dkim_signature_without_a_dmarc_result():
    assert by_hand(NETCUP) is Verdict.ACCEPTED
    assert by_hand(NETCUP.replace("dkim=pass", "dkim=fail")) is Verdict.NOT_AUTHENTICATED
    assert by_hand(NETCUP.replace("mkleinhans.de;\n    spf", "other.example;\n    spf")) is (
        Verdict.NOT_AUTHENTICATED
    )
    assert by_hand("mx.x; dmarc=pass header.from=mkleinhans.de") is Verdict.ACCEPTED
    assert by_hand("mx.x; spf=pass smtp.mailfrom=mail@mkleinhans.de") is Verdict.NOT_AUTHENTICATED


def test_a_forward_by_hand_aligns_dkim_on_a_parent_domain_that_has_a_dot():
    sender = "me@sub.example.org"
    assert by_hand("mx.x; dkim=pass header.d=example.org", sender=sender) is Verdict.ACCEPTED
    assert by_hand("mx.x; dkim=pass header.d=org", sender=sender) is Verdict.NOT_AUTHENTICATED
    assert by_hand("mx.x; dkim=pass header.d=evil.org", sender=sender) is Verdict.NOT_AUTHENTICATED


def test_an_automatic_forward_needs_the_shops_dkim_pass_and_a_forwarding_header():
    assert verdict("mx.x; dkim=pass header.d=shop.example", headers=FWD) is Verdict.ACCEPTED
    # nothing names a listed address
    assert verdict("mx.x; dkim=pass header.d=shop.example") is Verdict.NOT_ACCEPTED


def test_an_automatic_forward_with_an_arc_pass_is_accepted():
    assert verdict("mx.x; arc=pass smtp.remote-ip=1.2.3.4", headers=FWD) is Verdict.ACCEPTED
    assert verdict("mx.x; arc=fail", headers=FWD) is Verdict.NOT_AUTHENTICATED


def test_an_aligned_parent_domain_passes_but_not_a_sibling_or_a_longer_domain():
    from_ = "orders@mail.shop.example"
    assert verdict("mx.x; dkim=pass header.d=shop.example", sender=from_, headers=FWD) is Verdict.ACCEPTED
    for d in ("other.example", "ail.shop.example", "evilshop.example", "x.mail.shop.example", "example"):
        got = verdict(f"mx.x; dkim=pass header.d={d}", sender=from_, headers=FWD)
        assert got is Verdict.NOT_AUTHENTICATED


def test_a_failing_or_wrong_domain_dkim_is_not_authenticated():
    assert verdict("mx.x; dkim=fail header.d=shop.example", headers=FWD) is Verdict.NOT_AUTHENTICATED
    assert verdict("mx.x; dkim=pass header.d=evil.example", headers=FWD) is Verdict.NOT_AUTHENTICATED
    assert verdict("mx.x; spf=pass smtp.mailfrom=shop.example", headers=FWD) is Verdict.NOT_AUTHENTICATED


def test_no_header_is_not_authenticated_and_an_unlisted_message_is_not_accepted_either_way():
    assert verdict(None, headers=FWD) is Verdict.NOT_AUTHENTICATED
    assert verdict(None, sender=FAMILY) is Verdict.NOT_AUTHENTICATED
    assert verdict(None, sender="x@spam.example") is Verdict.NOT_ACCEPTED
    assert verdict("mx.x; dkim=pass header.d=spam.example", sender="x@spam.example") is Verdict.NOT_ACCEPTED


def test_only_the_topmost_header_counts():
    msg = make_message(sender=SHOP, headers=FWD, auth=None)
    msg["Authentication-Results"] = "mx.x; dkim=fail header.d=shop.example"  # topmost
    msg["Authentication-Results"] = "forged.example; dkim=pass header.d=shop.example"  # below it
    assert check_sender(msg, ALLOWED) is Verdict.NOT_AUTHENTICATED
    good = make_message(sender=SHOP, headers=FWD, auth=None)
    good["Authentication-Results"] = "mx.x; dkim=pass header.d=shop.example"
    good["Authentication-Results"] = "other.example; dkim=fail header.d=shop.example"
    assert check_sender(good, ALLOWED) is Verdict.ACCEPTED


def test_the_header_is_parsed_with_comments_quotes_and_several_results():
    value = (
        'mx.example.com 1; dkim=pass (2048-bit key; unprotected (nested)) header.d="Shop.Example" '
        "header.i=@shop.example header.b=abc; spf=pass smtp.mailfrom=shop.example; "
        "dmarc=pass (p=NONE sp=NONE) header.from=shop.example"
    )
    results = parse_authentication_results(value)
    assert [(r.method, r.result) for r in results] == [("dkim", "pass"), ("spf", "pass"), ("dmarc", "pass")]
    assert results[0].properties["header.d"] == "shop.example"
    assert parse_authentication_results("mx.example.com; none") == []
    assert parse_authentication_results("mx.example.com") == []


def test_a_comment_cannot_smuggle_a_pass():
    msg = make_message(sender=SHOP, headers=FWD, auth="mx.x; dkim=fail (dkim=pass header.d=shop.example)")
    assert check_sender(msg, ALLOWED) is Verdict.NOT_AUTHENTICATED


def test_an_escaped_quote_in_a_reason_cannot_forge_a_result():
    value = 'mx.x; dkim=fail reason="a\\"; dmarc=pass header.from=shop.com; x=\\""'
    results = parse_authentication_results(value)
    assert [(r.method, r.result) for r in results] == [("dkim", "fail")]
    assert not any(r.method == "dmarc" for r in results)


def test_escaped_quotes_stay_inside_the_value_and_a_later_section_still_splits():
    value = 'mx.x; dkim=fail reason="say \\"hi\\"" header.d=a.example; spf=pass smtp.mailfrom=a.example'
    results = parse_authentication_results(value)
    assert [(r.method, r.result) for r in results] == [("dkim", "fail"), ("spf", "pass")]
    assert results[0].properties["header.d"] == "a.example"


def test_nested_comments_and_escaped_parentheses_hide_semicolons_and_results():
    value = (
        "mx.x; dkim=fail (a (b; dmarc=pass) c; spf=pass) header.d=a.example; spf=pass (x \\) ; dmarc=pass)"
    )
    results = parse_authentication_results(value)
    assert [(r.method, r.result) for r in results] == [("dkim", "fail"), ("spf", "pass")]


# ---- plus addresses (email.md §3) ------------------------------------------------------------------------

PLUS = "family+amazon@example.com"
PASS = "mx.x; dmarc=pass header.from=example.com"


def test_a_plus_address_from_a_forward_by_hand_matches_the_listed_base():
    msg = make_message(sender=PLUS, auth=PASS)
    assert check_sender(msg, ALLOWED) is Verdict.ACCEPTED


@pytest.mark.parametrize("header", ["Delivered-To", "X-Forwarded-For", "X-Original-To"])
def test_a_plus_address_in_a_forwarding_header_matches_the_listed_base(header: str):
    assert is_accepted(make_message(sender=SHOP, headers={header: PLUS}), ALLOWED)


def test_a_listed_plus_address_matches_itself():
    listed = ["family+shop@example.com"]
    assert is_accepted(make_message(sender=SHOP, headers={"Delivered-To": listed[0]}), listed)
    assert is_accepted(make_message(sender=listed[0], auth=PASS), listed)


@pytest.mark.parametrize(
    "named", ["family+other@example.com", "family@example.com", "family+shop+x@example.com"]
)
def test_a_listed_plus_address_matches_neither_another_tag_nor_the_bare_base(named: str):
    listed = ["family+shop@example.com"]
    msg = make_message(sender=named, headers={"Delivered-To": named}, auth=PASS)
    assert check_sender(msg, listed) is Verdict.NOT_ACCEPTED


@pytest.mark.parametrize(
    "named", ["+tag@example.com", "+@example.com", "family+tag@example.org", "family+tag"]
)
def test_no_stripping_to_an_empty_local_part_or_across_domains(named: str):
    msg = make_message(sender=named, headers={"Delivered-To": named}, auth=PASS)
    assert check_sender(msg, ["@example.com", ALLOWED[0]]) is Verdict.NOT_ACCEPTED


def test_a_plus_address_that_fails_authentication_is_not_authenticated_not_unaccepted():
    bad = "mx.x; dmarc=fail header.from=example.com"
    assert check_sender(make_message(sender=PLUS, auth=bad), ALLOWED) is Verdict.NOT_AUTHENTICATED
    assert check_sender(make_message(sender=SHOP, headers={"Delivered-To": PLUS}, auth=None), ALLOWED) is (
        Verdict.NOT_AUTHENTICATED
    )


def test_a_local_part_holding_an_at_sign_is_not_stripped():
    odd = "family+x@evil.example@example.com"
    assert check_sender(make_message(sender=odd, auth=PASS), ALLOWED) is Verdict.NOT_ACCEPTED
    assert check_sender(make_message(sender=SHOP, headers={"Delivered-To": odd}, auth=PASS), ALLOWED) is (
        Verdict.NOT_ACCEPTED
    )
