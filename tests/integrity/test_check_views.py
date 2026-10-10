"""Integrity views (schema.sql §9): empty on clean data, non-empty on a seeded violation.

The violations are written inside the test transaction with triggers bypassed
(`SET LOCAL session_replication_role = replica`), which also switches off the
foreign-key triggers; CHECK constraints and unique indexes stay on, so a seeded
violation is one the schema's DDL alone would allow.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import Connection, text

from tests.invariants.helpers import Clean, make_source, seed_clean

CHECK_VIEWS = [
    "v_check_split_sum",
    "v_check_duplicate_with_entries",
    "v_check_duplicate_chain",
    "v_check_transfer_asymmetry",
    "v_check_opening_not_first",
    "v_check_reported_after_coverage",
    "v_check_derived_type",
    "v_check_derived_on_uncounted",
    "v_check_opening_not_anchor",
    "v_check_anchor_not_opening",
]


def _count(conn: Connection, view: str) -> int:
    return int(conn.execute(text(f"SELECT count(*) FROM {view}")).scalar_one())  # noqa: S608


def _replica(conn: Connection) -> None:
    conn.execute(text("SET LOCAL session_replication_role = replica"))


def _sql(conn: Connection, sql: str, **params: object) -> None:
    conn.execute(text(sql), params)


def _split_sum(conn: Connection, c: Clean) -> None:
    _sql(conn, "UPDATE source_transaction SET amount = amount - 1 WHERE id = :i", i=c.m1)


def _duplicate_with_entries(conn: Connection, c: Clean) -> None:
    _sql(conn, "UPDATE source_transaction SET duplicate_of = :o WHERE id = :i", o=c.m1, i=c.spare)


def _duplicate_chain(conn: Connection, c: Clean) -> None:
    make_source(conn, c.checking, duplicate_of=c.dup, amount=-1000)


def _transfer_asymmetry(conn: Connection, c: Clean) -> None:
    _sql(conn, "UPDATE ledger_entry SET counterpart_entry_id = NULL WHERE id = :i", i=c.transfer_b)


def _opening_not_first(conn: Connection, c: Clean) -> None:
    _sql(conn, "UPDATE ledger_entry SET booked_on = DATE '2026-04-01' WHERE id = :i", i=c.opening)


def _reported_after_coverage(conn: Connection, c: Clean) -> None:
    _sql(conn, "UPDATE balance_record SET balance_on = DATE '2026-03-05' WHERE id = :i", i=c.reported_record)


def _derived_type(conn: Connection, c: Clean) -> None:
    _sql(conn, "UPDATE ledger_entry SET type = 'valuation' WHERE id = :i", i=c.reconciliation)


def _derived_on_uncounted(conn: Connection, c: Clean) -> None:
    _sql(conn, "UPDATE import_run SET status = 'reverted', reverted_at = now() WHERE id = :i", i=c.run)


def _opening_not_anchor(conn: Connection, c: Clean) -> None:
    _sql(
        conn,
        "UPDATE balance_record SET balance_on = DATE '2025-12-01' WHERE id = :i",
        i=c.reported_record,
    )


def _anchor_not_opening(conn: Connection, c: Clean) -> None:
    _sql(conn, "UPDATE ledger_entry SET type = 'reconciliation' WHERE id = :i", i=c.opening)


VIOLATIONS: dict[str, Callable[[Connection, Clean], None]] = {
    "v_check_split_sum": _split_sum,
    "v_check_duplicate_with_entries": _duplicate_with_entries,
    "v_check_duplicate_chain": _duplicate_chain,
    "v_check_transfer_asymmetry": _transfer_asymmetry,
    "v_check_opening_not_first": _opening_not_first,
    "v_check_reported_after_coverage": _reported_after_coverage,
    "v_check_derived_type": _derived_type,
    "v_check_derived_on_uncounted": _derived_on_uncounted,
    "v_check_opening_not_anchor": _opening_not_anchor,
    "v_check_anchor_not_opening": _anchor_not_opening,
}


def test_every_check_view_has_a_violation_case(db_conn: Connection) -> None:
    """The lists above cover every v_check_* view the schema defines (a new view needs a test)."""
    names = {
        r[0]
        for r in db_conn.execute(
            text(
                "SELECT viewname FROM pg_views WHERE schemaname = 'public' AND viewname LIKE 'v\\_check\\_%'"
            )
        )
    }
    assert names == set(CHECK_VIEWS) == set(VIOLATIONS)


def test_check_views_are_empty_on_an_empty_database(db_conn: Connection) -> None:
    for view in CHECK_VIEWS:
        assert _count(db_conn, view) == 0, view


def test_check_views_are_empty_on_clean_data(db_conn: Connection, make_account: Callable[..., int]) -> None:
    seed_clean(db_conn, make_account)
    for view in CHECK_VIEWS:
        assert _count(db_conn, view) == 0, view


@pytest.mark.parametrize("view", CHECK_VIEWS)
def test_check_view_reports_a_seeded_violation(
    view: str, db_conn: Connection, make_account: Callable[..., int]
) -> None:
    clean = seed_clean(db_conn, make_account)
    assert _count(db_conn, view) == 0

    _replica(db_conn)
    VIOLATIONS[view](db_conn, clean)

    assert _count(db_conn, view) >= 1


def test_seeded_violation_is_invisible_to_the_other_views_it_does_not_concern(
    db_conn: Connection, make_account: Callable[..., int]
) -> None:
    """A split-sum violation shows in v_check_split_sum only: the views are not redundant copies."""
    clean = seed_clean(db_conn, make_account)
    _replica(db_conn)
    _split_sum(db_conn, clean)
    flagged = [v for v in CHECK_VIEWS if _count(db_conn, v) > 0]
    assert flagged == ["v_check_split_sum"]


def test_split_sum_view_names_the_source_and_both_sums(
    db_conn: Connection, make_account: Callable[..., int]
) -> None:
    clean = seed_clean(db_conn, make_account)
    _replica(db_conn)
    _split_sum(db_conn, clean)
    row = db_conn.execute(text("SELECT * FROM v_check_split_sum")).one()
    assert (row.source_transaction_id, row.source_amount, row.entries_sum) == (clean.m1, -1001, -1000)


def test_violations_need_the_bypass(db_conn: Connection, make_account: Callable[..., int]) -> None:
    """Without session_replication_role the immutability trigger refuses the very write the test seeds."""
    from tests.invariants.helpers import RAISE_EXCEPTION, rejects

    clean = seed_clean(db_conn, make_account)
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="is immutable"):
        _split_sum(db_conn, clean)
