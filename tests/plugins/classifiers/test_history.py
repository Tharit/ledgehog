from __future__ import annotations

import random
from datetime import date

from hypothesis import given
from hypothesis import strategies as st

from app.core.plugins.classifier import (
    EMPTY,
    ClassifierContext,
    EntryInput,
    Field,
    Proposal,
    Vote,
)
from app.plugins.classifiers.history import HistoryClassifier
from tests.plugins.classifiers.fakes import ListHistory, entry, vote

H = HistoryClassifier()


def run(
    field: Field,
    e: EntryInput,
    votes: list[Vote],
    *,
    payee: int | None = None,
    account_ok: object = None,
    exclude: frozenset[int] = frozenset(),
) -> Proposal | None:
    resolved = {"payee": Proposal("payee", payee, {})} if payee is not None else {}
    ctx = ClassifierContext(
        resolved=resolved,  # type: ignore[arg-type]
        account_ok=account_ok or (lambda _a: True),  # type: ignore[arg-type]
        history=ListHistory(votes),
        exclude_entry_ids=exclude,
    )
    return H.propose(field, e, ctx)


def flows(n: int, **kw: object) -> list[Vote]:
    return [vote(**kw) for _ in range(n)]


def test_no_history_source_none() -> None:
    assert H.propose("type", entry(counterparty_ref="X"), ClassifierContext()) is None


# ---- keys alone ----


def test_key1_counterparty_ref() -> None:
    v = vote(counterparty_ref="DE12 3456", category_id=5, booked_on=date(2026, 2, 1))
    p = run("category", entry(counterparty_ref="de123456"), [v])
    assert p == Proposal(
        "category", 5, {"matched_on": "counterparty_ref", "agree": 1, "of": 1, "since": "2026-02-01"}
    )


def test_key2_name_and_booking_text() -> None:
    v = vote(counterparty_name="Aral Tank", booking_text="Kartenzahlung", category_id=6)
    p = run("category", entry(counterparty_name="ARAL  tank!", booking_text="kartenzahlung"), [v])
    assert p is not None and p.basis["matched_on"] == "counterparty_name+booking_text"


def test_key3_payee_for_category_only() -> None:
    votes = flows(2, payee_id=7, category_id=9)
    e = entry(purpose=None)
    p = run("category", e, votes, payee=7)
    assert p is not None and p.value == 9 and p.basis["matched_on"] == "payee"
    assert run("category", e, votes) is None  # no payee resolved
    assert run("type", e, votes, payee=7) is None
    assert run("payee", e, votes, payee=7) is None


def test_key4_tokens() -> None:
    v = vote(counterparty_name="PayPal Europe", purpose="Seeed 123", payee_id=3, category_id=2)
    p = run("payee", entry(counterparty_name="PAYPAL *SEEED", purpose="Seeed"), [v])
    # tokens {paypal, europe, seeed} vs {paypal, seeed}: 2/3
    assert p == Proposal("payee", 3, {"matched_on": "tokens", "agree": 1, "of": 1, "since": "2026-03-01"})


def test_key4_jaccard_boundary() -> None:
    e = entry(purpose="alpha beta")
    at = vote(purpose="alpha gamma", category_id=1)  # 1/3? no: {alpha,beta} vs {alpha,gamma} = 1/3
    assert run("category", e, [at]) is None
    exact = vote(purpose="alpha beta gamma beta", category_id=1)  # 2/3
    assert run("category", e, [exact]) is not None
    half = vote(purpose="alpha", category_id=1)  # 1/2
    assert run("category", e, [half]) is not None
    below = vote(purpose="alpha beta gamma delta zzz", category_id=1)  # 2/5
    assert run("category", e, [below]) is None


def test_key4_skipped_without_tokens() -> None:
    assert run("category", entry(purpose="12 34"), flows(2, purpose="12 34", category_id=1)) is None


def test_missing_input_skips_key() -> None:
    h = ListHistory([])
    ctx = ClassifierContext(history=h)
    assert H.propose("type", entry(), ctx) is None
    assert h.calls == []


# ---- refinements ----


def test_mandate_refinement() -> None:
    e = entry(counterparty_ref="CR1", mandate_ref="M1")
    votes = [
        vote(counterparty_ref="CR1", mandate_ref="M2", category_id=1),
        vote(counterparty_ref="CR1", mandate_ref="M2", category_id=1),
        vote(counterparty_ref="CR1", mandate_ref="m-1", category_id=2),
        vote(counterparty_ref="CR1", category_id=2),
    ]
    p = run("category", e, votes)
    assert p is not None and p.value == 2 and (p.basis["agree"], p.basis["of"]) == (2, 2)


