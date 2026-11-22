"""The mailbox side with the real extractor (fake model transport) and builder: documents and statistics."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx2
import pytest

from app.core.plugins.errors import SourceUnavailable
from app.core.plugins.fetch import SecretText
from app.plugins.importers.email.document import EmailDocumentBuilder
from app.plugins.importers.email.extract import ModelExtractor, ModelSpec
from app.plugins.importers.email.extractor import STAT_KEYS, AttemptFailed
from app.plugins.importers.email.factory import email_importer
from app.plugins.importers.email.importer import EmailImporter
from app.plugins.importers.email.mailbox import Connection
from app.utils.config import ModelConfig, Secret, VisionModelConfig
from tests.plugins.importers.email.helpers import (
    FAMILY,
    SHOP,
    SINCE,
    TODAY,
    FakeMailbox,
    Scripted,
    base_settings,
    make_message,
)
from tests.plugins.importers.email.test_extract import ANSWER, PNG, Endpoint

RECEIPT = (
    "<table><tr><td>Thing</td><td>20<sup>00</sup></td></tr><tr><td>Total</td><td>30,00</td></tr></table>"
)
ARRIVED = date(2026, 1, 6)


def order(order_id: str | None, total: float, *names: str) -> dict[str, Any]:
    """An order of the answer: one line per name, the whole total on the first (the rest at 1.0 each)."""
    items = [
        {"name": f"{name} long name", "short": name, "quantity": 1, "amount": total if i == 0 else 1.0}
        for i, name in enumerate(names or ("Thing",))
    ]
    return {"order_id": order_id, "total": total, "items": items}


def answer(*orders: dict[str, Any], **over: Any) -> dict[str, Any]:
    return {**ANSWER, "orders": list(orders), **over}


def message(n: int, **kw: Any):  # type: ignore[no-untyped-def]
    kw.setdefault("html", RECEIPT)
    kw.setdefault("subject", f"Order {n}")
    return make_message(sender=SHOP, message_id=f"<o{n}@shop>", headers={"Delivered-To": FAMILY}, **kw)


class Rig:
    def __init__(self, text: Endpoint, vision: Endpoint | None = None) -> None:
        self.mailbox = FakeMailbox()
        self.text, self.vision = text, vision
        extractor = ModelExtractor(
            ModelSpec("http://t/v1", "text-1"),
            ModelSpec("http://v/v1", "vision-1") if vision else None,
            transport=httpx2.MockTransport(text),
            vision_transport=httpx2.MockTransport(vision) if vision else None,
            render=lambda data: [PNG],
        )
        self.importer = EmailImporter(extractor, EmailDocumentBuilder(), connect=lambda c, p: self.mailbox)
        self.state: dict[str, Any] = {}

    def run(self):  # type: ignore[no-untyped-def]
        session = self.importer.open(base_settings(), self.state, Scripted(), today=TODAY)
        try:
            return session.fetch_documents(
                since=SINCE,
                today=TODAY,
                minor_units_of=lambda c: {"EUR": 2, "JPY": 0}[c],
                progress=lambda d, t: None,
            )
        finally:
            session.close()


def test_a_forwarded_receipt_becomes_a_document_with_its_counts_and_position():
    rig = Rig(Endpoint(answer(order("A-1", 30.0))))
    rig.mailbox.add(1, message(1), ARRIVED)
    delivery = rig.run()
    [doc] = delivery.documents
    assert (doc.provider, doc.source_id, doc.total_minor, doc.currency) == ("Shop", "A-1", -3000, "EUR")
    assert doc.occurred_on == date(2026, 1, 5) and doc.title == "Order 1"
    assert doc.raw["source"] == "text" and doc.raw["model"] == "text-1" and doc.raw["uid"] == 1
    assert doc.raw["message_id"] == "o1@shop" and doc.raw["outer_message_id"] == "o1@shop"
    # what the model saw is the converted text, with the superscript marker
    user = rig.text.body()["messages"][1]["content"]
    assert "20^00" in user and "\t" in user
    assert set(delivery.importer_stats) == set(STAT_KEYS) and delivery.importer_stats["documents"] == 1
    assert delivery.position is not None and delivery.position["last_uid"] == 1


def test_coverage_is_today_minus_two_and_data_starts_at_the_start_date_or_the_coverage():
    rig = Rig(Endpoint())
    delivery = rig.run()
    assert delivery.covered_through == date(2026, 1, 18) and delivery.covered_from == SINCE
    assert delivery.documents == ()
    session = rig.importer.open(base_settings(), {}, Scripted(), today=TODAY)
    later = session.fetch_documents(
        since=date(2026, 3, 1), today=TODAY, minor_units_of=lambda c: 2, progress=lambda d, t: None
    )
    assert later.covered_from == later.covered_through == date(2026, 1, 18)


def test_the_importer_names_no_provider():
    importer = Rig(Endpoint()).importer
    assert importer.providers == frozenset() and importer.emits == frozenset({"documents"})


def test_each_outcome_is_counted_once():
    texts = {
        1: answer(order("A-1", 30.0)),  # a document
        3: answer(order("A-3", 30.0), currency="XXX"),
        4: answer({"order_id": "A-4", "total": 30.0, "items": None}),
        5: answer(order("A-5", 30.0), merchant=None),
        6: "not json",
        7: answer(order("A-1", 30.0)),  # the same order again
        9: answer(order("B-1", 10.0), order("B-2", 20.0)),  # two orders, one count
        10: answer(order("C-1", 10.0), {"order_id": "C-2", "total": None, "items": None}),
        11: answer(order("B-1", 10.0), order("B-2", 20.0)),  # all duplicates
        12: answer(),  # no order
    }
    endpoint = Endpoint()
    endpoint.replies = [texts[n] for n in sorted(texts)]
    rig = Rig(endpoint)
    for n in texts:
        rig.mailbox.add(n, message(n), ARRIVED)
    rig.mailbox.add(8, make_message(sender="spam@x.example"), ARRIVED)
    stats = rig.run().importer_stats
    assert {k: v for k, v in stats.items() if v} == {
        "documents": 2,
        "same_order": 2,
        "unknown_currency": 1,
        "incomplete": 3,
        "no_merchant": 1,
        "unreadable": 1,
        "not_accepted": 1,
    }


def test_an_order_and_its_refund_in_one_delivery_are_both_delivered():
    endpoint = Endpoint()
    endpoint.replies = [answer(order("A-1", 30.0)), answer(order("A-1", 30.0), refund=True)]
    rig = Rig(endpoint)
    rig.mailbox.add(1, message(1), ARRIVED)
    rig.mailbox.add(2, message(2), ARRIVED)
    delivery = rig.run()
    assert sorted(d.total_minor for d in delivery.documents) == [-3000, 3000]
    assert delivery.importer_stats["documents"] == 2 and delivery.importer_stats["same_order"] == 0


def test_a_mail_confirming_several_orders_is_one_message_and_several_documents():
    rig = Rig(Endpoint(answer(order("A-1", 10.0, "Cable"), order("A-2", 20.0, "Lamp", "Bulb"))))
    rig.mailbox.add(1, message(1), ARRIVED)
    delivery = rig.run()
    first, second = delivery.documents
    assert (first.source_id, first.total_minor, first.raw["order"]) == ("A-1", -1000, 1)
    assert (second.source_id, second.total_minor, second.raw["order"]) == ("A-2", -2000, 2)
    assert [ln.description for ln in second.lines] == ["Lamp", "Bulb"]  # the short names
    assert first.raw["message_id"] == second.raw["message_id"] and len(first.raw["extraction"]["orders"]) == 2
    stats = {k: v for k, v in delivery.importer_stats.items() if v}
    assert stats == {"documents": 1}


def test_one_incomplete_order_makes_the_inner_message_incomplete_and_delivers_none_of_them():
    bad = {
        "order_id": "A-2",
        "total": 5.0,
        "items": [{"name": "x", "short": "x", "quantity": 1, "amount": None}],
    }
    rig = Rig(Endpoint(answer(order("A-1", 10.0), bad)))
    rig.mailbox.add(1, message(1), ARRIVED)
    delivery = rig.run()
    assert delivery.documents == ()
    assert {k: v for k, v in delivery.importer_stats.items() if v} == {"incomplete": 1}


def test_orders_without_ids_and_a_refund_are_keyed_by_message_and_position():
    endpoint = Endpoint()
    endpoint.replies = [
        answer(order(None, 10.0), order(None, 20.0)),
        answer(order("R-1", 10.0), order("R-2", 20.0), refund=True),
    ]
    rig = Rig(endpoint)
    rig.mailbox.add(1, message(1), ARRIVED)
    rig.mailbox.add(2, message(2), ARRIVED)
    keys = [d.source_id for d in rig.run().documents]
    assert keys == ["message:o1@shop#1", "message:o1@shop#2", "message:o2@shop#1", "message:o2@shop#2"]


def test_the_requests_ask_for_the_marketplace_orders_and_short_names():
    rig = Rig(Endpoint(answer(order("A-1", 30.0))))
    rig.mailbox.add(1, message(1), ARRIVED)
    rig.run()
    system = rig.text.body()["messages"][0]["content"]
    assert "never the seller of an article" in system and "Each item also has short:" in system
    assert "orders lists each order, invoice or booking" in system


def test_a_pdf_is_read_by_the_vision_model_where_the_text_yields_no_document():
    text = Endpoint({**ANSWER, "orders": None})
    vision = Endpoint(answer(order("A-1", 30.0)))
    rig = Rig(text, vision)
    rig.mailbox.add(1, message(1, pdfs=[("terms.pdf", "application", "pdf")]), ARRIVED)
    delivery = rig.run()
    [doc] = delivery.documents
    assert doc.raw["source"] == "pdf" and doc.raw["pdf"] == "terms.pdf" and doc.raw["model"] == "vision-1"
    assert len(text.requests) == 1 and len(vision.requests) == 1
    assert "response_format" not in vision.body()


def test_without_the_vision_model_such_a_message_counts_as_pdf_not_read():
    rig = Rig(Endpoint({**ANSWER, "orders": None}))
    rig.mailbox.add(1, message(1, pdfs=[("terms.pdf", "application", "pdf")]), ARRIVED)
    delivery = rig.run()
    assert delivery.documents == () and delivery.importer_stats["pdf_not_read"] == 1


def test_a_model_that_cannot_be_reached_fails_the_run_and_the_position_stays():
    endpoint = Endpoint(status=401)
    rig = Rig(endpoint)
    rig.mailbox.add(1, message(1), ARRIVED)
    with pytest.raises(SourceUnavailable) as caught:
        rig.run()
    assert type(caught.value) is SourceUnavailable
    assert "stuck" not in rig.state and "last_uid" not in rig.state


def test_a_failed_attempt_is_counted_in_stuck_and_the_third_in_a_row_is_given_up():
    endpoint = Endpoint(status=503)
    rig = Rig(endpoint)
    rig.mailbox.add(1, message(1), ARRIVED)
    for attempts in (1, 2):
        with pytest.raises(AttemptFailed):
            rig.run()
        assert rig.state["stuck"] == {"uid": 1, "uidvalidity": 1, "attempts": attempts}
    delivery = rig.run()
    assert delivery.documents == () and delivery.importer_stats["gave_up"] == 1
    assert "stuck" not in rig.state


def test_a_message_the_model_refuses_is_skipped():
    rig = Rig(Endpoint(status=413))
    rig.mailbox.add(1, message(1), ARRIVED)
    assert rig.run().importer_stats["model_refused"] == 1


def test_a_text_too_long_to_send_without_a_pdf_is_too_large_and_never_asked():
    rig = Rig(Endpoint())
    rig.mailbox.add(1, message(1, html="<p>" + "word " * 9000 + "</p>"), ARRIVED)
    delivery = rig.run()
    assert delivery.importer_stats["too_large"] == 1 and rig.text.requests == []


def test_no_log_record_carries_an_address_a_subject_a_reply_or_a_key(caplog: pytest.LogCaptureFixture):
    caplog.set_level("DEBUG")
    endpoint = Endpoint(answer(order("SECRET-ORDER", 30.0), merchant="Secret Merchant"))
    rig = Rig(endpoint)
    rig.mailbox.add(1, message(1, subject="Secret subject"), ARRIVED)
    rig.mailbox.add(2, message(2, subject="Another secret"), ARRIVED)
    rig.run()
    logged = "\n".join(r.getMessage() for r in caplog.records)
    for secret in (SHOP, FAMILY, "ecret", "SECRET", "Thing", "Bearer"):
        assert secret not in logged
    assert "uid 1" in logged


def test_the_factory_unwraps_the_configured_endpoints_and_keys():
    importer = email_importer(
        ModelConfig("http://t/v1", "text-1", Secret("tk"), "medium"),
        VisionModelConfig("http://v/v1", "vision-1", None, "high"),
    )
    extractor = importer.extractor
    assert isinstance(extractor, ModelExtractor)
    assert extractor._text.spec == ModelSpec("http://t/v1", "text-1", "tk", "medium")
    assert extractor._vision is not None and extractor._vision.spec == ModelSpec(
        "http://v/v1", "vision-1", None, "high"
    )
    assert email_importer(ModelConfig("http://t/v1", "t", None)).extractor._vision is None  # type: ignore[attr-defined]


def test_connect_is_given_the_settings_and_the_password():
    seen: list[tuple[Connection, SecretText]] = []
    rig = Rig(Endpoint())
    rig.importer._connect = lambda c, p: (seen.append((c, p)), rig.mailbox)[1]  # type: ignore[assignment]
    rig.run()
    assert seen[0][0].host == "imap.example.com" and seen[0][1].reveal() == "pw"
    json.dumps(rig.state)
