"""Migration 0007: an entry's line of its transaction's document (spec §5.8, D225): the column, its foreign
key (SET NULL), the unique index, the transfer constraint, and the version bump on a change of the line."""

from __future__ import annotations

from typing import Any

import pytest
from alembic import command
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from app.utils.config import Config
from app.utils.db import migrate
from app.utils.db.engine import make_engine
from tests.core.units.doc_helpers import make_document
from tests.invariants.helpers import make_entry, make_source

MakeAccount = Any


def line(conn: Connection, doc: int, no: int = 1) -> int:
    return int(
        conn.execute(
            text(
                "INSERT INTO external_document_line (document_id, line_no, description, amount)"
                " VALUES (:d, :n, 'x', -1) RETURNING id"
            ),
            {"d": doc, "n": no},
        ).scalar_one()
    )


def entry_row(conn: Connection, entry: int) -> Any:
    return conn.execute(
        text("SELECT document_id, document_line_id, version FROM ledger_entry WHERE id = :i"), {"i": entry}
    ).one()


def test_the_column_is_nullable_and_new_entries_have_no_line(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    e = make_entry(db_conn, make_source(db_conn, make_account(db_conn)))
    assert entry_row(db_conn, e).document_line_id is None


def test_a_line_is_the_line_of_at_most_one_entry(db_conn: Connection, make_account: MakeAccount) -> None:
    acct = make_account(db_conn)
    doc = make_document(db_conn, total=-1000)
    own = line(db_conn, doc)
    make_entry(db_conn, make_source(db_conn, acct), document_id=doc, document_line_id=own)
    with pytest.raises(IntegrityError, match="ux_le_document_line"), db_conn.begin_nested():
        make_entry(db_conn, make_source(db_conn, acct), document_line_id=own)


def test_a_line_must_exist(db_conn: Connection, make_account: MakeAccount) -> None:
    with pytest.raises(IntegrityError, match="fk_le_document_line"), db_conn.begin_nested():
        make_entry(db_conn, make_source(db_conn, make_account(db_conn)), document_line_id=987654321)


def test_a_document_is_not_on_a_transfer(db_conn: Connection, make_account: MakeAccount) -> None:
    acct, other = make_account(db_conn), make_account(db_conn, name="B")
    doc = make_document(db_conn, total=-1000)
    with pytest.raises(IntegrityError, match="ck_document_not_on_transfer"), db_conn.begin_nested():
        make_entry(
            db_conn,
            make_source(db_conn, acct),
            type="transfer",
            counter_account_id=other,
            document_id=doc,
        )
    e = make_entry(db_conn, make_source(db_conn, acct), document_id=doc)
    with pytest.raises(IntegrityError, match="ck_document_not_on_transfer"), db_conn.begin_nested():
        db_conn.execute(
            text(
                "UPDATE ledger_entry SET type = 'transfer', category_id = NULL, counter_account_id = :c"
                " WHERE id = :i"
            ),
            {"c": other, "i": e},
        )
    # a transfer without a document and a flow with one are both fine
    make_entry(db_conn, make_source(db_conn, acct), type="transfer", counter_account_id=other)


def test_replacing_a_documents_lines_clears_the_references_and_bumps_the_entrys_version(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    doc = make_document(db_conn, total=-1000)
    own = line(db_conn, doc)
    e = make_entry(db_conn, make_source(db_conn, acct), document_id=doc, document_line_id=own)
    before = entry_row(db_conn, e)
    # ingest replaces the lines as a delete and an insert (core/ingest/documents.py)
    db_conn.execute(text("DELETE FROM external_document_line WHERE document_id = :d"), {"d": doc})
    line(db_conn, doc)
    after = entry_row(db_conn, e)
    assert (after.document_id, after.document_line_id) == (doc, None)  # the link stays, the line is cleared
    assert after.version == before.version + 1


def test_a_change_of_the_line_bumps_the_version_like_a_change_of_the_link_even_while_settling(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    doc = make_document(db_conn, total=-1000)
    first, second = line(db_conn, doc, 1), line(db_conn, doc, 2)
    e = make_entry(db_conn, make_source(db_conn, acct), document_id=doc)
    v0 = entry_row(db_conn, e).version
    db_conn.execute(text("UPDATE ledger_entry SET document_line_id = :l WHERE id = :i"), {"l": first, "i": e})
    assert entry_row(db_conn, e).version == v0 + 1
    db_conn.execute(text("UPDATE ledger_entry SET note = 'n' WHERE id = :i"), {"i": e})  # not structural
    assert entry_row(db_conn, e).version == v0 + 2  # a note is user-meaningful outside settling
    db_conn.execute(text("SELECT set_config('ledger.settling', 'on', true)"))
    db_conn.execute(text("UPDATE ledger_entry SET note = 'm' WHERE id = :i"), {"i": e})
    assert entry_row(db_conn, e).version == v0 + 2  # settling's own writes do not bump
    db_conn.execute(
        text("UPDATE ledger_entry SET document_line_id = :l WHERE id = :i"), {"l": second, "i": e}
    )
    assert entry_row(db_conn, e).version == v0 + 3  # a structural column bumps whoever writes it
    db_conn.execute(
        text("UPDATE ledger_entry SET document_line_id = :l WHERE id = :i"), {"l": second, "i": e}
    )
    assert entry_row(db_conn, e).version == v0 + 3  # an unchanged value is not a change


def test_the_flows_view_carries_the_column(db_conn: Connection) -> None:
    columns = (
        db_conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'v_flows'"
                " ORDER BY ordinal_position"
            )
        )
        .scalars()
        .all()
    )
    assert "document_line_id" in columns and columns[-2:] == ["category_kind", "base_amount"]


def test_down_and_up_again_is_clean_and_adds_no_data(isolated_db: Config, make_account: MakeAccount) -> None:
    def step(down: str | None) -> None:
        engine = make_engine(isolated_db, pool_size=1, max_overflow=0)
        try:
            with engine.begin() as conn:
                alembic = migrate.alembic_config()
                alembic.attributes["connection"] = conn
                if down is not None:
                    command.downgrade(alembic, down)
                else:
                    command.upgrade(alembic, "head")
        finally:
            engine.dispose()

    step("0006")
    engine = make_engine(isolated_db, pool_size=1, max_overflow=0)
    with engine.begin() as conn:
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.columns WHERE column_name = 'document_line_id'"
                    " AND table_name = 'ledger_entry'"
                )
            ).scalar_one()
            == 0
        )
        e = make_entry(conn, make_source(conn, make_account(conn)))
    engine.dispose()
    step(None)
    engine = make_engine(isolated_db, pool_size=1, max_overflow=0)
    with engine.connect() as conn:
        assert entry_row(conn, e).document_line_id is None  # no backfill
    engine.dispose()