def test_booking_text_refinement() -> None:
    e = entry(counterparty_name="Bank", booking_text="Entgelt")
    votes = [
        vote(counterparty_name="Bank", booking_text="Auszahlung", category_id=1),
        vote(counterparty_name="Bank", booking_text="Auszahlung", category_id=1),
        vote(counterparty_name="Bank", booking_text="entgelt", category_id=2),
        vote(counterparty_name="Bank", category_id=2),
    ]
    p = run("category", e, votes)
    assert p is not None and p.value == 2 and p.basis["of"] == 2


def test_refinement_not_applied_when_entry_lacks_code() -> None:
    e = entry(counterparty_ref="CR1")
    votes = [vote(counterparty_ref="CR1", mandate_ref="M2", category_id=1)]
    assert run("category", e, votes) is not None


# ---- majority ----


def _split(agree: int, of: int) -> list[Vote]:
    return [vote(counterparty_ref="CR", category_id=1 if i < agree else 2 + i) for i in range(of)]


def test_strict_majority_edges() -> None:
    e = entry(counterparty_ref="CR")
    assert run("category", e, _split(1, 1)) is not None
    assert run("category", e, _split(2, 4)) is None
    assert run("category", e, _split(3, 7)) is None
    p = run("category", e, _split(3, 4))
    assert p is not None and (p.basis["agree"], p.basis["of"]) == (3, 4)
    assert run("category", e, _split(4, 7)) is not None


def test_falls_through_when_no_majority() -> None:
    e = entry(counterparty_ref="CR", counterparty_name="Shop", purpose="shop")
    votes = [
        vote(counterparty_ref="CR", counterparty_name="Shop", category_id=1),
        vote(counterparty_ref="CR", counterparty_name="Shop", category_id=2),
        vote(counterparty_name="Shop", category_id=3),
        vote(counterparty_name="Shop", category_id=3),
        vote(counterparty_name="Shop", category_id=3),
    ]
    # key 1 sees a 1:1 split; key 2 sees all 5 with category 3 only 3 of 5 -> majority
    p = run("category", e, votes[:2] + votes[2:])
    assert p is not None and p.value == 3 and p.basis["matched_on"] == "counterparty_name+booking_text"
    assert (p.basis["agree"], p.basis["of"]) == (3, 5)


def test_falls_through_when_key_has_no_matches() -> None:
    e = entry(counterparty_ref="NEW", counterparty_name="Sonnenkorn Bio")
    p = run("category", e, flows(1, counterparty_name="Sonnenkorn Bio", category_id=4))
    assert p is not None and p.basis["matched_on"] == "counterparty_name+booking_text"


def test_exclude_entry_ids() -> None:
    v = vote(counterparty_ref="CR", category_id=1)
    assert run("category", entry(counterparty_ref="CR"), [v], exclude=frozenset({v.entry_id})) is None


def test_since_is_earliest_counted() -> None:
    votes = [
        vote(counterparty_ref="CR", category_id=1, booked_on=date(2026, 5, 1)),
        vote(counterparty_ref="CR", category_id=1, booked_on=date(2026, 1, 15)),
        vote(counterparty_ref="CR", category_id=2, booked_on=date(2026, 4, 1)),
        vote(counterparty_ref="CR", category_id=1, booked_on=date(2026, 3, 1)),
    ]
    p = run("category", entry(counterparty_ref="CR"), votes)
    assert p is not None and p.basis["since"] == "2026-01-15"


# ---- type ----


def test_type_counts_all_votes() -> None:
    votes = [
        vote(counterparty_ref="CR", type="transfer"),
        vote(counterparty_ref="CR", type="transfer"),
        vote(counterparty_ref="CR", type="flow", category_id=1),
    ]
    p = run("type", entry(counterparty_ref="CR"), votes)
    assert p is not None and p.value == "transfer" and p.basis["of"] == 3


# ---- counter account ----


def _t(counter: int | None, **kw: object) -> Vote:
    return vote(counterparty_ref="CR", type="transfer", counter_account_id=counter, **kw)


def test_counter_account_proposal_basis() -> None:
    p = run("counter_account", entry(counterparty_ref="CR"), [_t(50), _t(50), _t(60)])
    assert p is not None and p.value == 50
    assert p.basis == {
        "matched_on": "counterparty_ref",
        "agree": 2,
        "of": 3,
        "since": "2026-03-01",
        "account_id": 50,
    }


