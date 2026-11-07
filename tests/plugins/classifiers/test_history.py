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


def test_no_key_on_words_alone() -> None:
    # key 4 is gone: an entry shares no key with a vote of another counterparty, whatever the words
    v = vote(counterparty_name="MediaMarkt", purpose="Kartenzahlung girocard", payee_id=3, category_id=2)
    e = entry(counterparty_name="Shell", purpose="Kartenzahlung girocard")
    for field in ("type", "payee", "category"):
        assert run(field, e, [v]) is None  # type: ignore[arg-type]


# ---- the purpose refines every key ----


def _friend(purpose: str, category_id: int, n: int = 1) -> list[Vote]:
    return [vote(counterparty_ref="DE99FRIEND", purpose=purpose, category_id=category_id) for _ in range(n)]


FRIEND = _friend("Miete Juni", 1, 3) + _friend("Pizza Essen Freitag", 2, 2)


def test_similar_purpose_decides_unanimously() -> None:
    e = entry(counterparty_ref="DE99FRIEND", purpose="Pizza Essen Samstag")
    p = run("category", e, FRIEND)
    assert p is not None and p.value == 2 and not p.gives_way
    assert p.basis["matched_on"] == "counterparty_ref+purpose"
    assert (p.basis["agree"], p.basis["of"]) == (2, 2)


def test_no_similar_purpose_falls_back_to_all_matches_and_gives_way() -> None:
    e = entry(counterparty_ref="DE99FRIEND", purpose="Konzertkarten")
    p = run("category", e, FRIEND)
    assert p is not None and p.value == 1 and p.gives_way  # 3 of 5: mixed
    assert p.basis["matched_on"] == "counterparty_ref"
    assert (p.basis["agree"], p.basis["of"]) == (3, 5)


def test_unanimous_all_matches_does_not_give_way() -> None:
    e = entry(counterparty_ref="DE99FRIEND", purpose="Konzertkarten")
    p = run("category", e, _friend("Miete Juni", 1, 3))
    assert p is not None and p.value == 1 and not p.gives_way


def test_similar_set_without_majority_falls_back_to_all_matches() -> None:
    votes = (
        _friend("Pizza Essen Freitag", 2) + _friend("Pizza Essen Samstag", 3) + _friend("Miete Juni", 1, 4)
    )
    p = run("category", entry(counterparty_ref="DE99FRIEND", purpose="Pizza Essen Sonntag"), votes)
    # the two similar votes split 1:1; all six: category 1 holds 4 of 6
    assert p is not None and p.value == 1 and p.basis["matched_on"] == "counterparty_ref"
    assert (p.basis["agree"], p.basis["of"]) == (4, 6)


def test_similar_set_with_a_majority_that_is_not_unanimous_gives_way_without_falling_back() -> None:
    votes = (
        _friend("Pizza Essen Freitag", 2, 2) + _friend("Pizza Essen Samstag", 3) + _friend("Miete Juni", 1, 9)
    )
    p = run("category", entry(counterparty_ref="DE99FRIEND", purpose="Pizza Essen Sonntag"), votes)
    assert p is not None and p.value == 2 and p.gives_way
    assert p.basis["matched_on"] == "counterparty_ref+purpose"
    assert (p.basis["agree"], p.basis["of"]) == (2, 3)


def test_purpose_without_tokens_skips_the_narrowing() -> None:
    votes = _friend("Reinigung 48213", 4, 2) + _friend("Reinigung 77", 4)
    p = run("category", entry(counterparty_ref="DE99FRIEND", purpose="48213"), votes)
    assert p is not None and p.value == 4 and not p.gives_way
    assert p.basis["matched_on"] == "counterparty_ref"  # no "+purpose": nothing narrowed


def test_a_vote_without_purpose_tokens_is_not_similar() -> None:
    votes = _friend("123", 1, 2) + _friend("Pizza Essen Freitag", 2)
    p = run("category", entry(counterparty_ref="DE99FRIEND", purpose="Pizza Essen Samstag"), votes)
    assert p is not None and p.value == 2 and p.basis["matched_on"] == "counterparty_ref+purpose"
    assert (p.basis["agree"], p.basis["of"]) == (1, 1)


def test_purpose_similarity_is_jaccard_at_half_on_the_purpose_alone() -> None:
    mk = lambda purpose: [vote(counterparty_ref="CR", purpose=purpose, category_id=1)]  # noqa: E731
    e = entry(counterparty_ref="CR", counterparty_name="alpha beta", purpose="alpha beta")
    narrowed = lambda votes: run("category", e, votes).basis["matched_on"]  # type: ignore[union-attr]  # noqa: E731
    assert narrowed(mk("alpha beta gamma beta")) == "counterparty_ref+purpose"  # 2/3
    assert narrowed(mk("alpha")) == "counterparty_ref+purpose"  # 1/2
    assert narrowed(mk("alpha gamma")) == "counterparty_ref"  # 1/3: all matches decide
    assert narrowed(mk("alpha beta gamma delta zzz")) == "counterparty_ref"  # 2/5
    # the name's words do not count: a purpose of the name alone is no purpose in common
    other = [vote(counterparty_ref="CR", purpose="beta", category_id=1)]
    assert run("category", entry(counterparty_ref="CR", counterparty_name="alpha", purpose="alpha"), other)
    assert (
        run("category", entry(counterparty_ref="CR", counterparty_name="beta", purpose="alpha"), other).basis[
            "matched_on"
        ]  # type: ignore[union-attr]
        == "counterparty_ref"
    )


