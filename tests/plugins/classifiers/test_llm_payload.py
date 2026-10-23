"""Pass 3's payload (spec §5.9 "Limited payload", architecture §5.4): only the permitted text."""

from __future__ import annotations

from datetime import date

from app.core.plugins.classifier import EntryInput
from app.core.plugins.model import LineInput
from app.plugins.classifiers.llm.payload import fingerprint_of, payload_fingerprint, payload_of, user_message

SECRETS = ("DE89370400440532013000", "COBADEFFXXX", "E2E-REF-77", "MANDATE-55", "1234567", "2026-02-10")


def _entry(**kw: object) -> EntryInput:
    base: dict[str, object] = {
        "entry_id": 1,
        "account_id": 9,
        "currency": "EUR",
        "booked_on": date(2026, 2, 10),
        "amount": -1234567,
        "counterparty_ref": "DE89370400440532013000",
        "mandate_ref": "MANDATE-55",
        "end_to_end_id": "E2E-REF-77",
        "instructed_currency": "USD",
        "instructed_amount": -1234567,
    }
    base.update(kw)
    return EntryInput(**base)  # type: ignore[arg-type]


def test_the_payload_has_the_permitted_text_and_nothing_else() -> None:
    entry = _entry(
        counterparty_name="AUCAT BAR CUBELLES",
        booking_text="CARD PAYMENT",
        purpose="toll  tag",
        documented=True,
        document_merchant="Autopistas",
    )
    payload = payload_of(entry)
    assert payload == {
        "counterparty": "AUCAT BAR CUBELLES",
        "booking text": "CARD PAYMENT",
        "purpose": "toll tag",
        "document merchant": "Autopistas",
    }
    assert payload is not None
    sent = user_message(payload)
    for secret in SECRETS:
        assert secret not in sent
    assert "USD" not in sent and "EUR" not in sent


def test_an_empty_payload_is_none_whatever_else_the_entry_has() -> None:
    assert payload_of(_entry()) is None
    assert payload_of(_entry(counterparty_name="  ", purpose="")) is None


def test_a_document_without_text_adds_nothing() -> None:
    assert payload_of(_entry(documented=True)) is None


def test_the_fingerprint_follows_the_payload_only() -> None:
    a = payload_of(_entry(counterparty_name="X"))
    b = payload_of(_entry(counterparty_name="X", amount=5, booked_on=date(2025, 1, 1), counterparty_ref="Z"))
    c = payload_of(_entry(counterparty_name="X", purpose="more"))
    assert a is not None and b is not None and c is not None
    assert fingerprint_of(a) == fingerprint_of(b) != fingerprint_of(c)


def test_an_entry_with_a_line_has_the_merchant_and_the_line_only() -> None:
    entry = _entry(
        counterparty_name="PAYPAL EUROPE",
        booking_text="CARD PAYMENT",
        purpose="1234 order",
        documented=True,
        document_merchant="Seeed Studio",
        document_line="USB  cable",
    )
    payload = payload_of(entry)
    assert payload == {"document merchant": "Seeed Studio", "document line": "USB cable"}
    sent = user_message(payload or {})
    for secret in (*SECRETS, "PAYPAL", "CARD PAYMENT", "order"):
        assert secret not in sent


def test_a_line_has_the_merchant_and_its_description_only_and_the_entry_shares_its_fingerprint() -> None:
    line = LineInput(7, "Seeed Studio", "USB cable")
    assert payload_of(line) == {"document merchant": "Seeed Studio", "document line": "USB cable"}
    entry = _entry(
        counterparty_name="PAYPAL",
        documented=True,
        document_merchant="Seeed Studio",
        document_line="USB cable",
    )
    assert payload_fingerprint(line) == payload_fingerprint(entry) is not None
    assert payload_fingerprint(LineInput(7, "Other", "USB cable")) != payload_fingerprint(line)
    assert payload_fingerprint(LineInput(8, None, "USB cable")) != payload_fingerprint(line)
    assert payload_of(LineInput(1, "Seeed", "  ")) == {"document merchant": "Seeed"}
