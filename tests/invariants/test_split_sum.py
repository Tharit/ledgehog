"""Split allocation (I3, I7): trg_split_sum, trg_source_entries and check_source_entries.

Both are DEFERRED, so most cases run on `db_conn` and call `fire_deferred` where the commit
would be. The last section commits for real on a throwaway database.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

from tests.invariants.helpers import (
    RAISE_EXCEPTION,
    fire_deferred,
    make_balance_record,
    make_derived_entry,
    make_entry,
    make_movement,
    make_source,
    rejects,
    scalar,
)

MakeAccount = Callable[..., int]
MISMATCH = "split allocation mismatch"


def _committed_split(conn: Connection, acct: int) -> tuple[int, int, int]:
    """A source of -3000 with entries -1000 and -2000, already past its deferred check."""
    src = make_source(conn, acct, amount=-3000)
    e1 = make_entry(conn, src, amount=-1000)
    e2 = make_entry(conn, src, amount=-2000)
    fire_deferred(conn)
    return src, e1, e2


# ---- accepts


def test_single_entry_equal_to_the_source_is_accepted(db_conn: Connection, make_account: MakeAccount) -> None:
    make_movement(db_conn, make_account(db_conn))
    fire_deferred(db_conn)


def test_a_split_summing_to_the_source_is_accepted(db_conn: Connection, make_account: MakeAccount) -> None:
    _committed_split(db_conn, make_account(db_conn))


def test_a_split_may_mix_signs_as_long_as_it_sums(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    src = make_source(db_conn, acct, amount=-3000)
    make_entry(db_conn, src, amount=-4000)
    make_entry(db_conn, src, amount=1000)
    fire_deferred(db_conn)


def test_a_balanced_rewrite_in_one_statement_is_accepted(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    """Deferred: the sum is only checked after the whole statement."""
    _, e1, e2 = _committed_split(db_conn, make_account(db_conn))
    db_conn.execute(
        text(
            "UPDATE ledger_entry SET amount = CASE id WHEN :a THEN -2500 ELSE -500 END WHERE id IN (:a, :b)"
        ),
        {"a": e1, "b": e2},
    )
    fire_deferred(db_conn)


def test_derived_entries_have_no_source_and_are_skipped(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    rec = make_balance_record(db_conn, acct, balance_on=date(2026, 1, 1), balance=5000)
    make_derived_entry(db_conn, acct, rec, type="opening", booked_on=date(2026, 1, 1))
    fire_deferred(db_conn)


# ---- INSERT path


def test_source_without_an_entry_is_refused_at_commit(db_conn: Connection, make_account: MakeAccount) -> None:
    """I7: caught by trg_duplicate_state on the new row (trg_split_sum only watches entries)."""
    make_source(db_conn, make_account(db_conn))
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="not a duplicate but its entries sum to 0"):
        fire_deferred(db_conn)


def test_entry_that_does_not_sum_is_refused(db_conn: Connection, make_account: MakeAccount) -> None:
    src = make_source(db_conn, make_account(db_conn), amount=-1000)
    make_entry(db_conn, src, amount=-900)
    # a NEW source is checked by trg_duplicate_state first (alphabetical order of the deferred triggers)
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="entries sum to -900, not -1000"):
        fire_deferred(db_conn)


def test_second_entry_overshooting_the_source_is_refused(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    src, _, _ = _committed_split(db_conn, make_account(db_conn))
    make_entry(db_conn, src, amount=-1)
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message=MISMATCH):
        fire_deferred(db_conn)


def test_entry_on_a_duplicate_is_refused(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    original, _ = make_movement(db_conn, acct)
    dup = make_source(db_conn, acct, duplicate_of=original)
    make_entry(db_conn, dup)
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="still has 1 entries"):
        fire_deferred(db_conn)


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"booked_on": date(2026, 2, 11)}, "must carry its account, currency and dates"),
        ({"value_on": date(2026, 2, 11)}, "must carry its account, currency and dates"),
    ],
)
def test_entry_must_carry_the_sources_dates(
    override: dict[str, date], message: str, db_conn: Connection, make_account: MakeAccount
) -> None:
    src = make_source(db_conn, make_account(db_conn), amount=-1000)
    make_entry(db_conn, src, **override)
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message=message):
        fire_deferred(db_conn)


def test_entry_must_carry_the_sources_account(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn, name="A")
    other = make_account(db_conn, name="B")
    src = make_source(db_conn, acct, amount=-1000)
    make_entry(db_conn, src, account_id=other)
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="must carry its account, currency and dates"):
        fire_deferred(db_conn)


# ---- UPDATE path (only on the watched columns)


@pytest.mark.parametrize(
    ("assignment", "message"),
    [
        ("amount = amount - 1", MISMATCH),
        ("booked_on = booked_on + 1", "must carry its account, currency and dates"),
        ("value_on = DATE '2026-02-12'", "must carry its account, currency and dates"),
    ],
)
def test_updating_a_watched_entry_column_is_rechecked(
    assignment: str, message: str, db_conn: Connection, make_account: MakeAccount
) -> None:
    _, e1, _ = _committed_split(db_conn, make_account(db_conn))
    db_conn.execute(text(f"UPDATE ledger_entry SET {assignment} WHERE id = :i"), {"i": e1})  # noqa: S608
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message=message):
        fire_deferred(db_conn)


def test_updating_an_unwatched_column_queues_nothing(db_conn: Connection, make_account: MakeAccount) -> None:
    """Settling's rewrite of flags, derivation and notes must not re-run the split check."""
    acct = make_account(db_conn)
    src, e1, _ = _committed_split(db_conn, acct)
    # corrupt the split with the triggers off, then go back to normal
    db_conn.execute(text("SET LOCAL session_replication_role = replica"))
    db_conn.execute(text("UPDATE ledger_entry SET amount = amount - 1 WHERE id = :i"), {"i": e1})
    db_conn.execute(text("SET LOCAL session_replication_role = origin"))

    db_conn.execute(
        text(
            "UPDATE ledger_entry SET review_flags = ARRAY['unconfirmed'], note = 'n', description = 'd', "
            "derivation = '{\"type\": {}}' WHERE id = :i"
        ),
        {"i": e1},
    )
    fire_deferred(db_conn)  # no event queued: the corruption is not noticed

    db_conn.execute(text("UPDATE ledger_entry SET amount = amount WHERE id = :i"), {"i": e1})
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message=MISMATCH):
        fire_deferred(db_conn)  # touching a watched column (even to the same value) queues the check
    assert src