def test_counter_account_evidence_filters() -> None:
    e = entry(counterparty_ref="CR")
    # unpaired votes do not count
    assert run("counter_account", e, [_t(None), _t(None)]) is None
    p = run("counter_account", e, [_t(None), _t(None), _t(50)])
    assert p is not None and p.value == 50 and p.basis["of"] == 1
    # wrong currency / closed account (account_ok false) removes votes, never changes result
    votes = [_t(50), _t(50), _t(60), _t(60), _t(60)]
    p = run("counter_account", e, votes, account_ok=lambda a: a != 60)
    assert p is not None and p.value == 50 and p.basis["of"] == 2
    assert run("counter_account", e, votes, account_ok=lambda a: False) is None
    # flow votes do not count
    assert run("counter_account", e, [vote(counterparty_ref="CR", category_id=1)]) is None


# ---- payee ----


def test_payee_flow_votes_only() -> None:
    votes = [
        vote(counterparty_ref="CR", payee_id=3, category_id=1),
        vote(counterparty_ref="CR", payee_id=3, category_id=1),
        vote(counterparty_ref="CR", type="transfer"),
    ]
    p = run("payee", entry(counterparty_ref="CR"), votes)
    assert p is not None and p.value == 3 and p.basis["of"] == 2


def test_no_payee_majority_is_proposed_and_ends_field() -> None:
    votes = [
        vote(counterparty_ref="CR", category_id=1),
        vote(counterparty_ref="CR", category_id=1),
        vote(counterparty_ref="CR", payee_id=3, category_id=1),
    ]
    e = entry(counterparty_ref="CR", counterparty_name="Shop")
    p = run("payee", e, votes + flows(5, counterparty_name="Shop", payee_id=9, category_id=1))
    assert p is not None and p.value == EMPTY and (p.basis["agree"], p.basis["of"]) == (2, 3)


def test_no_payee_tie_falls_through() -> None:
    e = entry(counterparty_ref="CR", counterparty_name="Shop")
    votes = [
        vote(counterparty_ref="CR", counterparty_name="Shop", category_id=1),
        vote(counterparty_ref="CR", counterparty_name="Shop", payee_id=3, category_id=1),
        vote(counterparty_name="Shop", payee_id=3, category_id=1),
        vote(counterparty_name="Shop", payee_id=3, category_id=1),
    ]
    p = run("payee", e, votes)
    assert p is not None and p.value == 3 and p.basis["matched_on"] == "counterparty_name+booking_text"


# ---- worked examples (spec §4, §5.9) ----


def test_second_atm_withdrawal_key2_one_of_one() -> None:
    first = vote(
        counterparty_name="Sparkasse Geldautomat",
        booking_text="GA-AUSZAHLUNG",
        type="transfer",
        counter_account_id=40,
    )
    e = entry(
        counterparty_name="SPARKASSE GELDAUTOMAT",
        booking_text="GA-Auszahlung",
        counterparty_ref=None,
    )
    t = run("type", e, [first])
    assert t is not None and t.value == "transfer"
    assert t.basis["matched_on"] == "counterparty_name+booking_text"
    assert (t.basis["agree"], t.basis["of"]) == (1, 1)
    c = run("counter_account", e, [first])
    assert c is not None and c.value == 40 and (c.basis["agree"], c.basis["of"]) == (1, 1)


def test_booking_text_alone_is_never_a_key() -> None:
    # "Dauerauftrag" is a category of payment, shared by unrelated counterparties: a new counterparty
    # with that booking text gets no proposal from it (spec §5.9)
    savings = vote(
        counterparty_ref="DE01SAVINGS",
        booking_text="Dauerauftrag",
        type="transfer",
        counter_account_id=40,
    )
    other = vote(
        counterparty_ref="DE02LANDLORD",
        booking_text="Dauerauftrag",
        type="flow",
        category_id=3,
    )
    e = entry(counterparty_ref="DE03NEWPAYEE", booking_text="Dauerauftrag")
    for field in ("type", "counter_account", "category", "payee"):
        assert run(field, e, [savings, other]) is None  # type: ignore[arg-type]


