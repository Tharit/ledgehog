"""ck_review_flags_known: review_flags is a subset of the closed token set (I23)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import Connection, text

from tests.invariants.helpers import (
    CHECK_VIOLATION,
    NOT_NULL_VIOLATION,
    make_movement,
    rejects,
    scalar,
)

MakeAccount = Callable[..., int]
KNOWN = ["unconfirmed", "unclassified", "waiting", "unmatched_transfer"]


@pytest.fixture
def entry(db_conn: Connection, make_account: MakeAccount) -> int:
    return make_movement(db_conn, make_account(db_conn))[1]


def _set(conn: Connection, entry: int, array_sql: str) -> None:
    conn.execute(text(f"UPDATE ledger_entry SET review_flags = {array_sql} WHERE id = :i"), {"i": entry})  # noqa: S608


@pytest.mark.parametrize("token", KNOWN)
def test_each_known_token_is_accepted(db_conn: Connection, entry: int, token: str) -> None:
    _set(db_conn, entry, f"ARRAY['{token}']::text[]")
    assert scalar(db_conn, "SELECT review_flags FROM ledger_entry WHERE id = :i", i=entry) == [token]


def test_all_known_tokens_together_and_empty_are_accepted(db_conn: Connection, entry: int) -> None:
    _set(db_conn, entry, "ARRAY['" + "','".join(KNOWN) + "']::text[]")
    _set(db_conn, entry, "'{}'::text[]")


def test_the_default_is_empty(db_conn: Connection, entry: int) -> None:
    assert scalar(db_conn, "SELECT review_flags FROM ledger_entry WHERE id = :i", i=entry) == []


@pytest.mark.parametrize(
    "array_sql",
    [
        "ARRAY['bogus']::text[]",
        "ARRAY['unconfirmed','bogus']::text[]",
        "ARRAY['Unconfirmed']::text[]",  # case-sensitive
        "ARRAY['unconfirmed',NULL]::text[]",
        "ARRAY['']::text[]",
    ],
)
def test_unknown_tokens_are_rejected_on_update(db_conn: Connection, entry: int, array_sql: str) -> None:
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ck_review_flags_known"):
        _set(db_conn, entry, array_sql)


def test_unknown_tokens_are_rejected_on_insert(db_conn: Connection, make_account: MakeAccount) -> None:
    from tests.invariants.helpers import make_entry, make_source

    acct = make_account(db_conn)
    src = make_source(db_conn, acct)
    with rejects(db_conn, sqlstate=CHECK_VIOLATION, constraint="ck_review_flags_known"):
        make_entry(db_conn, src, review_flags=["made_up"])


def test_a_repeated_known_token_is_accepted(db_conn: Connection, entry: int) -> None:
    """The set is closed, but the array is not de-duplicated by the schema: writers must not repeat."""
    _set(db_conn, entry, "ARRAY['waiting','waiting']::text[]")


def test_null_flags_are_rejected(db_conn: Connection, entry: int) -> None:
    with rejects(db_conn, sqlstate=NOT_NULL_VIOLATION):
        _set(db_conn, entry, "NULL")
