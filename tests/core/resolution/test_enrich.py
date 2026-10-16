"""A linked document as an input to resolution (spec §5.8, §5.9; documents.md §5): pure.

The source row is read as stored; the document only adds `documented`, `document_merchant` and
`document_line`."""

from __future__ import annotations

from datetime import date

from app.core.plugins.classifier import EntryInput
from app.core.resolution.enrich import LinkedDocument, with_document

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
    assert with_document(ENTRY, None) is ENTRY
    assert not ENTRY.documented and ENTRY.document_merchant is None and ENTRY.document_line is None


def test_the_source_fields_are_never_rewritten() -> None:
    out = with_document(ENTRY, DOC, line_no=1)
    assert out.counterparty_name == "PAYPAL *SEEEDDEVELO"
    assert out.purpose == "1234 PP.5678"
    assert (out.booking_text, out.amount, out.entry_id) == ("CARD", -1000, 1)


def test_the_merchant_is_a_field_of_its_own() -> None:
    out = with_document(ENTRY, DOC)
    assert (out.documented, out.document_merchant) == (True, "Seeed Studio")


def test_the_line_is_the_entrys_own_or_none() -> None:
    assert with_document(ENTRY, DOC, line_no=2).document_line == "Case"
    assert with_document(ENTRY, DOC, line_no=1).document_line == "USB cable"
    # an entry without a line has none, whatever the document holds (a split made by hand, an unsplit order)
    assert with_document(ENTRY, DOC).document_line is None
    assert with_document(ENTRY, DOC, line_no=9).document_line is None


def test_a_document_without_a_merchant_is_still_a_document() -> None:
    out = with_document(ENTRY, LinkedDocument(None, ((1, -1000, "Cable"),)), line_no=1)
    assert (out.documented, out.document_merchant, out.document_line) == (True, None, "Cable")
    assert with_document(ENTRY, LinkedDocument("  ", ())).document_merchant is None
