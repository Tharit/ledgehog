"""Document matching (spec/features/documents.md §1-§4, §9)."""

from __future__ import annotations

from datetime import date, timedelta

from app.core.matching import (
    DocInput,
    DocTxn,
    DocWindow,
    Line,
    automatic_links,
    document_candidates,
    fully_charged,
    match,
    reverse_matches,
    suggestions,
)

D = date(2026, 3, 10)
W = DocWindow(7, 7)  # the edges of a symmetric window; the asymmetric one has its own test


def txn(i: int = 1, amount: int = -1000, on: date = D, **kw) -> DocTxn:  # noqa: ANN003
    kw.setdefault("payee_provider", "amazon")
    kw.setdefault("currency", "EUR")
    return DocTxn(i, 1, on, amount, **kw)


def doc(i: int = 101, total: int = -1000, on: date = D, **kw) -> DocInput:  # noqa: ANN003
    provider = kw.pop("provider", "amazon")
    currency = kw.pop("currency", "EUR")
    return DocInput(i, provider, on, total, currency, **kw)


def order(*amounts: int, i: int = 101, carriers: tuple[DocTxn, ...] = (), **kw) -> DocInput:  # noqa: ANN003
    """A document of these line amounts, its total their sum."""
    lines = tuple(Line(n, a) for n, a in enumerate(amounts, start=1))
    return doc(i, sum(amounts), lines=lines, carriers=carriers, **kw)


def carrier(i: int, amount: int, on: date = D, **kw) -> DocTxn:  # noqa: ANN003
    """A transaction whose original entry links a document (decided, so never considered)."""
    return DocTxn(i, 1, on, amount, "EUR", document_decided=True, document_id=101, **kw)


def ids(found: list[DocInput]) -> list[int]:
    return [d.document_id for d in found]


def test_basic_candidate_and_provider() -> None:
    assert ids(document_candidates(txn(), [doc(), doc(102, provider="paypal")], W)) == [101]


def test_sign_must_match_and_refund_matches_refund_only() -> None:
    assert document_candidates(txn(), [doc(total=1000)], W) == []
    assert ids(document_candidates(txn(amount=1000), [doc(total=1000)], W)) == [101]
    assert document_candidates(txn(amount=1000), [doc(total=-1000)], W) == []


def test_currency_versus_instructed() -> None:
    usd = doc(total=-1100, currency="USD")
    assert document_candidates(txn(), [usd], W) == []
    t = txn(instructed_amount=-1100, instructed_currency="USD")
    assert ids(document_candidates(t, [usd], W)) == [101]
    assert document_candidates(t, [doc(total=-1100, currency="GBP")], W) == []
    # same number in the wrong currency is no match
    assert document_candidates(txn(), [doc(currency="USD")], W) == []


def test_window_edges_and_zero() -> None:
    assert ids(document_candidates(txn(), [doc(on=D + timedelta(7)), doc(102, on=D - timedelta(7))], W)) == [
        101,
        102,
    ]
    assert document_candidates(txn(), [doc(on=D + timedelta(8))], W) == []
    assert document_candidates(txn(), [doc(on=D - timedelta(8))], W) == []
    assert ids(document_candidates(txn(), [doc(), doc(102, on=D + timedelta(1))], DocWindow(0, 0))) == [101]


def test_the_window_is_asymmetric() -> None:
    w = DocWindow(back=60, ahead=7)
    on = lambda days: [doc(on=D + timedelta(days))]  # noqa: E731
    assert ids(document_candidates(txn(), on(-60), w)) == [101]
    assert document_candidates(txn(), on(-61), w) == []
    assert ids(document_candidates(txn(), on(7), w)) == [101]
    assert document_candidates(txn(), on(8), w) == []
    # the reverse reach: a booking up to `ahead` days before the document, `back` days after it
    ts = [
        txn(1, on=D - timedelta(7)),
        txn(2, on=D - timedelta(8)),
        txn(3, on=D + timedelta(60)),
        txn(4, on=D + timedelta(61)),
    ]
    assert [t.entry_id for t in reverse_matches(doc(), ts, w)] == [1, 3]
    # zero on one side leaves the other
    assert ids(document_candidates(txn(), on(-5), DocWindow(5, 0))) == [101]
    assert document_candidates(txn(), on(1), DocWindow(5, 0)) == []


def test_the_provider_is_matched_without_regard_to_case() -> None:
    assert ids(document_candidates(txn(payee_provider="PayPal"), [doc(provider="paypal")], W)) == [101]
    assert automatic_links([txn(payee_provider="PAYPAL")], [doc(provider="PayPal")], W) == {1: 101}


def test_a_document_carried_in_full_is_no_candidate() -> None:
    assert document_candidates(txn(), [doc(carriers=(carrier(9, -1000),))], W) == []


