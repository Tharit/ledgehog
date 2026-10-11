"""The integrity reader: every v_check_* view, read as rows (architecture §4.1, schema §9)."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import Connection, text

from app.core.integrity import check_integrity
from tests.invariants.helpers import make_source, seed_clean, triggers_disabled


def _views(conn: Connection) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            text(
                "SELECT viewname FROM pg_views WHERE schemaname = 'public' AND viewname LIKE 'v\\_check\\_%'"
            )
        )
    }


def test_every_check_view_is_reported_and_a_clean_ledger_is_ok(
    db_conn: Connection, make_account: Callable[..., int]
) -> None:
    seed_clean(db_conn, make_account)
    report = check_integrity(db_conn)
    assert report.ok is True
    assert set(report.checks) == _views(db_conn) and len(report.checks) >= 10
    assert all(c.rows == [] and not c.truncated for c in report.checks.values())


def _unbalanced_sources(conn: Connection, account: int, n: int) -> None:
    with triggers_disabled(conn, "source_transaction", "ledger_entry"):
        for _ in range(n):
            make_source(conn, account, amount=-100)  # a source with no entries: split sum broken


def test_a_violation_is_reported_as_json_ready_rows_under_its_view(
    db_conn: Connection, make_account: Callable[..., int]
) -> None:
    account = make_account(db_conn, name="A")
    _unbalanced_sources(db_conn, account, 1)
    report = check_integrity(db_conn)
    assert report.ok is False
    check = report.checks["v_check_split_sum"]
    assert len(check.rows) == 1 and not check.truncated
    assert check.rows[0]["source_amount"] == -100 and check.rows[0]["entries_sum"] == 0
    assert all(c.rows == [] for name, c in report.checks.items() if name != "v_check_split_sum")


def test_rows_are_capped_per_view_with_a_truncated_flag(
    db_conn: Connection, make_account: Callable[..., int]
) -> None:
    account = make_account(db_conn, name="A")
    _unbalanced_sources(db_conn, account, 5)
    check = check_integrity(db_conn, limit=3).checks["v_check_split_sum"]
    assert len(check.rows) == 3 and check.truncated is True
    exact = check_integrity(db_conn, limit=5).checks["v_check_split_sum"]
    assert len(exact.rows) == 5 and exact.truncated is False
