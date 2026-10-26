"""The history snapshot: same candidates as the list oracle (modulo lookback), and its loader."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, timedelta

import pytest
from sqlalchemy import Connection

from app.core.plugins.classifier import HISTORY_KEYS, EntryInput
from app.core.resolution.confirmed import load_confirmed_ids
from app.core.resolution.snapshot import (
    LOOKBACK_DAYS,
    TOKEN_REACH,
    HistorySnapshot,
    load_snapshot,
    load_votes,
    load_votes_of,
    touches,
)
from app.plugins.classifiers.history import JACCARD_MIN
from tests.core.units.helpers import Bench, keys
from tests.invariants.helpers import make_category, make_entry, make_source
from tests.plugins.classifiers.fakes import ListHistory, entry, vote

VOTES = [
    vote(counterparty_ref="DE01", counterparty_name="Rewe Markt", purpose="Einkauf Rewe", payee_id=7),
    vote(counterparty_ref="de 01", counterparty_name="REWE-Markt", purpose="Kartenzahlung", booking_text="K"),
    vote(
        counterparty_name="Lidl",
        purpose="Einkauf Lidl",
        payee_id=8,
        booking_text="K",
        booked_on=date(2026, 5, 1),
    ),
    vote(counterparty_name="Rewe Sagt Danke", purpose="Rewe", payee_id=7, account_id=2),
    vote(),
]
ENTRIES = [
    entry(counterparty_ref="DE01", counterparty_name="Rewe Markt", purpose="Einkauf", booking_text="K"),
    entry(counterparty_name="LIDL", purpose="Einkauf", booking_text="k", account_id=2),
    entry(),
    entry(counterparty_name="Unknown", purpose="Nothing here"),
]


def _ids(votes: object) -> list[int]:
    return [v.entry_id for v in votes]  # type: ignore[attr-defined]


@pytest.mark.parametrize("e", ENTRIES)
@pytest.mark.parametrize("key", HISTORY_KEYS)
@pytest.mark.parametrize("payee", [None, 7])
def test_same_candidates_as_the_list_oracle(e: EntryInput, key: str, payee: int | None) -> None:
    snap, oracle = HistorySnapshot(VOTES), ListHistory(VOTES)
    got = snap.candidates(key, e, payee_id=payee)  # type: ignore[arg-type]
    want = oracle.candidates(key, e, payee_id=payee)  # type: ignore[arg-type]
    assert _ids(got) == sorted(
        _ids(want), key=lambda i: next((v.booked_on, v.entry_id) for v in VOTES if v.entry_id == i)
    )


def test_exclusion_and_incremental_add_match_a_fresh_snapshot() -> None:
    e = ENTRIES[0]
    full = HistorySnapshot(VOTES)
    grown = HistorySnapshot(VOTES[:2])
    grown.add(VOTES[2:])
    grown.add(VOTES)  # already held: ignored
    for key in HISTORY_KEYS:
        assert _ids(grown.candidates(key, e, payee_id=7)) == _ids(full.candidates(key, e, payee_id=7))
    skip = frozenset({VOTES[0].entry_id})
    assert VOTES[0].entry_id not in _ids(full.candidates("counterparty_ref", e, exclude_entry_ids=skip))
    assert len(grown) == len(VOTES)


def test_candidates_are_ordered_by_date_then_id_whatever_the_load_order() -> None:
    vs = [vote(counterparty_ref="X", booked_on=date(2026, 3, d)) for d in (9, 3, 5)]
    vs.append(vote(counterparty_ref="X", booked_on=date(2026, 3, 3)))
    ordered = sorted(vs, key=lambda v: (v.booked_on, v.entry_id))
    for load in (vs, vs[::-1]):
        got = HistorySnapshot(load).candidates("counterparty_ref", entry(counterparty_ref="X"))
        assert _ids(got) == _ids(ordered)


def test_lookback_is_a_year_either_side() -> None:
    day = date(2026, 6, 1)
    near = [
        vote(counterparty_ref="X", booked_on=day - timedelta(days=LOOKBACK_DAYS)),
        vote(counterparty_ref="X", booked_on=day + timedelta(days=LOOKBACK_DAYS)),
    ]
    far = [
        vote(counterparty_ref="X", booked_on=day - timedelta(days=LOOKBACK_DAYS + 1)),
        vote(counterparty_ref="X", booked_on=day + timedelta(days=LOOKBACK_DAYS + 1)),
    ]
    snap = HistorySnapshot(near + far)
    e = entry(counterparty_ref="X", counterparty_name="X", booked_on=day)
    assert _ids(snap.candidates("counterparty_ref", e)) == _ids(near)
    snap_t = HistorySnapshot([vote(counterparty_name="alpha", booked_on=v.booked_on) for v in near + far])
    assert len(snap_t.candidates("tokens", entry(counterparty_name="alpha", booked_on=day))) == 2


def test_token_reach_is_the_classifiers_threshold() -> None:
    assert TOKEN_REACH == JACCARD_MIN


def test_touches_is_exact_for_equality_keys_and_similarity_for_tokens() -> None:
    grown = HistorySnapshot().add(
        [vote(counterparty_ref="R1", counterparty_name="Alpha Shop", purpose="Einkauf", payee_id=5)]
    )
    assert touches(grown, entry(counterparty_ref="r-1"), None)
    assert touches(grown, entry(counterparty_name="ALPHA SHOP"), None)
    assert touches(grown, entry(counterparty_name="zzz"), 5)
    assert touches(grown, entry(counterparty_name="alpha", purpose="einkauf shop"), None)
    assert not touches(grown, entry(counterparty_name="alpha beta gamma delta"), None)  # 1 of 5 tokens
    assert not touches(grown, entry(counterparty_name="Other"), 6)
    assert not touches(grown, entry(), None)  # an empty value is never a key


# -- the loader -----------------------------------------------------------------------------------

MakeAccount = Callable[..., int]


def _d(**keys: str) -> str:
    return json.dumps({k: {"pass": v} for k, v in keys.items()})


def test_only_confirmed_units_vote(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    cat = make_category(db_conn, "Food")
    ok = make_entry(
        db_conn, make_source(db_conn, acct), category_id=cat, derivation=_d(type="user", category="rule")
    )
    proposal = make_entry(
        db_conn, make_source(db_conn, acct), category_id=cat, derivation=_d(category="history")
    )
    unclassified = make_entry(db_conn, make_source(db_conn, acct))
    untyped = make_entry(db_conn, make_source(db_conn, acct), type=None)
    transfer = make_entry(
        db_conn,
        make_source(db_conn, acct),
        type="transfer",
        counter_account_id=make_account(db_conn, name="B"),
    )
    split_src = make_source(db_conn, acct, amount=-1000)
    half_ok = make_entry(db_conn, split_src, amount=-600, category_id=cat)
    half_open = make_entry(db_conn, split_src, amount=-400)
    got = {v.entry_id for v in load_votes(db_conn)}
    assert got == {ok}
    assert load_confirmed_ids(db_conn) == {ok}
    assert len(load_snapshot(db_conn)) == 1
    assert not {proposal, unclassified, untyped, transfer, half_ok, half_open} & got


def test_a_vote_carries_its_source_facts(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    cat = make_category(db_conn, "Food")
    src = make_source(db_conn, acct, booked_on=date(2026, 4, 2), purpose="Einkauf")
    e = make_entry(db_conn, src, category_id=cat)
    (v,) = load_votes(db_conn)
    assert (v.entry_id, v.account_id, v.booked_on, v.type, v.category_id) == (
        e,
        acct,
        date(2026, 4, 2),
        "flow",
        cat,
    )
    assert v.purpose == "Einkauf" and v.counter_account_id is None


def test_a_leg_whose_partner_is_unconfirmed_does_not_vote(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    """The unit votes as a whole (I19): a pair, its siblings and a proposal on one leg."""
    b = Bench(db_conn, make_account)
    clean_a, clean_b = b.transfer(b.source()), b.transfer(b.source(b.b))
    b.pair(clean_a, clean_b)
    held_a = b.transfer(b.source())
    held_b = b.transfer(b.source(b.b), derivation=keys(counter_account="history"))
    sibling = b.flow(b.source())  # alone and clean: votes
    b.pair(held_a, held_b)
    assert {v.entry_id for v in load_votes(db_conn)} == {clean_a, clean_b, sibling}
    assert {v.entry_id for v in load_votes_of(db_conn, [held_a, clean_b])} == {clean_b}


# -- key 5: the source text (D230) ----------------------------------------------------------------

TEXT_VOTES = [
    vote(source_text="USB-C cable", counterparty_name="Amazon", payee_id=7),
    vote(source_text="usb c CABLE", counterparty_name="Amazon", payee_id=7, booked_on=date(2026, 4, 1)),
    vote(source_text="Paperback", counterparty_name="Amazon"),
    vote(counterparty_name="Amazon", purpose="order shipment", payee_id=7),
]


@pytest.mark.parametrize("text_", ["USB-C Cable", "paperback", "other", None])
@pytest.mark.parametrize("key", [*HISTORY_KEYS, "source_text"])
def test_source_text_candidates_match_the_list_oracle(text_: str | None, key: str) -> None:
    e = entry(source_text=text_, counterparty_name="Amazon", purpose="order shipment")
    got = HistorySnapshot(TEXT_VOTES).candidates(key, e, payee_id=7)  # type: ignore[arg-type]
    want = ListHistory(TEXT_VOTES).candidates(key, e, payee_id=7)  # type: ignore[arg-type]
    assert sorted(_ids(got)) == sorted(_ids(want))


def test_a_vote_with_a_source_text_is_a_candidate_for_keys_3_and_5_only() -> None:
    snap = HistorySnapshot(TEXT_VOTES)
    amazon = entry(counterparty_name="Amazon", purpose="order shipment")
    assert _ids(snap.candidates("counterparty_name", amazon)) == [TEXT_VOTES[3].entry_id]
    assert _ids(snap.candidates("tokens", amazon)) == [TEXT_VOTES[3].entry_id]
    assert len(snap.candidates("payee", amazon, payee_id=7)) == 3


def test_touches_for_an_entry_with_a_source_text_reads_keys_5_and_3_only() -> None:
    grown = HistorySnapshot().add([vote(counterparty_name="Alpha Shop", purpose="Einkauf", payee_id=5)])
    assert not touches(grown, entry(source_text="x", counterparty_name="Alpha Shop"), None)
    assert touches(grown, entry(source_text="x"), 5)
    grown = HistorySnapshot().add([vote(source_text="USB-C cable")])
    assert touches(grown, entry(source_text="usb c Cable"), None)
    assert not touches(grown, entry(source_text="other"), None)
    assert not touches(grown, entry(counterparty_name="USB cable"), None)
