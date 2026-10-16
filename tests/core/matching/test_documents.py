"""Document matching (spec/features/documents.md §1-§4, §9)."""

from __future__ import annotations

from datetime import date, timedelta

from app.core.matching import (
    DocInput,
    DocTxn,
    automatic_links,
    document_candidates,
    reverse_matches,
    suggestions,
)

D = date(2026, 3, 10)
W = 7


def txn(i: int = 1, amount: int = -1000, on: date = D, **kw) -> DocTxn:  # noqa: ANN003
    kw.setdefault("payee_provider", "amazon")
    kw.setdefault("currency", "EUR")
    return DocTxn(i, 1, on, amount, **kw)


def doc(i: int = 101, total: int = -1000, on: date = D, **kw) -> DocInput:  # noqa: ANN003
    provider = kw.pop("provider", "amazon")
    currency = kw.pop("currency", "EUR")
    return DocInput(i, provider, on, total, currency, **kw)


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
    assert ids(document_candidates(txn(), [doc(on=D + timedelta(W)), doc(102, on=D - timedelta(W))], W)) == [
        101,
        102,
    ]
    assert document_candidates(txn(), [doc(on=D + timedelta(W + 1))], W) == []
    assert document_candidates(txn(), [doc(on=D - timedelta(W + 1))], W) == []
    assert ids(document_candidates(txn(), [doc(), doc(102, on=D + timedelta(1))], 0)) == [101]


def test_carried_documents_are_excluded() -> None:
    assert document_candidates(txn(), [doc(carried=True)], W) == []


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
        DocTxn(2, 9, D + timedelta(W), -1000, "EUR"),
        txn(3, duplicate=True),
        txn(4, on=D + timedelta(W + 1)),
        txn(5, amount=-999),
        txn(6, document_decided=True),
        txn(7, instructed_amount=-1000, instructed_currency="EUR", currency="USD", amount=-1100),
    ]
    assert [t.entry_id for t in reverse_matches(doc(), ts, W)] == [1, 6, 7, 2]
    assert reverse_matches(doc(carried=True), ts, W) == []


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
