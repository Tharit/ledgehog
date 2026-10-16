"""The pure unit judgement equals the SQL: unit keys, confirmation and flags, over generated units.

Scenarios: single sources, splits, pairs, splits with a paired residual (siblings on one or both legs),
a partner that is unconfirmed, proposals and unclassified entries here and there, and derived entries
(in no unit). Every scenario lives in one rolled-back transaction; all are compared at once.
"""

from __future__ import annotations

import random
from typing import Any

import pytest
from sqlalchemy import Connection, text

from app.core.resolution.confirmed import units_binds, units_sql
from app.core.settle.flags import recompute_review_flags
from app.core.units.closure import UnitEntry, unit_keys, units_of
from app.core.units.state import unit_state
from tests.core.units.helpers import Bench, D, keys
from tests.fixtures import ledger_seed as seed

_KEY_CHOICES = ["", "", "", "rule", "user", "own_account", "history", "llm", "matcher_proposal"]


def _derivation(rng: random.Random) -> str:
    chosen = rng.choice(_KEY_CHOICES)
    # the user's decision of no payee: a standing `user` key on a NULL payee (never makes a unit unconfirmed)
    passes = {"payee": "user"} if rng.random() < 0.25 else {}
    if chosen:
        passes["category"] = chosen
    return keys(**passes) if passes else "{}"


def _scenario(bench: Bench, rng: random.Random) -> None:
    """One random unit: a source with 1-3 entries, optionally a paired second source with 0-2 siblings."""
    n = rng.randint(1, 3)
    src = bench.source(on=D, parts=n)
    paired = rng.random() < 0.4
    transfers: list[int] = []
    for i in range(n):
        as_transfer = i == 0 and (paired or rng.random() < 0.15)
        if as_transfer:
            transfers.append(bench.transfer(src, derivation=_derivation(rng)))
        elif rng.random() < 0.1:
            bench.flow(src, done=False, type=None, derivation=_derivation(rng))
        else:
            bench.flow(src, done=rng.random() < 0.7, derivation=_derivation(rng))
    if paired and transfers:
        siblings = rng.randint(0, 2)
        other = bench.source(bench.b, on=D, amount=100, parts=1 + siblings)
        leg = bench.transfer(other, derivation=_derivation(rng))
        for _ in range(siblings):
            bench.flow(other, done=rng.random() < 0.8, derivation=_derivation(rng))
        bench.pair(transfers[0], leg)


def _load(conn: Connection) -> list[UnitEntry]:
    rows = conn.execute(
        text(
            "SELECT id, source_transaction_id, type, category_id, counterpart_entry_id, derivation"
            " FROM ledger_entry"
        )
    )
    return [
        UnitEntry(
            id=r.id,
            source_transaction_id=r.source_transaction_id,
            type=r.type,
            category_id=r.category_id,
            counterpart_entry_id=r.counterpart_entry_id,
            derivation=r.derivation,
        )
        for r in rows
    ]


@pytest.mark.parametrize("seed_value", [1, 2, 3])
def test_pure_judgement_equals_sql(db_conn: Connection, make_account: Any, seed_value: int) -> None:
    bench = Bench(db_conn, make_account)
    rng = random.Random(seed_value)
    for _ in range(60):
        _scenario(bench, rng)
    seed.derived(db_conn, bench.a)  # a derived entry: in no unit, no flags
    recompute_review_flags(db_conn)

    entries = _load(db_conn)
    keys_ = unit_keys(entries)
    states = {k: unit_state(v) for k, v in units_of(entries).items()}
    sql = {
        r.id: r
        for r in db_conn.execute(text(f"WITH units AS ({units_sql()}) SELECT * FROM units"), units_binds())
    }
    # the unit judgement: `waiting` and `unmatched_transfer` are the matcher's (test_flags_matching.py)
    matching = {"waiting", "unmatched_transfer"}
    stored = {
        r.id: [f for f in r.review_flags if f not in matching]
        for r in db_conn.execute(text("SELECT id, review_flags FROM ledger_entry"))
    }

    movements = [e for e in entries if e.source_transaction_id is not None]
    assert set(sql) == {e.id for e in movements} == set(keys_)
    assert len({k for k in keys_.values()}) < len(movements)  # the scenarios do form multi-entry units
    kinds = {s.reasons for s in states.values()}
    assert (
        () in kinds and any("non_standing_keys" in r for r in kinds) and any("incomplete" in r for r in kinds)
    )
    assert any(r == ("unpaired_transfer",) or "unpaired_transfer" in r for r in kinds)
    for e in movements:
        row, state = sql[e.id], states[keys_[e.id]]
        assert row.unit_key == keys_[e.id], e
        assert row.unit_ok == state.confirmed, e
        assert row.unit_has_nonstanding == ("non_standing_keys" in state.reasons), e
        assert stored[e.id] == list(state.flags[e.id]), e
    for e in entries:
        if e.source_transaction_id is None:
            assert stored[e.id] == []
