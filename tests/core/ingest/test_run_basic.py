"""Run lifecycle, insertion, refusals (spec §5.1-§5.2)."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.domain.errors import ContractViolation
from app.core.ingest.run import fail_run, ingest_delivery, start_run
from app.core.plugins.importer import IncomingRow
from tests.core.ingest.conftest import THROUGH, Env, row


def test_start_run_commits_running_row_first(env: Env) -> None:
    run_id = start_run(env.engine, env.account, "transactions", importer="csv")
    r = env.run_row(run_id)
    assert (r.status, r.finished_at, r.emits, r.account_id) == ("running", None, "transactions", env.account)


def test_fail_run_sets_failed_and_finished(env: Env) -> None:
    run_id = start_run(env.engine, env.account, "transactions", importer="csv")
    fail_run(env.engine, run_id, "boom")
    r = env.run_row(run_id)
    assert (r.status, r.error_text) == ("failed", "boom")
    assert r.finished_at is not None and r.covered_through is None


def test_insert_creates_source_and_exactly_one_entry(env: Env) -> None:
    res = env.deliver(
        [row(-500, purpose="coffee", source_id="a"), row(1200, purpose="refund", source_id="b")]
    )
    assert res.inserted == 2 and res.duplicates == () and res.skipped_by_identity == 0
    entries = env.q(
        "SELECT e.amount, e.currency, e.booked_on, e.type, e.category_id, e.derivation, e.review_flags,"
        " e.account_id, s.account_id AS sa FROM ledger_entry e JOIN source_transaction s"
        " ON s.id = e.source_transaction_id ORDER BY e.id"
    )
    assert [e.amount for e in entries] == [-500, 1200]
    for e in entries:
        assert e.type is None and e.category_id is None and e.derivation == {}
        assert e.account_id == e.sa and e.currency == "EUR"
    r = env.run_row(res.run_id)
    assert r.status == "ok" and r.finished_at is not None and r.covered_through == THROUGH
    assert r.stats["inserted"] == 2


def test_content_hash_stored_when_no_source_id(env: Env) -> None:
    env.deliver([row(purpose="x"), row(-1, source_id="s1")])
    rows = env.q("SELECT source_id, content_hash FROM source_transaction ORDER BY id")
    assert rows[0].source_id is None and len(rows[0].content_hash) == 64
    assert rows[1].source_id == "s1" and rows[1].content_hash is None


def _violates(env: Env, rows: list[IncomingRow], rule: str, *, covered_through: date | None = THROUGH) -> str:
    """Deliver `rows`: the run fails naming `rule`, and nothing is written."""
    run_id = start_run(env.engine, env.account, "transactions", importer="csv")
    with pytest.raises(ContractViolation) as caught:
        ingest_delivery(env.engine, run_id, rows, covered_through=covered_through)
    assert caught.value.rule == rule
    r = env.run_row(run_id)
    assert r.status == "failed" and r.covered_through is None and r.finished_at is not None
    assert rule in r.error_text
    for table in ("source_transaction", "ledger_entry"):
        assert env.count(table) == 0
    return str(caught.value)


def test_currency_mismatch_fails_the_run(env: Env) -> None:
    msg = _violates(
        env, [row(-5, source_id="ok"), row(-500, currency="USD", source_id="u")], "currency_mismatch"
    )
    assert "row 1" in msg and "USD" in msg and "EUR" in msg


def test_zero_amount_fails_the_run(env: Env) -> None:
    msg = _violates(env, [row(-5, source_id="y"), row(0, source_id="z")], "zero_amount")
    assert "row 1" in msg


def test_repeated_source_id_fails_the_run(env: Env) -> None:
    msg = _violates(env, [row(-1, source_id="a"), row(-2, source_id="a")], "repeated_source_id")
    assert "row 1" in msg and "row 0" in msg  # the repeat and its first occurrence; the value is not echoed
    assert "'a'" not in msg and '"a"' not in msg


def test_no_coverage_fails_the_run(env: Env) -> None:
    _violates(env, [row(source_id="a")], "no_coverage", covered_through=None)


def test_a_violating_row_at_the_end_leaves_nothing(env: Env) -> None:
    rows = [row(-i, source_id=f"s{i}") for i in range(1, 30)] + [row(0, source_id="last")]
    _violates(env, rows, "zero_amount")


def test_violation_row_index_counts_the_whole_delivery(env: Env) -> None:
    msg = _violates(env, [row(-1, source_id="a"), row(-2), row(-3, currency="GBP")], "currency_mismatch")
    assert "row 2" in msg


def test_importer_stats_are_stored_and_returned(env: Env) -> None:
    res = env.deliver([row(-5, source_id="y")], importer_stats={"filtered": 3, "synthetic_skipped": 0})
    assert dict(res.importer_stats) == {"filtered": 3, "synthetic_skipped": 0}
    stats = env.run_row(res.run_id).stats
    assert stats["importer"] == {"filtered": 3, "synthetic_skipped": 0}
    assert "filtered" not in stats and "refused_currency" not in stats and "zero_amount" not in stats


def test_importer_stats_default_to_empty(env: Env) -> None:
    res = env.deliver([row(-5, source_id="y")])
    assert dict(res.importer_stats) == {} and env.run_row(res.run_id).stats["importer"] == {}


def test_importer_stats_result_is_a_copy_and_frozen(env: Env) -> None:
    given = {"filtered": 1}
    res = env.deliver([row(-5, source_id="y")], importer_stats=given)
    given["filtered"] = 99
    assert res.importer_stats["filtered"] == 1
    with pytest.raises(TypeError):
        res.importer_stats["filtered"] = 2  # type: ignore[index]


@pytest.mark.parametrize("bad", [{"filtered": -1}, {"filtered": 1.5}, {"filtered": "3"}, {"filtered": True}])
def test_invalid_importer_stats_are_rejected(env: Env, bad: dict[str, object]) -> None:
    run_id = start_run(env.engine, env.account, "transactions", importer="csv")
    with pytest.raises(ValueError, match="importer_stats"):
        ingest_delivery(
            env.engine,
            run_id,
            [row(source_id="a")],
            covered_through=THROUGH,
            importer_stats=bad,  # type: ignore[arg-type]
        )
    assert env.run_row(run_id).status == "failed" and env.count("source_transaction") == 0


def test_missing_covered_through_fails_the_run(env: Env) -> None:
    run_id = start_run(env.engine, env.account, "transactions", importer="csv")
    with pytest.raises(Exception, match="covered_through"):
        ingest_delivery(env.engine, run_id, [row(source_id="a")])
    assert env.run_row(run_id).status == "failed" and env.count("source_transaction") == 0


def test_run_not_running_is_refused(env: Env) -> None:
    res = env.deliver([row(source_id="a")])
    with pytest.raises(Exception, match="not running"):
        ingest_delivery(env.engine, res.run_id, [row(source_id="b")], covered_through=THROUGH)
    assert env.run_row(res.run_id).status == "ok"
    assert env.count("source_transaction") == 1