def test_ineligible_transactions_have_no_candidates() -> None:
    for kw in (
        {"duplicate": True},
        {"confirmed": True},
        {"document_decided": True},
        {"payee_provider": None},
        {"is_transfer": True},  # a document explains a flow (spec §5.8)
    ):
        assert document_candidates(txn(**kw), [doc()], W) == []


def test_automatic_link_needs_exactly_one_candidate() -> None:
    assert automatic_links([txn()], [doc()], W) == {1: 101}
    assert automatic_links([txn()], [doc(), doc(102)], W) == {}
    assert automatic_links([txn()], [], W) == {}


def test_uniqueness_both_ways() -> None:
    # two identical charges, one document: neither is linked, both are offered it
    two_charges = [txn(1), txn(2)]
    assert automatic_links(two_charges, [doc()], W) == {}
    for t in two_charges:
        assert ids(suggestions(t, [doc()], W, others=two_charges)) == [101]
    # two identical charges and two identical documents: nothing is linked
    assert automatic_links(two_charges, [doc(), doc(102)], W) == {}
    # a second charge outside the window leaves the first one alone
    far = txn(2, on=D + timedelta(30))
    assert automatic_links([txn(1), far], [doc()], W) == {1: 101}


def test_ineligible_transaction_does_not_block_the_link() -> None:
    assert automatic_links([txn(1), txn(2, confirmed=True)], [doc()], W) == {1: 101}


def test_suggestions_only_without_a_link() -> None:
    assert suggestions(txn(), [doc()], W) == []
    assert ids(suggestions(txn(), [doc(), doc(102)], W)) == [101, 102]
    assert suggestions(txn(document_decided=True), [doc(), doc(102)], W) == []


def test_deterministic_regardless_of_input_order() -> None:
    docs = [
        doc(105, on=D + timedelta(3)),
        doc(103),
        doc(104, on=D - timedelta(3)),
        doc(102, on=D + timedelta(3)),
    ]
    forward = ids(document_candidates(txn(), docs, W))
    assert forward == [103, 102, 104, 105] == ids(document_candidates(txn(), docs[::-1], W))
    txns = [txn(1), txn(2, amount=-500), txn(3, amount=-700)]
    pool = [doc(1), doc(2, total=-500), doc(3, total=-700)]
    assert automatic_links(txns, pool, W) == automatic_links(txns[::-1], pool[::-1], W) == {1: 1, 2: 2, 3: 3}


def test_reverse_matches_include_confirmed_any_payee_and_any_account() -> None:
    ts = [
        txn(1, confirmed=True, payee_provider=None),
        DocTxn(2, 9, D + timedelta(7), -1000, "EUR"),
        txn(3, duplicate=True),
        txn(4, on=D + timedelta(8)),
        txn(5, amount=-999),
        txn(6, document_decided=True),
        txn(7, instructed_amount=-1000, instructed_currency="EUR", currency="USD", amount=-1100),
    ]
    assert [t.entry_id for t in reverse_matches(doc(), ts, W)] == [1, 6, 7, 2]
    assert reverse_matches(doc(carriers=(carrier(9, -1000),)), ts, W) == []


def test_a_transfer_is_not_a_reverse_match_nor_does_it_block_a_link() -> None:
    ts = [txn(1, is_transfer=True, payee_provider=None), txn(2)]
    assert [t.entry_id for t in reverse_matches(doc(), ts, W)] == [2]
    # the transfer is not among the transactions considered, so the other one has the document alone
    assert automatic_links([txn(1, is_transfer=True), txn(2)], [doc()], W) == {2: 101}


def test_reverse_matches_sign_and_instructed() -> None:
    assert reverse_matches(doc(total=1000), [txn(1)], W) == []
    usd = doc(total=-1100, currency="USD")
    assert [
        t.entry_id
        for t in reverse_matches(usd, [txn(1, instructed_amount=-1100, instructed_currency="USD")], W)
    ] == [1]


# ---- one document, several charges ------------------------------------------------------------------


def test_a_charge_that_takes_some_of_the_lines_is_a_candidate() -> None:
    assert ids(document_candidates(txn(amount=-300), [order(-300, -200)], W)) == [101]
    assert document_candidates(txn(amount=-250), [order(-300, -200)], W) == []
    # a partial match needs lines that sum to the total
    assert (
        document_candidates(txn(amount=-300), [doc(total=-600, lines=(Line(1, -300), Line(2, -200)))], W)
        == []
    )
    # the whole document matches whatever the lines sum to
    assert ids(
        document_candidates(txn(amount=-600), [doc(total=-600, lines=(Line(1, -300), Line(2, -200)))], W)
    ) == [101]