def test_editing_a_user_source_amount_requires_matching_entries(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    src = make_source(db_conn, acct, importer=None, amount=-1000)
    entry = make_entry(db_conn, src)
    fire_deferred(db_conn)
    db_conn.execute(text("UPDATE source_transaction SET amount = -1500 WHERE id = :i"), {"i": src})
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message=MISMATCH):
        fire_deferred(db_conn)
    db_conn.execute(text("UPDATE ledger_entry SET amount = -1500 WHERE id = :i"), {"i": entry})
    fire_deferred(db_conn)


def test_editing_a_user_source_date_requires_matching_entries(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    src = make_source(db_conn, acct, importer=None)
    entry = make_entry(db_conn, src)
    fire_deferred(db_conn)
    db_conn.execute(
        text("UPDATE source_transaction SET booked_on = DATE '2026-02-20' WHERE id = :i"), {"i": src}
    )
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message="must carry its account, currency and dates"):
        fire_deferred(db_conn)
    db_conn.execute(text("UPDATE ledger_entry SET booked_on = DATE '2026-02-20' WHERE id = :i"), {"i": entry})
    fire_deferred(db_conn)


# ---- DELETE path: assert_split_sum reads OLD when NEW is null


def test_deleting_one_entry_of_a_split_is_refused(db_conn: Connection, make_account: MakeAccount) -> None:
    _, e1, _ = _committed_split(db_conn, make_account(db_conn))
    db_conn.execute(text("DELETE FROM ledger_entry WHERE id = :i"), {"i": e1})
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message=MISMATCH):
        fire_deferred(db_conn)


