"""The backfill generator: deterministic, one entry per source row, a clean ledger."""

from __future__ import annotations

import hashlib

from sqlalchemy import Engine, text

from app.core.settle.settle import settle
from tests.fixtures.backfill import build_backfill

SMALL = {"accounts": 3, "rows_per_account": 60}


def _digest(engine: Engine, account_id: int) -> str:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT amount, currency, booked_on, counterparty_ref, counterparty_name, purpose,"
                " source_id, content_hash FROM source_transaction WHERE account_id = :a"
                " ORDER BY id"
            ),
            {"a": account_id},
        ).all()
    return hashlib.sha256(repr([tuple(r) for r in rows]).encode()).hexdigest()


def test_same_seed_builds_the_same_ledger(isolated_engine: Engine):
    one = build_backfill(isolated_engine, seed=7, **SMALL)
    two = build_backfill(isolated_engine, seed=7, **SMALL)
    other = build_backfill(isolated_engine, seed=8, **SMALL)
    for a, b, c in zip(one.account_ids, two.account_ids, other.account_ids, strict=True):
        assert _digest(isolated_engine, a) == _digest(isolated_engine, b)
        assert _digest(isolated_engine, a) != _digest(isolated_engine, c)


def test_counts_and_summary(isolated_engine: Engine):
    s = build_backfill(isolated_engine, seed=1, **SMALL)
    assert len(s.account_ids) == 3 and len(s.run_ids) == 3
    assert s.source_count == s.entry_count == 180
    with isolated_engine.connect() as conn:
        n_src = conn.execute(text("SELECT count(*) FROM source_transaction")).scalar_one()
        n_ent = conn.execute(text("SELECT count(*) FROM ledger_entry")).scalar_one()
        lo, hi = conn.execute(text("SELECT min(booked_on), max(booked_on) FROM source_transaction")).one()
    assert n_src == n_ent == 180
    assert s.first_booked <= lo and hi <= s.last_booked
    assert (s.last_booked - s.first_booked).days >= 330  # a year of spread


def test_every_source_row_has_exactly_one_entry(isolated_engine: Engine):
    build_backfill(isolated_engine, seed=2, **SMALL)
    with isolated_engine.connect() as conn:
        bad = conn.execute(
            text(
                "SELECT s.id FROM source_transaction s LEFT JOIN ledger_entry e"
                " ON e.source_transaction_id = s.id GROUP BY s.id HAVING count(e.id) <> 1"
            )
        ).all()
    assert bad == []


def test_check_views_are_empty(isolated_engine: Engine):
    build_backfill(isolated_engine, seed=3, **SMALL)
    with isolated_engine.connect() as conn:
        views = (
            conn.execute(
                text("SELECT viewname FROM pg_views WHERE schemaname = 'public' AND viewname ~ '^v_check_'")
            )
            .scalars()
            .all()
        )
        assert views
        for view in views:
            found = conn.execute(text(f"SELECT count(*) FROM {view}")).scalar_one()  # noqa: S608
            assert found == 0, view


def test_all_entries_are_unclassified_after_settle(isolated_engine: Engine):
    s = build_backfill(isolated_engine, seed=4, **SMALL)
    result = settle(isolated_engine)
    assert result.error is None and len(result.touched_entry_ids) == s.entry_count
    with isolated_engine.connect() as conn:
        flags = conn.execute(text("SELECT DISTINCT review_flags FROM ledger_entry")).scalars().all()
    assert flags == [["unclassified"]]
