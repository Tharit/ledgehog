"""A poison message: three runs in a row that fail at the same message give it up (email.md §8)."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.plugins.errors import SourceUnavailable
from app.plugins.importers.email.extractor import AttemptFailed, Extraction
from tests.plugins.importers.email.helpers import FAMILY, SHOP, FakeMailbox, Rig, make_message

ARRIVED = date(2026, 1, 6)


def msg(n: int):  # type: ignore[no-untyped-def]
    return make_message(
        sender=SHOP, message_id=f"<o{n}@shop>", subject=f"Order {n}", headers={"Delivered-To": FAMILY}
    )


def failing_at(rig: Rig, poison: int) -> None:
    def reply(text: str | None, pdfs: object) -> Extraction:
        if text and f"Order {poison}" in text:
            raise AttemptFailed("a request failed")
        return Extraction({"merchant": "S", "order_id": text or "x"}, "text")

    rig.extractor.reply = reply  # type: ignore[assignment]


def rig_for() -> Rig:
    box = FakeMailbox()
    for n in (1, 2, 3):
        box.add(
            n,
            make_message(
                sender=SHOP,
                message_id=f"<o{n}@shop>",
                html=f"<p>Order {n}</p>",
                headers={"Delivered-To": FAMILY},
            ),
            ARRIVED,
        )
    rig = Rig(box)
    failing_at(rig, 2)
    return rig


def test_a_failed_attempt_fails_the_run_writes_stuck_and_leaves_the_position():
    rig = rig_for()
    with pytest.raises(AttemptFailed):
        rig.run()
    assert rig.state == {"stuck": {"uid": 2, "uidvalidity": 1, "attempts": 1}}


def test_the_third_run_in_a_row_gives_the_message_up_and_goes_on():
    rig = rig_for()
    for attempts in (1, 2):
        with pytest.raises(SourceUnavailable):
            rig.run()
        assert rig.state["stuck"] == {"uid": 2, "uidvalidity": 1, "attempts": attempts}
    delivery = rig.run()
    assert delivery.importer_stats["gave_up"] == 1
    assert sorted(d.external_id for d in delivery.documents) == ["Order 1", "Order 3"]
    assert "stuck" not in rig.state
    assert delivery.position is not None and delivery.position["last_uid"] == 3
    assert fingerprint_in(
        delivery.position, "o2@shop"
    )  # remembered: a skipped message is read again only after a Reset


def fingerprint_in(position: dict, identity: str) -> bool:  # type: ignore[type-arg]
    from app.plugins.importers.email.position import fingerprint

    return fingerprint(identity) in position["seen"]


def test_the_count_is_per_message_and_a_different_message_starts_again():
    rig = rig_for()
    with pytest.raises(AttemptFailed):
        rig.run()
    failing_at(rig, 3)
    rig.mailbox.messages.pop(2)
    with pytest.raises(AttemptFailed):
        rig.run()
    assert rig.state["stuck"] == {"uid": 3, "uidvalidity": 1, "attempts": 1}


def test_a_changed_uidvalidity_is_another_message():
    rig = rig_for()
    with pytest.raises(AttemptFailed):
        rig.run()
    rig.mailbox.uidvalidity = 5
    with pytest.raises(AttemptFailed):
        rig.run()
    assert rig.state["stuck"] == {"uid": 2, "uidvalidity": 5, "attempts": 1}


def test_a_run_that_gets_past_every_message_clears_stuck():
    rig = rig_for()
    with pytest.raises(AttemptFailed):
        rig.run()
    rig.extractor.reply = None  # the model recovers
    rig.run()
    assert "stuck" not in rig.state


def test_a_model_that_cannot_be_reached_at_all_counts_nothing():
    rig = rig_for()

    def unreachable(text: str | None, pdfs: object) -> Extraction:
        raise SourceUnavailable("the model could not be reached")

    rig.extractor.reply = unreachable  # type: ignore[assignment]
    for _ in range(4):
        with pytest.raises(SourceUnavailable):
            rig.run()
    assert "stuck" not in rig.state