def test_deleting_the_only_entry_is_refused(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    src, entry = make_movement(db_conn, acct)
    fire_deferred(db_conn)
    db_conn.execute(text("DELETE FROM ledger_entry WHERE id = :i"), {"i": entry})
    with rejects(db_conn, sqlstate=RAISE_EXCEPTION, message=MISMATCH):
        fire_deferred(db_conn)
    assert src


def test_deleting_an_entry_and_replacing_it_in_the_same_transaction_is_accepted(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    src, entry = make_movement(db_conn, acct)
    fire_deferred(db_conn)
    db_conn.execute(text("DELETE FROM ledger_entry WHERE id = :i"), {"i": entry})
    make_entry(db_conn, src)
    fire_deferred(db_conn)


def test_deleting_the_entries_and_the_source_together_is_accepted(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    """The revert path: the source is gone when the deferred check runs, which is not an error."""
    acct = make_account(db_conn)
    src, entry = make_movement(db_conn, acct)
    fire_deferred(db_conn)
    db_conn.execute(text("DELETE FROM ledger_entry WHERE id = :i"), {"i": entry})
    db_conn.execute(text("DELETE FROM source_transaction WHERE id = :i"), {"i": src})
    fire_deferred(db_conn)
    assert scalar(db_conn, "SELECT count(*) FROM source_transaction WHERE id = :i", i=src) == 0


def test_check_source_entries_ignores_a_missing_source(db_conn: Connection) -> None:
    db_conn.execute(text("SELECT check_source_entries(-1)"))


# ---- real commits: the deferred triggers fire at COMMIT


def test_commit_of_source_and_entry_together_succeeds(
    isolated_engine: Engine, make_account: MakeAccount
) -> None:
    with isolated_engine.begin() as conn:
        acct = make_account(conn)
        make_movement(conn, acct)
    with isolated_engine.connect() as conn:
        assert scalar(conn, "SELECT count(*) FROM ledger_entry") == 1


def test_commit_of_a_source_without_entry_fails_and_leaves_nothing(
    isolated_engine: Engine, make_account: MakeAccount
) -> None:
    with isolated_engine.begin() as conn:
        acct = make_account(conn)
    with pytest.raises(DBAPIError, match="not a duplicate but its entries sum"):
        with isolated_engine.begin() as conn:
            make_source(conn, acct)
    with isolated_engine.connect() as conn:
        assert scalar(conn, "SELECT count(*) FROM source_transaction") == 0


def test_commit_of_a_mismatching_split_fails(isolated_engine: Engine, make_account: MakeAccount) -> None:
    with isolated_engine.begin() as conn:
        acct = make_account(conn)
    with pytest.raises(DBAPIError, match="entries sum to -400, not -1000"):
        with isolated_engine.begin() as conn:
            src = make_source(conn, acct, amount=-1000)
            make_entry(conn, src, amount=-400)
    with isolated_engine.connect() as conn:
        assert scalar(conn, "SELECT count(*) FROM ledger_entry") == 0


def test_commit_of_an_entry_delete_fails_but_a_split_rewrite_succeeds(
    isolated_engine: Engine, make_account: MakeAccount
) -> None:
    with isolated_engine.begin() as conn:
        acct = make_account(conn)
        src = make_source(conn, acct, amount=-3000)
        e1 = make_entry(conn, src, amount=-1000)
        e2 = make_entry(conn, src, amount=-2000)
    with pytest.raises(DBAPIError, match=MISMATCH):
        with isolated_engine.begin() as conn:
            conn.execute(text("DELETE FROM ledger_entry WHERE id = :i"), {"i": e1})
    with isolated_engine.begin() as conn:  # move 500 from one part to the other: sum unchanged
        conn.execute(text("UPDATE ledger_entry SET amount = -500 WHERE id = :i"), {"i": e1})
        conn.execute(text("UPDATE ledger_entry SET amount = -2500 WHERE id = :i"), {"i": e2})
    with isolated_engine.connect() as conn:
        assert scalar(conn, "SELECT sum(amount) FROM ledger_entry") == -3000
