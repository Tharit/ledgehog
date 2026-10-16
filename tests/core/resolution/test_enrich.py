"""The enrichment of a linked document (spec §5.8, §5.9; documents.md §5): pure."""

from __future__ import annotations

from datetime import date

from app.core.plugins.classifier import EntryInput
from app.core.resolution.enrich import LinkedDocument, enriched_input

ENTRY = EntryInput(
    entry_id=1,
    account_id=1,
    currency="EUR",
    booked_on=date(2026, 3, 10),
    amount=-1000,
    counterparty_name="PAYPAL *SEEEDDEVELO",
    purpose="1234 PP.5678",
    booking_text="CARD",
)
DOC = LinkedDocument("Seeed Studio", ((1, -400, "USB cable"), (2, -600, "Case")))


def test_no_document_is_the_input_itself() -> None:
    assert enriched_input(ENTRY, None) is ENTRY


def test_the_merchant_stands_in_and_every_description_is_appended_to_the_purpose() -> None:
    out = enriched_input(ENTRY, DOC)
    assert out.counterparty_name == "Seeed Studio"
    assert out.purpose == "1234 PP.5678 USB cable Case"
    assert (out.booking_text, out.amount, out.entry_id) == ("CARD", -1000, 1)  # nothing else changes


def test_an_entry_made_from_a_line_is_read_with_that_line_only() -> None:
    assert enriched_input(ENTRY, DOC, line_no=2).purpose == "1234 PP.5678 Case"
    assert enriched_input(ENTRY, DOC, line_no=1).purpose == "1234 PP.5678 USB cable"


def test_without_a_merchant_the_banks_name_stays_and_without_a_purpose_the_lines_are_it() -> None:
    bare = EntryInput(1, 1, "EUR", date(2026, 3, 10), -1000, counterparty_name="PAYPAL *X")
    out = enriched_input(bare, LinkedDocument(None, ((1, -1000, "Cable"),)))
    assert (out.counterparty_name, out.purpose) == ("PAYPAL *X", "Cable")


def test_a_document_with_neither_changes_nothing_but_equals_the_input() -> None:
    assert enriched_input(ENTRY, LinkedDocument(None, ())) == ENTRY
