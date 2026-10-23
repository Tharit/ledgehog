"""Migration 0013: one document, several charges (spec I35 §5.5 §5.9): a document may be carried by several
transactions (`ux_le_document` is gone), a transaction still has one carrier and a line one entry, and a line
holds the model's answer (`category_id`, SET NULL, and `category_key`)."""

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
from tests.invariants.helpers import make_category, make_entry, make_source

MakeAccount = Any


def _line(conn: Connection, doc: int, **extra: Any) -> int:
    return int(
        conn.execute(
            text(
                "INSERT INTO external_document_line (document_id, line_no, description, amount, category_id,"
                " category_key) VALUES (:d, 1, 'x', -1, :c, CAST(:k AS jsonb)) RETURNING id"
            ),
            {"d": doc, "c": extra.get("category_id"), "k": extra.get("category_key")},
        ).scalar_one()
    )


def test_a_document_may_be_carried_by_several_transactions(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    doc = make_document(db_conn, total=-1000)
    first = make_entry(db_conn, make_source(db_conn, acct), document_id=doc)
    second = make_entry(db_conn, make_source(db_conn, acct), document_id=doc)
    assert first != second


def test_a_transaction_still_has_one_carrier_and_a_line_one_entry(
    db_conn: Connection, make_account: MakeAccount
) -> None:
    acct = make_account(db_conn)
    doc, other = make_document(db_conn, total=-1000), make_document(db_conn, total=-2000)
    src = make_source(db_conn, acct, amount=-3000)
    make_entry(db_conn, src, amount=-1000, document_id=doc)
    with pytest.raises(IntegrityError, match="ux_le_document_per_transaction"), db_conn.begin_nested():
        make_entry(db_conn, src, amount=-2000, document_id=other)
    own = _line(db_conn, doc)
    make_entry(db_conn, make_source(db_conn, acct), document_id=doc, document_line_id=own)
    with pytest.raises(IntegrityError, match="ux_le_document_line"), db_conn.begin_nested():
        make_entry(db_conn, make_source(db_conn, acct), document_id=doc, document_line_id=own)


def test_a_line_holds_the_models_answer_and_loses_the_category_with_it(db_conn: Connection) -> None:
    doc = make_document(db_conn, total=-1000)
    category = make_category(db_conn, "Groceries")
    line = _line(db_conn, doc, category_id=category, category_key='{"pass": "llm"}')
    assert db_conn.execute(
        text("SELECT category_id, category_key FROM external_document_line WHERE id = :i"), {"i": line}
    ).one() == (category, {"pass": "llm"})
    db_conn.execute(text("DELETE FROM category WHERE id = :c"), {"c": category})
    row = db_conn.execute(
        text("SELECT category_id, category_key FROM external_document_line WHERE id = :i"), {"i": line}
    ).one()
    assert row.category_id is None and row.category_key == {"pass": "llm"}  # the key stays: no answer


def test_a_line_without_an_answer_has_none(db_conn: Connection) -> None:
    line = _line(db_conn, make_document(db_conn, total=-1000))
    row = db_conn.execute(
        text("SELECT category_id, category_key FROM external_document_line WHERE id = :i"), {"i": line}
    ).one()
    assert (row.category_id, row.category_key) == (None, None)


def test_down_and_up_again_is_clean(isolated_db: Config) -> None:
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

    def columns() -> set[str]:
        engine = make_engine(isolated_db, pool_size=1, max_overflow=0)
        try:
            with engine.connect() as conn:
                return set(
                    conn.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns"
                            " WHERE table_name = 'external_document_line'"
                        )
                    ).scalars()
                )
        finally:
            engine.dispose()

    step("0012")
    assert not {"category_id", "category_key"} & columns()
    step(None)
    assert {"category_id", "category_key"} <= columns()
