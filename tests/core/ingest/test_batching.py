"""The batched write path: chunk edges and accounting (spec §5.1-§5.2)."""

from __future__ import annotations

from typing import Any

import pytest

from app.core.ingest import run as run_module
from app.core.ingest.entries import insert_entry
from app.core.ingest.run import start_run
from tests.core.ingest.conftest import Env, row


def _entries_per_source(env: Env) -> list[Any]:
    return env.q(
        "SELECT s.id, s.duplicate_of, count(e.id) AS n FROM source_transaction s"
        " LEFT JOIN ledger_entry e ON e.source_transaction_id = s.id GROUP BY s.id ORDER BY s.id"
    )


def test_a_delivery_larger_than_one_chunk_gets_one_entry_per_row_in_delivery_order(env: Env) -> None:
    rows = [row(-(100 + i), source_id=f"r{i}" if i % 2 else None, purpose=f"p{i}") for i in range(2_500)]
    res = env.deliver(rows)
    assert res.inserted == 2_500 and res.skipped_by_identity == 0 and res.duplicates == ()
    got = env.q("SELECT amount FROM ledger_entry ORDER BY id")
    assert [g.amount for g in got] == [-(100 + i) for i in range(2_500)]
    assert all(r.n == 1 for r in _entries_per_source(env))


def test_chunk_boundaries_with_duplicates_across_chunks(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_module, "_CHUNK", 3)
    first = env.deliver([row(-(100 + i), purpose=f"p{i}") for i in range(4)])
    assert first.inserted == 4
    # 8 rows: i=1 and i=6 pair with earlier rows (same day and amount, other text)
    rows = [row(-(100 + i), purpose=f"other{i}") for i in (1, 6)] + [row(-(900 + i)) for i in range(6)]
    res = env.deliver(rows)
    assert res.inserted == 7 and len(res.duplicates) == 1 and res.skipped_by_identity == 0
    states = _entries_per_source(env)
    assert len(states) == 4 + 8
    assert all((s.n == 0) == (s.duplicate_of is not None) for s in states)
    assert [d[0] for d in res.duplicates] == [s.id for s in states if s.duplicate_of is not None]


def test_identity_conflict_mid_chunk_is_skipped_without_an_entry(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_module, "_CHUNK", 3)
    real = run_module._amount_step
    other = start_run(env.engine, env.account, "transactions", importer="csv")

    def racing(conn: Any, account_id: int, remaining: Any, used: Any) -> Any:
        out = real(conn, account_id, remaining, used)
        # a concurrent run commits the identity of row 4 after the identity step looked
        with env.engine.begin() as other_conn:
            other_conn.execute(
                run_module.text(
                    "INSERT INTO source_transaction (origin, importer, import_run_id, account_id, source_id,"
                    " amount, currency, booked_on, raw, source_format)"
                    " VALUES ('import', 'csv', :r, :a, 's4', -1, 'EUR', '2020-01-01', '{}', 'csv:test')"
                ),
                {"r": other, "a": account_id},
            )
            insert_entry(
                other_conn,
                other_conn.execute(run_module.text("SELECT max(id) FROM source_transaction")).scalar_one(),
            )
        return out

    monkeypatch.setattr(run_module, "_amount_step", racing)
    res = env.deliver([row(-(500 + i), source_id=f"s{i}") for i in range(8)])
    assert res.skipped_by_identity == 1 and res.inserted == 7
    states = _entries_per_source(env)
    assert len(states) == 8 and all(s.n == 1 for s in states)  # 7 delivered + the concurrent one
    assert env.run_row(res.run_id).stats["skipped_by_identity"] == 1


def test_an_all_duplicates_delivery_inserts_sources_and_no_entries(env: Env) -> None:
    env.deliver([row(-(100 + i), purpose=f"p{i}") for i in range(5)])
    res = env.deliver([row(-(100 + i), purpose=f"other{i}") for i in range(5)])
    assert res.inserted == 0 and len(res.duplicates) == 5
    assert env.count("ledger_entry") == 5 and env.count("source_transaction") == 10


def test_an_empty_delivery_writes_nothing_and_completes_the_run(env: Env) -> None:
    res = env.deliver([])
    assert (res.inserted, res.duplicates, res.skipped_by_identity) == (0, (), 0)
    assert env.count("source_transaction") == 0 and env.run_row(res.run_id).status == "ok"