def test_paypal_key4_proposes_payee_not_category() -> None:
    past = [
        vote(
            counterparty_name="PayPal Europe S.a.r.l.",
            purpose="PAYPAL Seeed order",
            payee_id=3,
            category_id=1,
        ),
        vote(counterparty_name="PayPal Europe S.a.r.l.", purpose="PAYPAL Netflix", payee_id=3, category_id=2),
        vote(counterparty_name="PayPal Europe S.a.r.l.", purpose="PAYPAL Steam", payee_id=3, category_id=3),
    ]
    e = entry(counterparty_name="PayPal Europe S.a.r.l.", purpose="PAYPAL Kindle")
    # key 2 sees all three: payee 3 agrees 3 of 3, but categories split
    assert run("payee", e, past) is not None
    assert run("category", e, past) is None
    e5 = entry(counterparty_name="PayPal (Europe)", purpose="PAYPAL Kindle")
    p = run("payee", e5, past)
    assert p is not None and p.value == 3 and p.basis["matched_on"] == "tokens"
    assert run("category", e5, past) is None


# ---- properties ----


@given(
    st.lists(
        st.tuples(st.sampled_from(["flow", "transfer"]), st.integers(1, 3), st.integers(1, 3)), max_size=9
    ),
    st.randoms(use_true_random=False),
)
def test_vote_order_never_changes_result(specs: list[tuple[str, int, int]], rnd: random.Random) -> None:
    votes = [
        vote(
            counterparty_ref="CR",
            type=t,
            category_id=c,
            payee_id=c,
            counter_account_id=a if t == "transfer" else None,
            booked_on=date(2026, 1, 1 + i),
        )
        for i, (t, c, a) in enumerate(specs)
    ]
    shuffled = votes[:]
    rnd.shuffle(shuffled)
    e = entry(counterparty_ref="CR")
    for f in ("type", "payee", "category", "counter_account"):
        assert run(f, e, votes) == run(f, e, shuffled)


@given(st.integers(1, 5), st.integers(1, 5))
def test_a_tie_never_proposes(n: int, m: int) -> None:
    votes = [vote(counterparty_ref="CR", category_id=1) for _ in range(n)]
    votes += [vote(counterparty_ref="CR", category_id=2) for _ in range(n)]
    assert run("category", entry(counterparty_ref="CR"), votes) is None


# ---- key 5: the entry's source text (D230) ----


def test_key5_source_text_is_tried_before_key3_and_names_its_basis() -> None:
    votes = [
        vote(source_text="USB-C cable", payee_id=7, category_id=5, booked_on=date(2026, 2, 1)),
        vote(source_text="usb c  CABLE!", payee_id=7, category_id=5, booked_on=date(2026, 3, 1)),
        *[vote(payee_id=7, category_id=9) for _ in range(5)],
    ]
    e = entry(source_text="USB-C Cable", counterparty_name="Amazon")
    p = run("category", e, votes, payee=7)
    assert p == Proposal(
        "category", 5, {"matched_on": "source_text", "agree": 2, "of": 2, "since": "2026-02-01"}
    )


def test_an_entry_with_a_source_text_falls_back_to_key3_only() -> None:
    votes = [vote(payee_id=7, category_id=9, counterparty_name="Amazon") for _ in range(3)]
    e = entry(source_text="Paperback", counterparty_name="Amazon")
    p = run("category", e, votes, payee=7)
    assert p is not None and p.value == 9 and p.basis["matched_on"] == "payee"


def test_an_entry_with_a_source_text_is_not_asked_on_keys_1_2_and_4() -> None:
    votes = [vote(counterparty_ref="X", counterparty_name="Amazon", purpose="order shipment", category_id=5)]
    e = entry(
        source_text="Paperback", counterparty_ref="X", counterparty_name="Amazon", purpose="order shipment"
    )
    history = ListHistory(votes)
    ctx = ClassifierContext(history=history)
    assert H.propose("category", e, ctx) is None
    assert H.propose("payee", e, ctx) is None
    assert set(history.calls) <= {"source_text", "payee"}


def test_votes_with_a_source_text_are_not_counted_on_keys_1_2_and_4() -> None:
    votes = [vote(source_text="Paperback", counterparty_ref="X", counterparty_name="Amazon", category_id=5)]
    assert run("category", entry(counterparty_ref="X"), votes) is None
    assert run("category", entry(counterparty_name="Amazon"), votes) is None


def test_key5_is_for_payee_and_category_only_and_never_for_an_entry_without_a_source_text() -> None:
    votes = [vote(source_text="Paperback", payee_id=7, category_id=5, counter_account_id=3)]
    e = entry(source_text="Paperback")
    assert run("type", e, votes) is None
    assert run("counter_account", e, votes) is None
    p = run("payee", e, votes)
    assert p is not None and p.value == 7 and p.basis["matched_on"] == "source_text"
    assert run("payee", entry(), votes) is None