def test_the_charges_of_one_order_are_linked_together() -> None:
    thirty, twenty = txn(1, amount=-300), txn(2, amount=-200, on=D + timedelta(1))
    pool = [order(-300, -200)]
    assert automatic_links([thirty, twenty], pool, W) == {1: 101, 2: 101}
    assert suggestions(thirty, pool, W, others=[thirty, twenty]) == []
    # each is a candidate alone, and the links do not depend on the order given
    assert automatic_links([twenty, thirty], pool, W) == {1: 101, 2: 101}


def test_the_later_charge_of_a_partly_charged_order_is_linked() -> None:
    pool = [order(-300, -200, carriers=(carrier(9, -300),))]
    assert automatic_links([txn(2, amount=-200)], pool, W) == {2: 101}
    assert document_candidates(txn(2, amount=-300), pool, W) == []  # the first line is taken


def test_a_document_with_a_confirmed_carrier_is_only_suggested() -> None:
    pool = [order(-300, -200, carriers=(carrier(9, -300, confirmed=True),))]
    t = txn(2, amount=-200)
    assert automatic_links([t], pool, W) == {}
    assert ids(suggestions(t, pool, W, others=[t])) == [101]


def test_a_link_needs_an_allocation_that_keeps_the_committed_references() -> None:
    # a carrier of -200 references line 1 (-300): an allocation exists only by moving that line, so the order
    # is a suggestion and no automatic link
    moved = order(-300, -200, carriers=(carrier(9, -200, line_numbers=frozenset({1})),))
    t = txn(2, amount=-300)
    assert ids(document_candidates(t, [moved], W)) == [101]  # a candidate: some allocation exists
    assert automatic_links([t], [moved], W) == {}
    assert ids(suggestions(t, [moved], W, others=[t])) == [101]
    kept = order(-300, -200, carriers=(carrier(9, -200, line_numbers=frozenset({2})),))
    assert automatic_links([t], [kept], W) == {2: 101}


def test_the_only_candidate_of_each_charge() -> None:
    # t1 has two candidate documents: nothing is linked, even though the order alone would divide
    a, b = txn(1, amount=-300), txn(2, amount=-200)
    pool = [order(-300, -200), doc(102, total=-300)]
    assert automatic_links([a, b], pool, W) == {}
    assert sorted(ids(suggestions(a, pool, W, others=[a, b]))) == [101, 102]


def test_identical_charges_see_a_single_line_alone() -> None:
    a, b = txn(1, amount=-300), txn(2, amount=-300)
    assert automatic_links([a, b], [order(-300, -200)], W) == {}
    assert automatic_links([a, b], [order(-300, -300)], W) == {1: 101, 2: 101}


def test_match_has_candidates_and_links() -> None:
    a = txn(1, amount=-300)
    found = match([a, txn(2, amount=-777)], [order(-300, -200)], W)
    assert ids(found.candidates[1]) == [101] and 2 not in found.candidates
    assert found.links == {1: 101}
    assert found.suggested.keys() == (found.candidates.keys() - found.links.keys())


def test_reverse_matches_of_a_partly_charged_order() -> None:
    pool = order(-300, -200, carriers=(carrier(9, -300),))
    ts = [txn(1, amount=-200), txn(2, amount=-300), txn(3, amount=-500), carrier(9, -300)]
    assert [t.entry_id for t in reverse_matches(pool, ts, W)] == [1]
    # an order carried in full lists nothing
    full = order(-300, -200, carriers=(carrier(9, -300), carrier(8, -200)))
    assert fully_charged(full) and reverse_matches(full, ts, W) == []
    # a document not carried at all lists the charges that take some of its lines or all of them
    assert [t.entry_id for t in reverse_matches(order(-300, -200), ts[:3], W)] == [1, 2, 3]


def test_fully_charged_compares_magnitudes() -> None:
    assert not fully_charged(order(-300, -200))
    assert not fully_charged(order(-300, -200, carriers=(carrier(9, -300),)))
    assert fully_charged(order(-300, -200, carriers=(carrier(9, -300), carrier(8, -200))))
    assert fully_charged(order(-300, -200, carriers=(carrier(9, -600),)))  # beyond the total, by magnitude


def test_a_zero_amount_booking_is_never_matched() -> None:
    zero = txn(1, amount=0)
    multi = order(-300, -700)
    assert document_candidates(zero, [multi, doc(total=0), doc(102)], W) == []
    assert automatic_links([zero], [multi, doc(total=0)], W) == {}
    assert suggestions(zero, [multi], W) == []
    assert match([zero], [multi], W).candidates == {}
    # and it takes no part in the link of the others
    assert automatic_links([zero, txn(2, amount=-1000)], [multi], W) == {2: 101}
    assert reverse_matches(multi, [zero, txn(2, amount=-300)], W) == [txn(2, amount=-300)]
