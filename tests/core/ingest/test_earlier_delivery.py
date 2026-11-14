"""An earlier delivery, skipped by identity, is recorded (spec §5.2, §3.10, D256)."""

from __future__ import annotations

from datetime import date

from app.core.ingest.revert import revert_run
from app.core.plugins.importer import IncomingRow
from tests.core.ingest.conftest import Env, row


def d(month: int, day: int) -> date:
    return date(2026, month, day)


def _rows() -> list[IncomingRow]:
    return [row(-100, d(1, 10), source_id="a"), row(-50, d(2, 10), source_id="b")]


def _recorded(env: Env, run_id: int | None) -> int:
    return len(env.q("SELECT * FROM source_transaction_earlier_delivery WHERE import_run_id = :r", r=run_id))


def _derived(env: Env) -> list[tuple[str, int]]:
    return [
        (r.type, r.amount)
        for r in env.q(
            "SELECT type, amount FROM ledger_entry WHERE balance_record_id IS NOT NULL ORDER BY id"
        )
    ]


def _long_run(env: Env) -> None:
    env.deliver(
        _rows(),
        covered_from=d(1, 1),
        covered_through=d(3, 31),
        reported_balance=-150,
        reported_balance_on=d(3, 31),
    )


def test_a_run_ending_earlier_records_what_it_skipped_and_anchors_correctly(env: Env) -> None:
    _long_run(env)
    short = env.deliver(
        _rows(),
        covered_from=d(1, 1),
        covered_through=d(2, 28),
        reported_balance=-150,
        reported_balance_on=d(2, 28),
    )
    assert short.skipped_by_identity == 2 and short.inserted == 0
    assert _recorded(env, short.run_id) == 2
    # the bank's February balance already held both rows: no opening, no reconciliation
    assert _derived(env) == []


def test_a_run_delivering_new_rows_records_nothing(env: Env) -> None:
    _long_run(env)
    assert _derived(env) == []
    run = env.deliver([row(-5, d(2, 5), source_id="c")], covered_from=d(2, 1), covered_through=d(2, 28))
    assert run.inserted == 1 and _recorded(env, run.run_id) == 0


def test_a_run_ending_on_the_same_day_or_later_records_nothing(env: Env) -> None:
    first = env.deliver(_rows(), covered_from=d(1, 1), covered_through=d(2, 28))
    same = env.deliver(_rows(), covered_from=d(1, 1), covered_through=d(2, 28))
    later = env.deliver(_rows(), covered_from=d(1, 1), covered_through=d(3, 31))
    assert first.inserted == 2
    assert (same.skipped_by_identity, later.skipped_by_identity) == (2, 2)
    assert env.count("source_transaction_earlier_delivery") == 0


def test_the_skip_is_recorded_against_the_row_that_was_hit_even_a_duplicate(env: Env) -> None:
    env.deliver([row(-100, d(1, 10), source_id="a")], covered_from=d(1, 1), covered_through=d(3, 31))
    # a second delivery of the same movement, rendered differently, is inserted as a duplicate
    dup = env.deliver([row(-100, d(1, 10), source_id="a2")], covered_from=d(1, 1), covered_through=d(3, 31))
    assert len(dup.duplicates) == 1
    dup_id = env.q("SELECT id FROM source_transaction WHERE source_id = 'a2'")[0].id
    early = env.deliver([row(-100, d(1, 10), source_id="a2")], covered_from=d(1, 1), covered_through=d(2, 28))
    assert env.q(
        "SELECT source_transaction_id FROM source_transaction_earlier_delivery WHERE import_run_id = :r",
        r=early.run_id,
    ) == [(dup_id,)]
    assert env.count("source_transaction_earlier_delivery") == 1  # the original is not skipped again


def test_a_revert_removes_what_its_run_recorded(env: Env) -> None:
    _long_run(env)
    short = env.deliver(_rows(), covered_from=d(1, 1), covered_through=d(2, 28))
    assert _recorded(env, short.run_id) == 2
    assert short.run_id is not None
    revert_run(env.engine, short.run_id, user_id=None)
    assert env.count("source_transaction_earlier_delivery") == 0
    assert env.count("source_transaction") == 2
