"""The reported balance of a delivery, its derived entry and the run summary (spec §5.1, §5.10, I36)."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.domain.errors import ContractViolation
from app.core.ingest.run import ingest_delivery, start_run
from tests.core.ingest.conftest import Env, row


def d(day: int) -> date:
    return date(2026, 3, day)


def _checks_clean(env: Env) -> None:
    views = [
        r[0]
        for r in env.q("SELECT table_name FROM information_schema.views WHERE table_name LIKE 'v_check_%'")
    ]
    assert views, "no integrity views found"
    for v in views:
        bad = env.q(f"SELECT * FROM {v}")  # noqa: S608
        assert not bad, f"{v} reports {bad}"


def _derived(env: Env) -> list[tuple[str, int, date]]:
    return [
        (r.type, r.amount, r.booked_on)
        for r in env.q(
            "SELECT type, amount, booked_on FROM ledger_entry WHERE balance_record_id IS NOT NULL"
            " ORDER BY booked_on, id"
        )
    ]


def _nothing_left(env: Env, run_id: int) -> None:
    for table in ("source_transaction", "ledger_entry", "balance_record"):
        assert env.count(table) == 0, table
    r = env.run_row(run_id)
    assert r.status == "failed" and r.covered_through is None and r.covered_from is None


def test_first_record_anchors_with_an_opening_before_the_first_movement(env: Env) -> None:
    res = env.deliver(
        [row(-500, d(10), source_id="a"), row(200, d(12), source_id="b")],
        reported_balance=1000,
        reported_balance_on=d(14),
    )
    # opening = B - movements = 1000 - (-500 + 200), dated the day before the earliest movement
    assert _derived(env) == [("opening", 1300, d(9))]
    rec = env.q("SELECT * FROM balance_record")[0]
    assert (rec.import_run_id, rec.balance, rec.balance_on) == (res.run_id, 1000, d(14))  # reported: a run
    assert res.balance_record_id == rec.id
    stats = env.run_row(res.run_id).stats
    assert stats["balance"] == {"balance_on": "2026-03-14", "balance": 1000}
    assert stats["unexplained_difference"] == {"before": None, "after": None}
    assert stats["since_zero"] == []
    assert (res.unexplained_difference_before, res.unexplained_difference_after) == (None, None)
    _checks_clean(env)


def test_no_balance_means_no_record_and_no_balance_key(env: Env) -> None:
    res = env.deliver([row(-500, d(10), source_id="a")])
    assert res.balance_record_id is None and env.count("balance_record") == 0
    assert "balance" not in env.run_row(res.run_id).stats
    _checks_clean(env)


def test_balance_dated_on_the_coverage_end_is_accepted(env: Env) -> None:
    res = env.deliver(
        [row(-1, source_id="a")], reported_balance=7, reported_balance_on=d(14), covered_through=d(14)
    )
    assert res.balance_record_id is not None


def test_covered_from_is_stored(env: Env) -> None:
    res = env.deliver([row(-1, source_id="a")], covered_from=d(1), covered_through=d(14))
    assert env.run_row(res.run_id).covered_from == d(1)


def test_a_matching_second_balance_needs_no_reconciliation(env: Env) -> None:
    """Architecture §8, the two-run rule: run 1's record anchors; run 2 overlaps and reports the truth."""
    env.deliver(
        [row(-300, d(5), source_id="a"), row(100, d(8), source_id="b")],
        covered_through=d(10),
        reported_balance=5000,
        reported_balance_on=d(10),
    )
    assert _derived(env) == [("opening", 5200, d(4))]  # 5000 - (-300 + 100)
    # overlapping window: the same Mar 8 booking again (skipped by identity), plus a new one
    res = env.deliver(
        [row(100, d(8), source_id="b"), row(-400, d(15), source_id="c")],
        covered_from=d(8),
        covered_through=d(20),
        reported_balance=4600,  # 5000 - 400
        reported_balance_on=d(20),
    )
    assert res.skipped_by_identity == 1 and res.inserted == 1
    assert [t for t, _, _ in _derived(env)] == ["opening"]  # the reconciliation is zero: no entry
    assert res.unexplained_difference_after is None
    assert env.run_row(res.run_id).stats["since_zero"] == []
    _checks_clean(env)


