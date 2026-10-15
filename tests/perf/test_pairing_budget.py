"""Transfer pairing and the transfer flags stay inside the settle budget (architecture §5.2, spec §5.7).

The fixture is the ~70% confirmed ledger (5,600 voters) plus 800 transfer legs: 160 pairs settling still
has to make, 100 pairs already made and confirmed, and 280 unpaired legs, half waiting on a synced
counter-account, half unmatched (`tests/fixtures/backfill.py`). Numbers are printed (run with -s).

The step is timed on its own before the first settle (a rolled-back transaction, so it does real work:
load the unpaired legs, pair, write) and the flag statement after it, as a full rewrite (every stored
flag cleared first: the worst case) and as the idle statement a settled ledger runs. The whole settle
is held to `BUDGET_SECONDS`, first pass and idle second pass.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, text

from app.core.integrity import check_integrity
from app.core.settle.flags import recompute_review_flags
from app.core.settle.pairing import pair_transfers_step
from app.core.settle.settle import settle
from tests.perf.budget import BUDGET_SECONDS
from tests.perf.conftest import Backfill

pytestmark = pytest.mark.perf
REPEATS = 5


def _rolled_back(engine: Engine, work: Callable[[Connection], Any]) -> tuple[float, Any]:
    """Time `work` inside the settle's setting, in a transaction that is rolled back."""
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text("SELECT set_config('ledger.settling', 'on', true)"))
            started = time.perf_counter()
            result = work(conn)
            return time.perf_counter() - started, result
        finally:
            trans.rollback()


@pytest.fixture(scope="module")
def measured(backfill_transfers: Backfill) -> dict[str, Any]:
    engine = backfill_transfers.engine
    out: dict[str, Any] = {}
    samples = []
    for _ in range(REPEATS):
        elapsed, outcome = _rolled_back(engine, pair_transfers_step)
        samples.append(elapsed)
        out["pairs_touched"] = len(list(outcome.touched))
    out["step"] = samples
    started = time.perf_counter()
    out["first"] = settle(engine)
    out["first_seconds"] = time.perf_counter() - started
    started = time.perf_counter()
    out["second"] = settle(engine)
    out["second_seconds"] = time.perf_counter() - started
    return out


def test_fixture_has_the_transfer_mix(backfill_transfers: Backfill) -> None:
    assert 780 <= backfill_transfers.summary.transfer_count <= 820
    with backfill_transfers.engine.connect() as conn:
        n = conn.execute(text("SELECT count(*) FROM ledger_entry WHERE type = 'transfer'")).scalar_one()
    assert n >= backfill_transfers.summary.transfer_count


def test_the_pairing_step_within_budget(backfill_transfers: Backfill, measured: dict[str, Any]) -> None:
    samples: list[float] = measured["step"]
    assert measured["pairs_touched"] == 320  # 160 pairs, both legs
    print(
        f"\n[perf] pair_transfers step ({backfill_transfers.summary.transfer_count} legs, 160 pairs made):"
        f" median {statistics.median(samples) * 1000:.0f} ms, max {max(samples) * 1000:.0f} ms"
    )
    assert max(samples) <= BUDGET_SECONDS


def test_settle_with_transfers_within_budget(backfill_transfers: Backfill, measured: dict[str, Any]) -> None:
    first, second = measured["first"], measured["second"]
    print(
        f"[perf] settle over the transfer ledger: first {measured['first_seconds'] * 1000:.0f} ms,"
        f" second (nothing to do) {measured['second_seconds'] * 1000:.0f} ms, budget {BUDGET_SECONDS} s"
    )
    assert first.error is None and second.error is None
    assert measured["first_seconds"] <= BUDGET_SECONDS and measured["second_seconds"] <= BUDGET_SECONDS
    assert second.touched_entry_ids == ()  # I37: nothing moves the second time
    with backfill_transfers.engine.connect() as conn:
        unpaired = conn.execute(
            text("SELECT count(*) FROM ledger_entry WHERE type = 'transfer' AND counterpart_entry_id IS NULL")
        ).scalar_one()
        flags = dict(
            conn.execute(
                text(
                    "SELECT f, count(*) FROM ledger_entry, unnest(review_flags) AS f"
                    " WHERE f IN ('waiting', 'unmatched_transfer') GROUP BY f"
                )
            ).all()
        )
        report = check_integrity(conn)
    print(f"[perf]   unpaired transfer legs after settle: {unpaired}, flags {flags}")
    assert unpaired == flags["waiting"] + flags["unmatched_transfer"] and flags["waiting"] > 0
    assert report.ok


def test_the_flag_statement_within_budget(backfill_transfers: Backfill, measured: dict[str, Any]) -> None:
    engine = backfill_transfers.engine
    assert measured["first"].error is None
    idle, _ = _rolled_back(engine, recompute_review_flags)

    def cleared(conn: Connection) -> list[int]:
        conn.execute(text("UPDATE ledger_entry SET review_flags = '{}'"))  # everything differs again
        started = time.perf_counter()
        ids = recompute_review_flags(conn)
        cleared.seconds = time.perf_counter() - started  # type: ignore[attr-defined]
        return ids

    _rolled_back(engine, cleared)
    full: float = cleared.seconds  # type: ignore[attr-defined]
    print(f"[perf] flag statement: idle {idle * 1000:.0f} ms, full rewrite {full * 1000:.0f} ms")
    assert idle <= BUDGET_SECONDS and full <= BUDGET_SECONDS
