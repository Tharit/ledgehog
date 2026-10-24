"""The mailbox side end to end through stubs: candidates, position, seen, guard, inner messages, counts."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import pytest

from app.core.plugins.errors import AuthRejected, ChallengeAbandoned, InvalidProfile
from app.core.plugins.fetch import SecretPrompt, SecretText
from app.plugins.importers.email.extractor import STAT_KEYS, Extraction, Skipped
from app.plugins.importers.email.mailbox import Connection
from app.plugins.importers.email.position import fingerprint, position_for
from app.plugins.importers.email.settings import parse_settings
from tests.plugins.importers.email.helpers import (
    FAMILY,
    SHOP,
    SINCE,
    TODAY,
    FakeMailbox,
    Rig,
    base_settings,
    forward_by_hand,
    make_message,
)

ARRIVED = date(2026, 1, 6)


def order(n: int, *, sender: str = SHOP, sent: str = "Mon, 5 Jan 2026 10:00:00 +0000", **kw: Any):  # type: ignore[no-untyped-def]
    return make_message(sender=sender, message_id=f"<o{n}@shop>", subject=f"Order {n}", sent=sent, **kw)


def accepted(n: int, **kw: Any):  # type: ignore[no-untyped-def]
    return order(n, headers={"Delivered-To": FAMILY}, **kw)


def rig_with(*uids: int, **kw: Any) -> Rig:
    box = FakeMailbox(**kw)
    for uid in uids:
        box.add(uid, accepted(uid), ARRIVED)
    return Rig(box)


# ---- open: the password, the connection -------------------------------------------------------------


def test_the_password_is_asked_as_a_secret_before_anything_touches_the_network():
    rig = rig_with()
    order_of: list[str] = []
    rig.prompter.ask = lambda prompt, **kw: order_of.append("ask") or SecretText("pw")  # type: ignore[method-assign,assignment,func-returns-value]
    rig.importer._connect = lambda c, p: order_of.append("connect") or rig.mailbox  # type: ignore[assignment,func-returns-value]
    rig.run()
    assert order_of == ["ask", "connect"]


def test_the_prompt_subject_is_password_and_the_connection_follows_the_settings():
    rig = rig_with()
    rig.run(base_settings(security="starttls", mailbox="Receipts"))
    assert rig.prompter.asked == [SecretPrompt("password")]
    assert rig.connections[0][0] == Connection("imap.example.com", 143, "starttls", "household")
    assert rig.connections[0][1].reveal() == "pw"
    assert ("examine", "Receipts") in rig.mailbox.calls


def test_no_password_is_an_abandoned_prompt_and_nothing_connects():
    rig = rig_with()
    rig.prompter.answer = None
    with pytest.raises(ChallengeAbandoned):
        rig.run()
    assert rig.connections == []


def test_invalid_settings_fail_before_the_prompt():
    rig = rig_with()
    with pytest.raises(InvalidProfile):
        rig.run(base_settings(senders=[]))
    assert rig.prompter.asked == []


def test_a_missing_mailbox_is_invalid_and_the_connection_is_closed():
    rig = Rig(FakeMailbox(missing_folder=True))
    with pytest.raises(InvalidProfile, match="mailbox"):
        rig.run()
    assert rig.mailbox.logged_out == 1


def test_a_login_refused_by_the_connect_is_auth_rejected_as_raised():
    rig = rig_with()

    def refuse(c: Connection, p: SecretText) -> FakeMailbox:
        raise AuthRejected("the mail server refused the login")

    rig.importer._connect = refuse  # type: ignore[assignment]
    with pytest.raises(AuthRejected):
        rig.run()


def test_closing_logs_out_and_drops_an_error():
    rig = rig_with()
    rig.mailbox.logout_error = OSError("boom")
    rig.run()
    assert rig.mailbox.logged_out == 1


# ---- the position -------------------------------------------------------------------------------------


def test_a_first_run_searches_by_arrival_from_the_day_before_the_start_date():
    rig = rig_with(4, 5)
    rig.run()
    assert [c for c in rig.mailbox.calls if c[0].startswith("uids_")] == [
        ("uids_since", SINCE - timedelta(days=1))
    ]
    assert rig.mailbox.fetched() == [4, 5]


def test_the_delivery_carries_the_position_and_the_session_does_not_write_it_to_state():
    rig = rig_with(4, 5, uidvalidity=9)
    delivery = rig.run()
    assert rig.state == {}  # the runner applies the position, once the documents are written
    pos = delivery.position
    assert pos is not None
    assert pos["position_for"] == position_for(parse_settings(base_settings()))
    assert (pos["uidvalidity"], pos["last_uid"], pos["fetched_on"]) == (9, 5, "2026-01-20")
    assert set(pos["seen"]) == {fingerprint("o4@shop"), fingerprint("o5@shop")}
    assert set(pos["seen"].values()) == {"2026-01-20"}


def test_a_failed_run_leaves_the_state_alone():
    rig = rig_with(4)
    rig.extractor.reply = lambda t, p: (_ for _ in ()).throw(RuntimeError("model down"))
    with pytest.raises(RuntimeError):
        rig.run()
    assert rig.state == {}


def test_the_next_run_continues_after_last_uid_plus_the_overlap_since_the_day_before_the_last_run():
    rig = rig_with(4, 5)
    rig.run_and_apply()
    rig.mailbox.calls.clear()
    rig.mailbox.add(6, accepted(6), date(2026, 1, 20))
    rig.run_and_apply(today=date(2026, 1, 21))
    assert [c for c in rig.mailbox.calls if c[0].startswith("uids_")] == [
        ("uids_since", date(2026, 1, 19)),
        ("uids_after", 5),
    ]
    assert rig.mailbox.fetched() == [6]  # 4 and 5 are not fetched: they are above or below the position
    assert rig.state["last_uid"] == 6 and rig.state["fetched_on"] == "2026-01-21"


def test_the_overlap_catches_a_message_a_server_made_visible_late():
    rig = rig_with(4, 5)
    rig.run_and_apply()
    late = accepted(3, sent="Mon, 19 Jan 2026 09:00:00 +0000")
    rig.mailbox.add(3, late, date(2026, 1, 19))  # a lower UID, arrived the day before the last run
    delivery = rig.run_and_apply(today=date(2026, 1, 21))
    assert 3 in rig.mailbox.fetched() and [d.external_id for d in delivery.documents] == ["message:o3@shop"]
    assert delivery.position is not None and delivery.position["last_uid"] == 5  # never moves back


def test_a_changed_uidvalidity_reads_by_arrival_since_the_day_before_the_last_run_not_by_uid():
    rig = rig_with(4, 5)
    rig.run_and_apply()
    rig.mailbox.calls.clear()
    rig.mailbox.uidvalidity = 2
    rig.mailbox.messages = {1: (accepted(7), date(2026, 1, 20)), 2: (order(8), date(2025, 12, 1))}
    delivery = rig.run_and_apply(today=date(2026, 1, 21))
    calls = [c for c in rig.mailbox.calls if c[0].startswith("uids_")]
    assert calls == [("uids_since", date(2026, 1, 19))]
    assert rig.mailbox.fetched() == [1]
    assert delivery.position is not None
    assert (delivery.position["uidvalidity"], delivery.position["last_uid"]) == (
        2,
        2,
    )  # UIDNEXT - 1 of the renumbered mailbox, not max with the old 5


def test_a_first_run_records_the_mailboxs_uidnext_minus_one_so_old_mail_is_not_read_again():
    rig = Rig(FakeMailbox(uidnext=501))
    for uid in (1, 2):
        rig.mailbox.add(uid, accepted(uid), date(2025, 6, 1))  # before the start date: never a candidate
    delivery = rig.run_and_apply()
    assert rig.mailbox.fetched() == [] and delivery.position is not None
    assert delivery.position["last_uid"] == 500
    rig.mailbox.add(501, accepted(501), date(2026, 1, 20))
    rig.mailbox.calls.clear()
    rig.run_and_apply(today=date(2026, 1, 21))
    assert ("uids_after", 500) in rig.mailbox.calls and rig.mailbox.fetched() == [501]


def test_a_changed_host_port_username_mailbox_or_start_date_discards_the_position_and_seen():
    for change in (
        {"host": "other.example.com"},
        {"port": 1993},
        {"username": "x"},
        {"mailbox": "Other"},
        {"start_date": "2026-01-02"},
    ):
        rig = rig_with(4, 5)
        rig.run_and_apply()
        rig.state["stuck"] = {"uid": 4, "uidvalidity": 1, "attempts": 2}
        rig.mailbox.calls.clear()
        since = date(2026, 1, 2) if "start_date" in change else SINCE
        delivery = rig.run(base_settings(**change), since=since)
        assert [c for c in rig.mailbox.calls if c[0].startswith("uids_")] == [
            ("uids_since", since - timedelta(days=1))
        ], change
        assert "stuck" not in rig.state
        assert delivery.importer_stats["already_seen"] == 0 and len(delivery.documents) == 2, change


def test_a_malformed_stored_position_is_a_first_run():
    rig = rig_with(4)
    rig.state.update({"position_for": position_for(parse_settings(base_settings())), "uidvalidity": "x"})
    rig.run()
    assert ("uids_since", SINCE - timedelta(days=1)) in rig.mailbox.calls


def test_with_no_messages_the_position_keeps_the_last_uid_and_moves_the_day():
    rig = rig_with(4)
    rig.run_and_apply()
    delivery = rig.run_and_apply(today=date(2026, 1, 25))
    assert delivery.position is not None and delivery.position["last_uid"] == 4
    assert delivery.position["fetched_on"] == "2026-01-25"


# ---- seen ---------------------------------------------------------------------------------------------


def test_a_seen_message_is_skipped_on_its_headers_before_the_body_is_fetched():
    rig = rig_with(4)
    rig.run_and_apply()
    rig.mailbox.calls.clear()
    rig.extractor.calls.clear()
    # the overlap lists UID 4 again: arrived yesterday
    rig.mailbox.messages[4] = (accepted(4), date(2026, 1, 20))
    delivery = rig.run(today=date(2026, 1, 21))
    assert delivery.importer_stats["already_seen"] == 1 and delivery.documents == ()
    assert ("fetch", 4) not in rig.mailbox.calls and rig.extractor.calls == []


def test_an_inner_message_in_seen_is_skipped_before_the_model_is_asked():
    inner = order(1)
    rig = Rig(FakeMailbox({1: (forward_by_hand(inner), ARRIVED)}))
    rig.run_and_apply()
    assert len(rig.extractor.calls) == 1
    rig.mailbox.add(
        2, forward_by_hand(inner, message_id="<fwd2@family>"), date(2026, 1, 20)
    )  # forwarded twice
    delivery = rig.run(today=date(2026, 1, 21))
    assert len(rig.extractor.calls) == 1
    assert delivery.importer_stats["already_seen"] == 1 and delivery.documents == ()


def test_every_handled_message_goes_into_seen_whatever_its_outcome():
    box = FakeMailbox(
        {
            1: (order(1), ARRIVED),  # not accepted
            2: (accepted(2, sent="Wed, 1 Oct 2025 10:00:00 +0000"), ARRIVED),  # before the start date
            3: (accepted(3, html=None, text=None), ARRIVED),  # no content
        }
    )
    rig = Rig(box)
    delivery = rig.run()
    assert delivery.position is not None
    assert set(delivery.position["seen"]) == {fingerprint(f"o{n}@shop") for n in (1, 2, 3)}


def test_seen_is_kept_14_days_after_its_fetch_day_and_then_pruned():
    rig = rig_with(4)
    day = TODAY
    rig.state.update(
        {
            "position_for": position_for(parse_settings(base_settings())),
            "uidvalidity": 1,
            "last_uid": 4,
            "fetched_on": day.isoformat(),
            "seen": {
                "keep14": (day - timedelta(days=14)).isoformat(),
                "drop15": (day - timedelta(days=15)).isoformat(),
            },
        }
    )
    delivery = rig.run()
    assert delivery.position is not None
    assert set(delivery.position["seen"]) == {"keep14"}


def test_a_message_without_a_message_id_is_identified_by_the_hash_of_its_bytes():
    bare = make_message(sender=SHOP, message_id=None, headers={"Delivered-To": FAMILY})
    rig = Rig(FakeMailbox({1: (bare.as_bytes(), ARRIVED)}))
    rig.run_and_apply()
    rig.mailbox.messages[1] = (bare.as_bytes(), date(2026, 1, 20))
    delivery = rig.run(today=date(2026, 1, 21))
    assert delivery.importer_stats["already_seen"] == 1 and delivery.documents == ()


def test_two_copies_of_one_message_in_a_run_count_the_second_as_seen():
    box = FakeMailbox({1: (accepted(1), ARRIVED), 2: (accepted(1), ARRIVED)})
    delivery = Rig(box).run()
    assert delivery.importer_stats["already_seen"] == 1 and len(delivery.documents) == 1


# ---- the guard on the outer message -------------------------------------------------------------------


def test_a_message_that_is_not_accepted_is_counted_and_never_read_by_the_model():
    box = FakeMailbox(
        {1: (order(1), ARRIVED), 2: (make_message(sender="news@spam.example", message_id="<n@s>"), ARRIVED)}
    )
    rig = Rig(box)
    delivery = rig.run()
    assert delivery.importer_stats["not_accepted"] == 2 and rig.extractor.calls == []


def test_an_automatic_forward_keeps_the_shops_from_and_is_accepted_by_a_forwarding_header():
    box = FakeMailbox(
        {1: (order(1, headers={"X-Forwarded-For": f"{FAMILY} dedicated@inbox.example"}), ARRIVED)}
    )
    delivery = Rig(box).run()
    assert [d.title for d in delivery.documents] == ["Order 1"]


def test_a_forward_by_hand_attaches_the_original_and_the_guard_is_not_applied_to_the_inner_message():
    rig = Rig(FakeMailbox({1: (forward_by_hand(order(1)), ARRIVED)}))
    delivery = rig.run()
    assert [d.title for d in delivery.documents] == ["Order 1"]  # the inner From is the shop, not listed
    assert rig.builder.seen[0].outer_identity == "fwd@family" and rig.builder.seen[0].identity == "o1@shop"


def test_a_stranger_forwarding_a_listed_senders_mail_is_not_accepted_the_guard_is_on_the_outer_message():
    stranger = forward_by_hand(order(1, sender=FAMILY), sender="stranger@evil.example")
    delivery = Rig(FakeMailbox({1: (stranger, ARRIVED)})).run()
    assert delivery.importer_stats["not_accepted"] == 1 and delivery.documents == ()


def test_a_mixed_forward_accepted_by_a_header_with_the_original_attached_is_read_from_the_attachment():
    outer = make_message(
        sender=SHOP,
        message_id="<mixed@s>",
        html=None,
        text="x",
        headers={"Delivered-To": FAMILY},
        attached=[order(1), order(2)],
    )
    rig = Rig(FakeMailbox({1: (outer, ARRIVED)}))
    delivery = rig.run()
    assert sorted(d.title or "" for d in delivery.documents) == ["Order 1", "Order 2"]
    assert rig.state == {}


def test_several_attached_receipts_deliver_each_on_its_own_and_each_is_remembered():
    rig = Rig(FakeMailbox({1: (forward_by_hand(order(1)), ARRIVED)}))
    box_msg = make_message(
        sender=FAMILY, message_id="<two@f>", html=None, text="x", attached=[order(2), order(3)]
    )
    rig.mailbox.add(2, box_msg, ARRIVED)
    delivery = rig.run()
    assert len(delivery.documents) == 3
    assert delivery.position is not None
    assert {fingerprint(i) for i in ("o1@shop", "o2@shop", "o3@shop", "two@f", "fwd@family")} <= set(
        delivery.position["seen"]
    )


def test_an_inline_forward_is_its_own_inner_message_with_its_own_date():
    fwd = make_message(
        sender=FAMILY,
        message_id="<inline@f>",
        sent="Tue, 13 Jan 2026 08:00:00 +0000",
        html=None,
        text="Forwarded: order 77, total 5 EUR",
    )
    rig = Rig(FakeMailbox({1: (fwd, ARRIVED)}))
    delivery = rig.run()
    assert [d.occurred_on for d in delivery.documents] == [date(2026, 1, 13)]
    assert rig.extractor.calls[0][0] == "Forwarded: order 77, total 5 EUR"


# ---- dates, sizes, input ------------------------------------------------------------------------------


def test_a_message_dated_before_the_start_date_is_skipped_before_the_model_is_asked():
    old = accepted(1, sent="Tue, 30 Dec 2025 23:59:00 +0000")
    on_start = accepted(2, sent="Thu, 1 Jan 2026 00:10:00 +0000")
    rig = Rig(FakeMailbox({1: (old, ARRIVED), 2: (on_start, ARRIVED)}))
    delivery = rig.run()
    assert delivery.importer_stats["before_start"] == 1 and len(rig.extractor.calls) == 1


def test_the_date_is_the_inner_date_in_its_own_offset():
    rig = Rig(FakeMailbox({1: (accepted(1, sent="Thu, 1 Jan 2026 23:30:00 -0500"), ARRIVED)}))
    assert [d.occurred_on for d in rig.run().documents] == [date(2026, 1, 1)]


def test_a_message_without_a_date_header_takes_its_arrival_date():
    rig = Rig(FakeMailbox({1: (accepted(1, sent=None), date(2026, 1, 12))}))
    assert [d.occurred_on for d in rig.run().documents] == [date(2026, 1, 12)]


def test_a_message_over_25_mib_is_counted_and_never_fetched_but_remembered():
    box = FakeMailbox(
        {1: (accepted(1), ARRIVED), 2: (accepted(2), ARRIVED)},
        sizes={1: 25 * 1024 * 1024 + 1, 2: 25 * 1024 * 1024},
    )
    delivery = Rig(box).run()
    assert delivery.importer_stats["too_large"] == 1 and box.fetched() == [2]
    assert delivery.position is not None and fingerprint("o1@shop") in delivery.position["seen"]


def test_a_text_over_40000_characters_is_not_sent():
    big = "x" * 40_001
    rig = Rig(
        FakeMailbox(
            {
                1: (accepted(1, html=None, text=big), ARRIVED),
                2: (accepted(2, html=None, text="x" * 40_000), ARRIVED),
            }
        )
    )
    delivery = rig.run()
    assert delivery.importer_stats["too_large"] == 1 and len(rig.extractor.calls) == 1


def test_an_over_long_text_with_a_pdf_sends_the_pdf_only():
    msg = accepted(1, html=None, text="x" * 40_001, pdfs=[("r.pdf", "application", "pdf")])
    rig = Rig(FakeMailbox({1: (msg, ARRIVED)}))
    rig.run()
    text, pdfs = rig.extractor.calls[0]
    assert text is None and [p.name for p in pdfs] == ["r.pdf"]


def test_the_model_gets_the_text_and_up_to_three_pdfs():
    pdfs = [(f"{n}.pdf", "application", "pdf") for n in "abcd"]
    rig = Rig(FakeMailbox({1: (accepted(1, html="<p>Total<sup>5</sup></p>", pdfs=pdfs), ARRIVED)}))
    rig.run()
    text, got = rig.extractor.calls[0]
    assert text == "Total^5" and [p.name for p in got] == ["a.pdf", "b.pdf", "c.pdf"]


def test_a_message_with_neither_text_nor_pdf_is_no_content_and_the_model_is_not_asked():
    rig = Rig(FakeMailbox({1: (accepted(1, html=None, text=None), ARRIVED)}))
    delivery = rig.run()
    assert delivery.importer_stats["no_content"] == 1 and rig.extractor.calls == []


# ---- what comes back ----------------------------------------------------------------------------------


def test_the_stats_carry_every_fixed_key_and_the_documents_count():
    rig = rig_with(1, 2)
    delivery = rig.run()
    assert tuple(delivery.importer_stats) == STAT_KEYS
    assert delivery.importer_stats["documents"] == 2
    assert all(type(v) is int for v in delivery.importer_stats.values())


def test_skip_reasons_of_the_extractor_and_the_builder_are_counted_under_their_keys():
    replies = iter(
        [
            Skipped("unreadable"),
            Skipped("pdf_not_read"),
            Skipped("model_refused"),
            Skipped("no_content"),
            Extraction({"merchant": "S", "total": 1}, "text"),
        ]
    )
    rig = rig_with(1, 2, 3, 4, 5)
    rig.extractor.reply = lambda t, p: next(replies)
    rig.builder.build = lambda e, c, *, minor_units_of: Skipped("incomplete")  # type: ignore[method-assign,assignment]
    stats = rig.run().importer_stats
    assert (stats["unreadable"], stats["pdf_not_read"], stats["model_refused"], stats["no_content"]) == (
        1,
        1,
        1,
        1,
    )
    assert stats["incomplete"] == 1 and stats["documents"] == 0


def test_only_the_outcomes_of_the_taxonomy_can_be_a_skip_reason():
    with pytest.raises(ValueError):
        Skipped("documents")
    with pytest.raises(ValueError):
        Skipped("whatever")


def test_the_later_document_of_one_key_wins_and_the_earlier_is_superseded():
    box = FakeMailbox({1: (accepted(1), ARRIVED), 2: (accepted(2), ARRIVED), 3: (accepted(3), ARRIVED)})
    answers = iter([("A", "100"), ("B", "100"), ("A", "100")])
    rig = Rig(box)
    rig.extractor.reply = lambda t, p: Extraction(
        dict(zip(("merchant", "order_id"), next(answers), strict=True)), "text"
    )
    delivery = rig.run()
    assert [(d.provider, d.raw["uid"]) for d in delivery.documents] == [("B", 2), ("A", 3)]
    assert delivery.importer_stats["superseded"] == 1 and delivery.importer_stats["documents"] == 2


def test_the_builder_gets_the_context_and_the_currency_lookup_passed_in():
    rig = Rig(FakeMailbox({7: (accepted(1, sent="Mon, 5 Jan 2026 10:00:00 +0000"), ARRIVED)}, uidvalidity=3))
    rig.run()
    ctx = rig.builder.seen[0]
    assert (ctx.uid, ctx.uidvalidity, ctx.date, ctx.subject, ctx.identity) == (
        7,
        3,
        date(2026, 1, 5),
        "Order 1",
        "o1@shop",
    )
    assert rig.builder.minor_units[0]("EUR") == 2


def test_coverage_is_two_days_before_the_fetch_and_data_starts_at_the_start_date_or_the_coverage():
    rig = rig_with(1)
    d = rig.run()
    assert (d.covered_through, d.covered_from) == (date(2026, 1, 18), SINCE)
    d = rig.run(since=date(2026, 1, 19))  # a start date later than the coverage
    assert (d.covered_through, d.covered_from) == (date(2026, 1, 18), date(2026, 1, 18))


def test_a_message_that_is_gone_is_passed_over():
    box = rig_with(1, 2).mailbox
    original = box.fetch
    box.fetch = lambda uid: None if uid == 1 else original(uid)  # type: ignore[method-assign]
    delivery = Rig(box).run()
    assert (
        len(delivery.documents) == 1 and delivery.position is not None and delivery.position["last_uid"] == 2
    )


# ---- logging ------------------------------------------------------------------------------------------


def test_logs_carry_uid_and_outcome_only_never_contents(caplog: pytest.LogCaptureFixture):
    secret = make_message(
        sender="alice.private@example.org",
        subject="SECRET-SUBJECT-XYZ",
        message_id="<MID-XYZ@s>",
        html=None,
        text="SECRET-BODY-XYZ order",
        headers={"Delivered-To": FAMILY},
    )
    stranger = make_message(sender="bob.stranger@example.org", subject="OTHER-SUBJECT", message_id="<mid2@s>")
    rig = Rig(FakeMailbox({1: (secret, ARRIVED), 2: (stranger, ARRIVED)}))
    with caplog.at_level(logging.DEBUG):
        rig.run(base_settings(username="loginname-xyz"))
    text = "\n".join(r.getMessage() for r in caplog.records)
    for leak in ("SECRET", "alice", "bob", "OTHER-SUBJECT", "MID-XYZ", "loginname", "imap.example.com", "pw"):
        assert leak not in text, leak
    assert "uid 1" in text and "uid 2: not_accepted" in text
