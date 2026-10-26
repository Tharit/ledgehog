"""Pass 3's payload (spec §5.9 "Limited payload", architecture §5.4): only the permitted text."""

from __future__ import annotations

from datetime import date

from app.core.plugins.classifier import EntryInput
from app.plugins.classifiers.llm.payload import fingerprint_of, payload_of, user_message

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
    )
    payload = payload_of(entry)
    assert payload == {
        "counterparty": "AUCAT BAR CUBELLES",
        "booking text": "CARD PAYMENT",
        "purpose": "toll tag",
    }
    assert payload is not None
    sent = user_message(payload)
    for secret in SECRETS:
        assert secret not in sent
    assert "USD" not in sent and "EUR" not in sent


def test_an_empty_payload_is_none_whatever_else_the_entry_has() -> None:
    assert payload_of(_entry()) is None
    assert payload_of(_entry(counterparty_name="  ", purpose="")) is None


def test_the_fingerprint_follows_the_payload_only() -> None:
    a = payload_of(_entry(counterparty_name="X"))
    b = payload_of(_entry(counterparty_name="X", amount=5, booked_on=date(2025, 1, 1), counterparty_ref="Z"))
    c = payload_of(_entry(counterparty_name="X", purpose="more"))
    assert a is not None and b is not None and c is not None
    assert fingerprint_of(a) == fingerprint_of(b) != fingerprint_of(c)


def test_an_entry_with_a_source_text_adds_its_source_text_and_its_accounts_name() -> None:
    plain = _entry(counterparty_name="Amazon", purpose="order 1", account_name="Amazon clearing")
    booked = _entry(
        counterparty_name="Amazon",
        purpose="order 1",
        source_text="USB-C cable",
        account_name="Amazon clearing",
    )
    assert payload_of(plain) == {"counterparty": "Amazon", "purpose": "order 1"}
    assert payload_of(booked) == {
        "counterparty": "Amazon",
        "purpose": "order 1",
        "source text": "USB-C cable",
        "account": "Amazon clearing",
    }
    assert fingerprint_of(payload_of(booked) or {}) != fingerprint_of(payload_of(plain) or {})
    assert "Amazon clearing" in user_message(payload_of(booked) or {})


def test_a_source_text_alone_is_a_payload_and_a_blank_one_is_none() -> None:
    assert payload_of(_entry(source_text="Paperback", account_name="A")) == {
        "source text": "Paperback",
        "account": "A",
    }
    assert payload_of(_entry(source_text="  ", account_name="A")) is None
