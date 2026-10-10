"""Run lifecycle, insertion, refusals (spec §5.1-§5.2)."""

from __future__ import annotations

import pytest

from app.core.ingest.run import fail_run, ingest_delivery, start_run
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


def test_currency_mismatch_refused_counted_run_still_ok(env: Env) -> None:
    res = env.deliver([row(-500, currency="USD", source_id="u")])
    assert (res.refused_currency, res.inserted) == (1, 0)
    assert env.count("source_transaction") == 0
    r = env.run_row(res.run_id)
    assert r.status == "ok" and r.stats["refused_currency"] == 1


def test_zero_amount_counted_and_skipped(env: Env) -> None:
    res = env.deliver([row(0, source_id="z"), row(-5, source_id="y")])
    assert (res.zero_amount, res.inserted) == (1, 1)
    assert env.count("source_transaction") == 1


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