def test_a_disagreeing_balance_leaves_a_reconciliation_the_summary_reports(env: Env) -> None:
    env.deliver([row(-500, d(10), source_id="a")], reported_balance=1000, reported_balance_on=d(14))
    res = env.deliver(
        [row(-100, d(16), source_id="b")],
        covered_through=d(20),
        reported_balance=850,  # expected 1000 - 100 = 900
        reported_balance_on=d(20),
    )
    # (850 - 1000) - (-100) = -50
    assert _derived(env) == [("opening", 1500, d(9)), ("reconciliation", -50, d(20))]
    stats = env.run_row(res.run_id).stats
    assert stats["unexplained_difference"] == {"before": None, "after": -50}
    assert stats["since_zero"] == [res.balance_record_id]
    assert (res.unexplained_difference_before, res.unexplained_difference_after) == (None, -50)
    _checks_clean(env)


def test_before_is_the_value_prior_to_the_delivery(env: Env) -> None:
    env.deliver([row(-500, d(10), source_id="a")], reported_balance=1000, reported_balance_on=d(14))
    env.deliver(
        [row(-100, d(16), source_id="b")],
        covered_through=d(20),
        reported_balance=850,
        reported_balance_on=d(20),
    )
    # a delivery without a balance changes nothing: before == after == -50
    quiet = env.deliver([row(-10, d(21), source_id="c")], covered_through=d(22))
    stats = env.run_row(quiet.run_id).stats
    assert stats["unexplained_difference"] == {"before": -50, "after": -50}
    assert "balance" not in stats and len(stats["since_zero"]) == 1
    # a later record that agrees with the books (850 - 10 - 5 = 835) leaves the difference as it was
    fixed = env.deliver(
        [row(-5, d(23), source_id="d")],
        covered_through=d(25),
        reported_balance=835,
        reported_balance_on=d(25),
    )
    # (835 - 850) - (-10 - 5) = 0
    assert env.run_row(fixed.run_id).stats["unexplained_difference"] == {"before": -50, "after": -50}
    _checks_clean(env)


def test_a_duplicate_marked_row_does_not_count_in_the_interval(env: Env) -> None:
    env.deliver([row(-500, d(10), source_id="a")], reported_balance=1000, reported_balance_on=d(12))
    res = env.deliver(  # same day and amount, other identity: paired as a duplicate, no entry
        [row(-500, d(10), source_id="b")],
        covered_through=d(14),
        reported_balance=1000,
        reported_balance_on=d(14),
    )
    assert res.duplicates and res.inserted == 0
    assert [t for t, _, _ in _derived(env)] == ["opening"]
    assert res.unexplained_difference_after is None
    _checks_clean(env)


def _fails(env: Env, rule: str, **kw: object) -> str:
    run_id = start_run(env.engine, env.account, "transactions", importer="csv")
    with pytest.raises(ContractViolation) as exc:
        ingest_delivery(env.engine, run_id, [row(-5, source_id="a")], **kw)  # type: ignore[arg-type]
    assert exc.value.rule == rule
    _nothing_left(env, run_id)
    _checks_clean(env)
    return str(exc.value)


def test_balance_without_date_fails_the_run(env: Env) -> None:
    msg = _fails(env, "balance_without_date", reported_balance=5, covered_through=d(14))
    assert "reported_balance_on" in msg


def test_date_without_balance_fails_the_run(env: Env) -> None:
    msg = _fails(env, "balance_without_date", reported_balance_on=d(14), covered_through=d(14))
    assert "reported_balance" in msg


def test_balance_after_coverage_fails_the_run(env: Env) -> None:
    _fails(
        env, "balance_after_coverage", reported_balance=5, reported_balance_on=d(15), covered_through=d(14)
    )