def test_every_key_and_field_is_refined_by_the_purpose() -> None:
    by_name = [
        vote(counterparty_name="Shop", purpose="Abo Magazin", payee_id=5, category_id=1),
        vote(counterparty_name="Shop", purpose="Abo Magazin", payee_id=5, category_id=1),
        vote(counterparty_name="Shop", purpose="Einkauf Haus", payee_id=6, category_id=2),
        vote(counterparty_name="Shop", purpose="Einkauf Haus", payee_id=6, category_id=2),
        vote(counterparty_name="Shop", purpose="Einkauf Haus", payee_id=6, category_id=2),
    ]
    e = entry(counterparty_name="Shop", purpose="Abo Zeitung Magazin")
    p = run("payee", e, by_name)
    assert (
        p is not None and p.value == 5 and p.basis["matched_on"] == "counterparty_name+booking_text+purpose"
    )
    by_payee = [
        vote(payee_id=7, purpose="Rate Auto", category_id=8),
        vote(payee_id=7, purpose="Sonst", category_id=9),
    ]
    p = run("category", entry(purpose="Rate Auto"), by_payee, payee=7)
    assert p is not None and p.value == 8 and p.basis["matched_on"] == "payee+purpose"
    kinds = [
        vote(counterparty_ref="CR", purpose="Umbuchung Sparen", type="transfer"),
        vote(counterparty_ref="CR", purpose="Pizza", type="flow", category_id=1),
        vote(counterparty_ref="CR", purpose="Pizza", type="flow", category_id=1),
    ]
    p = run("type", entry(counterparty_ref="CR", purpose="Umbuchung Sparen"), kinds)
    assert p is not None and p.value == "transfer" and p.basis["matched_on"] == "counterparty_ref+purpose"


def test_only_a_category_gives_way() -> None:
    votes = flows(2, counterparty_ref="CR", payee_id=3, category_id=1) + flows(
        1, counterparty_ref="CR", payee_id=4, category_id=2
    )
    e = entry(counterparty_ref="CR")
    assert run("category", e, votes).gives_way  # type: ignore[union-attr]
    p = run("payee", e, votes)
    assert p is not None and p.value == 3 and not p.gives_way


# ---- the categories the model is told ----


def _seen(
    e: EntryInput, votes: list[Vote], paths: dict[int, str] | None = None, payee: int | None = None
) -> tuple[int, ...]:
    resolved = {"payee": Proposal("payee", payee, {})} if payee is not None else {}
    ctx = ClassifierContext(resolved=resolved, history=ListHistory(votes, paths))  # type: ignore[arg-type]
    return H.categories_seen(e, ctx)


def test_categories_seen_are_the_top_three_by_count_then_path_in_path_order() -> None:
    paths = {1: "Expense > Food", 2: "Expense > Housing", 3: "Expense > Leisure", 4: "Expense > Auto"}
    votes = (
        _friend("a", 2, 5)  # most frequent
        + _friend("b", 3, 2)  # tied with Food and Auto: Auto, Food rank before Leisure by path
        + _friend("c", 1, 2)
        + _friend("d", 4, 2)
    )
    seen = _seen(entry(counterparty_ref="DE99FRIEND", purpose="zzz"), votes, paths)
    assert seen == (4, 1, 2)  # Auto, Food, Housing: 5, then the ties by path (Auto, Food); Leisure is out


def test_categories_seen_take_all_matches_not_only_the_similar_ones() -> None:
    seen = _seen(
        entry(counterparty_ref="DE99FRIEND", purpose="Pizza Essen Samstag"), FRIEND, {1: "A", 2: "B"}
    )
    assert seen == (1, 2)


def test_categories_seen_come_from_the_first_key_that_has_any() -> None:
    votes = [
        vote(counterparty_ref="CR", type="transfer"),  # key 1 counts no category
        vote(counterparty_name="Shop", category_id=7),
    ]
    e = entry(counterparty_ref="CR", counterparty_name="Shop")
    assert _seen(e, votes) == (7,)
    assert _seen(entry(counterparty_ref="CR"), votes) == ()


def test_categories_seen_by_payee_and_none_for_a_booking_or_without_history() -> None:
    votes = flows(2, payee_id=7, category_id=9)
    assert _seen(entry(), votes, payee=7) == (9,)
    assert _seen(entry(), votes) == ()
    assert (
        _seen(
            entry(booking="document", counterparty_ref="CR"), flows(1, counterparty_ref="CR", category_id=1)
        )
        == ()
    )
    assert H.categories_seen(entry(counterparty_ref="CR"), ClassifierContext()) == ()


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


def test_paypal_payee_follows_the_counterparty_category_follows_the_purpose() -> None:
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
    # all three match: payee 3 agrees 3 of 3, but the categories split
    assert run("payee", e, past) is not None
    assert run("category", e, past) is None
    # the merchant behind the intermediary is in the purpose
    again = entry(counterparty_name="PayPal Europe S.a.r.l.", purpose="PAYPAL Netflix")
    p = run("category", again, past)
    assert (
        p is not None and p.value == 2 and p.basis["matched_on"] == "counterparty_name+booking_text+purpose"
    )
    # another descriptor shares no key: nothing, whatever the words
    assert run("payee", entry(counterparty_name="PayPal (Europe)", purpose="PAYPAL Kindle"), past) is None


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


# ---- a booking's entries take no part in history (D230) ----


def test_a_booking_entry_is_never_asked_by_history() -> None:
    votes = [vote(counterparty_ref="X", counterparty_name="Amazon", payee_id=7, category_id=5)] * 3
    history = ListHistory(votes)
    ctx = ClassifierContext(history=history)
    for kind in ("document", "transfer"):
        e = entry(booking=kind, source_text="Paperback", counterparty_ref="X", counterparty_name="Amazon")
        assert all(H.propose(f, e, ctx) is None for f in ("type", "payee", "category", "counter_account"))
    assert history.calls == []
    assert H.propose("category", entry(counterparty_ref="X"), ctx) is not None
