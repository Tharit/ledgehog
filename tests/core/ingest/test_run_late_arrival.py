"""A delivery's own coverage counts while its derived entries are recomputed (spec §3.10, D256).

Run A covers January and reports -100 on Jan 31, but misses a Jan 30 movement; run B (through Feb 28)
delivers it late. The preview, the real run and a fresh recompute afterwards must all agree.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.core.balance.derived import load_derivation_input, recompute_derived, record_gaps
from app.core.balance.difference import unexplained_difference
from app.core.ingest.run import RunResult, preview_delivery
from tests.core.ingest.conftest import Env, row


def d(month: int, day: int) -> date:
    return date(2026, month, day)


def _run_a(env: Env) -> None:
    env.deliver(
        [row(-100, d(1, 10), source_id="a")],
        covered_from=d(1, 1),
        covered_through=d(1, 31),
        reported_balance=-100,
        reported_balance_on=d(1, 31),
    )


def _run_b_args() -> dict[str, Any]:
    return {
        "covered_from": d(1, 1),
        "covered_through": d(2, 28),
        "reported_balance": -150,
        "reported_balance_on": d(2, 28),
    }


def _rows_b() -> list[Any]:
    return [row(-100, d(1, 10), source_id="a"), row(-50, d(1, 30), source_id="late")]


def _entries(env: Env) -> list[tuple[Any, ...]]:
    return [
        tuple(r)
        for r in env.q(
            "SELECT balance_record_id, type, booked_on, amount FROM ledger_entry"
            " WHERE balance_record_id IS NOT NULL ORDER BY balance_record_id, type"
        )
    ]


def _expected_difference(env: Env) -> int:
    """What the derivation gives once the run is ok: the sum of the gaps of the reported records."""
    with env.engine.connect() as conn:
        gaps = record_gaps(load_derivation_input(conn, env.account))
    return sum(g.amount for g in gaps if not g.anchor)


def _preview_b(env: Env) -> RunResult:
    return preview_delivery(
        env.engine,
        account_id=env.account,
        instance_id=None,
        importer="csv",
        rows=_rows_b(),
        **_run_b_args(),
    )


def test_late_arrival_real_run_stores_what_a_recompute_gives(env: Env) -> None:
    _run_a(env)
    real = env.deliver(_rows_b(), **_run_b_args())
    stored = _entries(env)
    with env.engine.begin() as conn:
        recompute_derived(conn, env.account)
    assert _entries(env) == stored  # the recompute is a no-op
    expected = _expected_difference(env)
    assert (real.unexplained_difference_after or 0) == expected  # None: no difference
    with env.engine.connect() as conn:
        assert (unexplained_difference(conn, env.account) or 0) == expected
    assert (real.stats["unexplained_difference"]["after"] or 0) == expected


def test_late_arrival_preview_equals_the_real_run(env: Env) -> None:
    _run_a(env)
    before = _entries(env)
    first = _preview_b(env)
    assert _entries(env) == before
    real = env.deliver(_rows_b(), **_run_b_args())
    assert first.unexplained_difference_before == real.unexplained_difference_before
    assert first.unexplained_difference_after == real.unexplained_difference_after
    assert (first.unexplained_difference_after or 0) == _expected_difference(env)  # what the real run left
    # record ids differ (the preview's sequence value is spent), the rest is the same
    assert {**first.stats, "since_zero": None} == {**real.stats, "since_zero": None}
