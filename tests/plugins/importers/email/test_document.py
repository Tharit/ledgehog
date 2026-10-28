"""From an extraction to a document: completeness, signs, the provider, the key."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from app.core.plugins.importer import IncomingDocument, IncomingDocumentLine
from app.plugins.importers.email.document import EmailDocumentBuilder, canonical_provider
from app.plugins.importers.email.extractor import Extraction, MessageContext, Skipped

EXPONENTS = {"EUR": 2, "USD": 2, "JPY": 0, "KWD": 3}


def exponent(code: str) -> int:
    return EXPONENTS[code]  # KeyError for an unknown currency, as the real lookup


CONTEXT = MessageContext(
    identity="inner@shop",
    outer_identity="outer@family",
    uid=7,
    uidvalidity=3,
    date=date(2026, 1, 5),
    subject="  Your   order  ",
)


def answer(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "merchant": "Shop",
        "order_id": "A-1",
        "total": 30.0,
        "currency": "EUR",
        "refund": False,
        "items": [
            {"name": "Thing", "quantity": 2, "amount": 20.0},
            {"name": "Shipping", "quantity": None, "amount": 10.0},
        ],
    }
    base.update(over)
    return base


def build(
    a: dict[str, Any], context: MessageContext = CONTEXT, source: str = "text"
) -> IncomingDocument | Skipped:
    return EmailDocumentBuilder().build(
        Extraction(a, source, "r.pdf" if source == "pdf" else None, "m-1"),  # type: ignore[arg-type]
        context,
        minor_units_of=exponent,
    )


def doc(a: dict[str, Any]) -> IncomingDocument:
    result = build(a)
    assert isinstance(result, IncomingDocument), result
    return result


def amounts(d: IncomingDocument) -> list[int]:
    return [ln.amount_minor for ln in d.lines]


# ---- the document -----------------------------------------------------------------------------------


def test_a_complete_answer_is_a_document_in_ledger_signs():
    d = doc(answer())
    assert (d.provider, d.source_id, d.occurred_on, d.total_minor, d.currency) == (
        "Shop",
        "A-1",
        date(2026, 1, 5),
        -3000,
        "EUR",
    )
    assert d.merchant_name == "Shop" and d.title == "Your order"
    assert d.lines == (IncomingDocumentLine("Thing", -2000, 2), IncomingDocumentLine("Shipping", -1000, None))
    assert sum(amounts(d)) == d.total_minor


def test_raw_holds_ids_date_path_and_the_validated_extraction_not_the_message():
    a = answer()
    result = build(a, source="pdf")
    assert isinstance(result, IncomingDocument)
    assert result.raw == {
        "message_id": "inner@shop",
        "outer_message_id": "outer@family",
        "uid": 7,
        "uidvalidity": 3,
        "date": "2026-01-05",
        "source": "pdf",
        "pdf": "r.pdf",
        "extraction": a,
        "model": "m-1",
    }
    json.dumps(result.raw)  # stored as JSON


def test_a_discount_becomes_a_positive_line_and_a_zero_line_is_dropped():
    d = doc(
        answer(
            total=25.0,
            items=[
                {"name": "Thing", "quantity": 1, "amount": 30.0},
                {"name": "Voucher", "quantity": None, "amount": -5.0},
                {"name": "Free gift", "quantity": 1, "amount": 0.0},
            ],
        )
    )
    assert [(ln.description, ln.amount_minor) for ln in d.lines] == [("Thing", -3000), ("Voucher", 500)]
    assert d.total_minor == -2500


def test_qty_only_where_it_is_a_whole_number_from_one():
    items = [
        {"name": "a", "quantity": 3, "amount": 1.0},
        {"name": "b", "quantity": 2.0, "amount": 1.0},
        {"name": "c", "quantity": 0.5, "amount": 1.0},
        {"name": "d", "quantity": 0, "amount": 1.0},
        {"name": "e", "quantity": -1, "amount": 1.0},
        {"name": "f", "quantity": None, "amount": 1.0},
        {"name": "g", "quantity": 1.5, "amount": 1.0},
    ]
    d = doc(answer(total=7.0, items=items))
    assert [ln.qty for ln in d.lines] == [3, 2, None, None, None, None, None]


def test_source_id_is_the_order_id_collapsed_else_the_message():
    assert doc(answer(order_id="  A  1 ")).source_id == "A 1"
    for missing in (None, "", "   "):
        assert doc(answer(order_id=missing)).source_id == "message:inner@shop"


def test_title_and_merchant_name_are_cut_and_the_title_may_be_absent():
    long = "x" * 300
    d = doc(answer(merchant="  Schreinerei   Huber GmbH  "))
    assert d.merchant_name == "Schreinerei Huber GmbH" and d.provider == "Schreinerei Huber"
    assert len(doc(answer(merchant=long)).merchant_name or "") == 200
    assert doc(answer(merchant=long)).provider == "x" * 100
    from dataclasses import replace

    assert len(build(answer(), replace(CONTEXT, subject=long)).title or "") == 200  # type: ignore[union-attr]
    assert build(answer(), replace(CONTEXT, subject=None)).title is None  # type: ignore[union-attr]


def test_reference_is_the_order_id_collapsed_else_none():
    d = doc(answer(order_id="  A  1 "))
    assert (d.reference, d.source_id) == ("A 1", "A 1")
    for missing in (None, "", "   "):
        d = doc(answer(order_id=missing))
        assert (d.reference, d.source_id) == (None, "message:inner@shop")


def _title(subject: str | None) -> str | None:
    from dataclasses import replace

    result = build(answer(), replace(CONTEXT, subject=subject))
    assert isinstance(result, IncomingDocument), result
    return result.title


@pytest.mark.parametrize(
    ("subject", "title"),
    [
        ("Fwd: Order 7", "Order 7"),
        ("Re: Order 7", "Order 7"),
        ("AW: Order 7", "Order 7"),
        ("WG: Order 7", "Order 7"),
        ("Fw: Order 7", "Order 7"),
        ("fwd: order 7", "order 7"),
        ("rE:   aw:Order 7", "Order 7"),
        ("Re[2]: Order 7", "Order 7"),
        ("Fwd(3) : Order 7", "Order 7"),
        ("Fwd: Re: Fwd: Order 7", "Order 7"),
        ("Rechnung: 123", "Rechnung: 123"),
        ("Reminder: Order 7", "Reminder: Order 7"),
        ("Order 7 Re: x", "Order 7 Re: x"),
        ("Fwd: Rechnung: 123", "Rechnung: 123"),
    ],
)
def test_the_titles_reply_and_forwarding_markers_are_removed(subject: str, title: str):
    assert _title(subject) == title


def test_a_subject_of_nothing_but_markers_is_no_title():
    assert _title("Re: Fwd:") is None
    assert _title("AW:") is None


def test_markers_come_off_before_the_title_is_cut():
    assert len(_title("Re: " + "x" * 300) or "") == 200


# ---- completeness -----------------------------------------------------------------------------------


def test_lines_that_sum_to_the_total_as_given_are_used_as_given():
    d = doc(
        answer(
            total=30.0,
            items=[
                {"name": "a", "quantity": 3, "amount": 10.0},
                {"name": "b", "quantity": 2, "amount": 20.0},
            ],
        )
    )
    assert amounts(d) == [-1000, -2000]  # 10 + 20 = 30, whatever the quantities


def test_lines_that_sum_to_the_total_as_amount_times_quantity_carry_the_products():
    d = doc(
        answer(
            total=50.0,
            items=[
                {"name": "a", "quantity": 3, "amount": 10.0},
                {"name": "b", "quantity": None, "amount": 20.0},
            ],
        )
    )
    assert amounts(d) == [-3000, -2000]  # the amounts were unit prices: 3 x 10 + 20
    assert [ln.qty for ln in d.lines] == [3, None]


def test_the_lines_need_not_sum_to_the_total_and_nothing_is_added_for_the_rest():
    for total in (30.01, 29.99, 25.0, 40.0):  # a discount or shipping the mail does not itemise
        d = doc(answer(total=total))
        assert amounts(d) == [-2000, -1000] and d.total_minor == -round(total * 100)


def test_the_unitemised_amount_may_be_as_large_as_the_lines_and_no_larger():
    items = [{"name": "a", "quantity": 1, "amount": 12.0}]
    assert doc(answer(total=24.0, items=items)).total_minor == -2400  # U = 12 = the lines' magnitude
    assert build(answer(total=24.01, items=items)) == Skipped("incomplete")  # a notice of a big order
    assert doc(answer(total=0, items=items)).total_minor == 0  # U = -12; a voucher paid it


def test_a_total_of_zero_is_delivered_and_a_negative_total_is_a_misread_refund():
    d = doc(answer(total=0, items=[{"name": "a", "quantity": 1, "amount": 30.0}]))
    assert d.total_minor == 0 and amounts(d) == [-3000]
    assert build(answer(total=-0.01)) == Skipped("incomplete")


def test_a_discount_line_counts_by_its_magnitude():
    items = [
        {"name": "a", "quantity": 1, "amount": 50.0},
        {"name": "voucher", "quantity": 1, "amount": -10.0},
    ]
    d = doc(answer(total=40.0, items=items))
    assert amounts(d) == [-5000, 1000]
    assert doc(answer(total=100.0, items=items)).total_minor == -10000  # U = 60 <= 60
    assert build(answer(total=100.01, items=items)) == Skipped("incomplete")


def test_lines_that_are_all_zero_are_not_a_document():
    items = [{"name": "a", "quantity": 1, "amount": 0.0}]
    assert build(answer(total=0, items=items)) == Skipped("incomplete")
    assert build(answer(total=5.0, items=items)) == Skipped("incomplete")


@pytest.mark.parametrize(
    "a",
    [
        answer(total=None),
        answer(total=-30.0),
        answer(items=None),
        answer(items=[]),
        answer(
            items=[{"name": "a", "quantity": 1, "amount": None}, {"name": "b", "quantity": 1, "amount": 30.0}]
        ),
        answer(items=[{"name": "  ", "quantity": 1, "amount": 30.0}]),
        answer(items=[{"name": "a", "quantity": 1, "amount": 12.0}]),  # a shipping notice: part of the order
        answer(currency=None),
        answer(currency="  "),
        answer(total=float("nan")),
        answer(total=float("inf")),
        answer(total=1e30, items=[{"name": "a", "quantity": 1, "amount": 1e30}]),
    ],
)
def test_incomplete_answers_are_skipped(a: dict[str, Any]):
    assert build(a) == Skipped("incomplete")


def test_amounts_are_whole_minor_units_taken_as_written_never_as_a_float():
    d = doc(answer(total=19.99, items=[{"name": "a", "quantity": 1, "amount": 19.99}]))
    assert (d.total_minor, amounts(d)) == (-1999, [-1999])  # 19.99 * 100 is 1998.9999999999998 as a float
    d = doc(answer(total=0.29, items=[{"name": "a", "quantity": 1, "amount": 0.29}]))
    assert d.total_minor == -29
    d = doc(answer(total=1234, items=[{"name": "a", "quantity": 1, "amount": 1234}]))  # an integer
    assert d.total_minor == -123400
    for fraction in (19.999, 19.995):
        assert build(
            answer(total=fraction, items=[{"name": "a", "quantity": 1, "amount": fraction}])
        ) == Skipped("incomplete")
    # a line that is not whole minor units fails, though the total is
    assert build(
        answer(
            total=30.0,
            items=[
                {"name": "a", "quantity": 1, "amount": 10.005},
                {"name": "b", "quantity": 1, "amount": 19.995},
            ],
        )
    ) == Skipped("incomplete")


def test_a_product_that_is_not_whole_minor_units_leaves_the_amounts_as_given():
    items = [{"name": "a", "quantity": 0.5, "amount": 0.25}, {"name": "b", "quantity": None, "amount": 29.75}]
    d = doc(answer(total=30.0, items=items))  # 0.5 x 25 is not whole: the second reading is not used
    assert amounts(d) == [-25, -2975]


def test_the_exponent_of_the_currency_decides_what_is_whole():
    d = doc(answer(currency="jpy", total=1500, items=[{"name": "a", "quantity": 1, "amount": 1500}]))
    assert (d.currency, d.total_minor, amounts(d)) == ("JPY", -1500, [-1500])
    assert build(
        answer(currency="JPY", total=15.5, items=[{"name": "a", "quantity": 1, "amount": 15.5}])
    ) == Skipped("incomplete")
    d = doc(answer(currency=" kwd ", total=1.005, items=[{"name": "a", "quantity": 1, "amount": 1.005}]))
    assert d.total_minor == -1005


@pytest.mark.parametrize("code", ["XXX", "EU", "EURO", "E1R", "€"])
def test_a_currency_the_lookup_does_not_know_is_skipped(code: str):
    assert build(answer(currency=code)) == Skipped("unknown_currency")


def test_a_refund_is_skipped_before_anything_else_is_checked():
    assert build(answer(refund=True, currency="XXX", total=None, items=None)) == Skipped("refund")


def test_the_checks_run_in_the_order_of_the_spec():
    assert build(answer(currency="XXX", total=None)) == Skipped("unknown_currency")
    assert build(answer(total=None, merchant=None)) == Skipped("incomplete")


@pytest.mark.parametrize("merchant", [None, "", "   ", "GmbH", "Ltd.", ".", 5])
def test_no_merchant_no_provider(merchant: Any):
    assert build(answer(merchant=merchant)) == Skipped("no_merchant")


# ---- the provider -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("merchant", "provider"),
    [
        ("Amazon.de", "Amazon"),
        ("amazon.co.uk", "amazon"),
        ("www.zalando.de", "zalando"),
        ("www.example.co.uk", "example"),
        ("shop.example.com", "example"),
        ("Schreinerei Huber GmbH", "Schreinerei Huber"),
        ("ACME Ltd.", "ACME"),
        ("ACME Ltd", "ACME"),
        ("Foo, Inc.", "Foo"),
        ("Müller GmbH & Co. KG", "Müller"),
        ("Müller Drogerie GmbH & Co. KGaA", "Müller Drogerie"),
        ("Amazon EU S.à r.l.", "Amazon EU"),
        ("Hilfe e.V.", "Hilfe"),
        ("Praxis Dr. Meier e.K.", "Praxis Dr. Meier"),
        ("Bäckerei Kurz UG (haftungsbeschränkt)", "Bäckerei Kurz"),
        ("Foo GmbH Co", "Foo"),  # repeatedly
        ("Foo AG GmbH", "Foo"),
        ("Ｆｏｏ　Ｓｈｏｐ", "Foo Shop"),  # NFKC: full-width
        ("  Café   Luise  -", "Café Luise"),
        ("Shop Online - ", "Shop Online"),
        ("IKEA Deutschland GmbH", "IKEA Deutschland"),
        ("Spotify AB", "Spotify"),
        ("Peas", "Peas"),  # "AS" inside a word is not a legal form
        ("Gesellschaft", "Gesellschaft"),
        ("Sports AG Ltd.", "Sports"),
        ("Apple Inc.", "Apple"),
        ("e.V.", ""),
    ],
)
def test_the_provider_is_the_merchant_canonicalised_case_kept(merchant: str, provider: str):
    assert canonical_provider(merchant) == provider


def test_the_provider_is_at_most_100_characters():
    assert len(canonical_provider("a" * 150)) == 100
