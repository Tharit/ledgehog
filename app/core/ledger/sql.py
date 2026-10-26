"""The ledger filter as SQLAlchemy Core (architecture §5.2).

`compose(flt)` returns the FROM clause and the WHERE predicates of a `LedgerFilter`. Anything that
selects entries by filter (the list, its count, the tag-apply operation) builds its statement from
these two parts, so they can never disagree about what "matching" means.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import (
    ColumnElement,
    FromClause,
    Text,
    and_,
    column,
    exists,
    func,
    or_,
    select,
    table,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from app.core.ledger.filters import LedgerFilter

# The columns the filter and the row read; not a schema definition (schema.sql is that).
le = table(
    "ledger_entry",
    column("id"),
    column("version"),
    column("account_id"),
    column("source_transaction_id"),
    column("type"),
    column("amount"),
    column("currency"),
    column("booked_on"),
    column("value_on"),
    column("category_id"),
    column("payee_id"),
    column("counterpart_entry_id"),
    column("counter_account_id"),
    column("description"),
    column("note"),
    column("source_text"),
    column("review_flags", ARRAY(Text)),
    column("derivation", JSONB),
)
# the other leg of a transfer, for the partner summary of a row
partner = le.alias("partner")
st = table(
    "source_transaction",
    column("id"),
    column("importer"),
    column("origin"),
    column("source_id"),
    column("amount"),
    column("currency"),
    column("counterparty_name"),
    column("counterparty_ref"),
    column("counterparty_bic"),
    column("purpose"),
    column("booking_text"),
    column("end_to_end_id"),
    column("mandate_ref"),
    column("instructed_amount"),
    column("instructed_currency"),
    column("source_format"),
)
payee = table("payee", column("id"), column("name"))
category = table("category", column("id"), column("name"), column("parent_id"))
let = table("ledger_entry_tag", column("ledger_entry_id"), column("tag_id"))


@dataclass(frozen=True)
class Composed:
    source: FromClause  # ledger_entry joined to what the predicates read
    where: tuple[ColumnElement[bool], ...]  # AND-ed


def compose(flt: LedgerFilter) -> Composed:
    source: FromClause = le.outerjoin(st, st.c.id == le.c.source_transaction_id)
    where: list[ColumnElement[bool]] = []

    if flt.date_from is not None:
        where.append(le.c.booked_on >= flt.date_from)
    if flt.date_to is not None:
        where.append(le.c.booked_on <= flt.date_to)
    if flt.account_ids:
        where.append(le.c.account_id.in_(flt.account_ids))
    if flt.payee_ids:
        where.append(le.c.payee_id.in_(flt.payee_ids))
    if flt.category_ids or flt.uncategorised:
        where.append(_category(flt))
    if flt.tag_ids:
        where.append(exists(select(1).where(let.c.ledger_entry_id == le.c.id, let.c.tag_id.in_(flt.tag_ids))))
    if flt.currency is not None:
        where.append(le.c.currency == flt.currency)
    magnitude = func.abs(le.c.amount)
    if flt.amount_min is not None:
        where.append(magnitude >= flt.amount_min)
    if flt.amount_max is not None:
        where.append(magnitude <= flt.amount_max)
    if flt.direction == "in":
        where.append(le.c.amount > 0)
    elif flt.direction == "out":
        where.append(le.c.amount < 0)
    if flt.types:
        where.append(le.c.type.in_(flt.types))
    if flt.flags:
        where.append(le.c.review_flags.overlap(list(flt.flags)))
    if flt.text is not None:
        source = source.outerjoin(payee, payee.c.id == le.c.payee_id).outerjoin(
            category, category.c.id == le.c.category_id
        )
        where.extend(_word(w) for w in flt.text.split())
    return Composed(source, tuple(where))


def _category(flt: LedgerFilter) -> ColumnElement[bool]:
    options: list[ColumnElement[bool]] = []
    if flt.category_ids:
        if flt.category_descendants:
            tree = (
                select(category.c.id)
                .where(category.c.id.in_(flt.category_ids))
                .cte("category_tree", recursive=True)
            )
            tree = tree.union_all(select(category.c.id).where(category.c.parent_id == tree.c.id))
            options.append(le.c.category_id.in_(select(tree.c.id)))
        else:
            options.append(le.c.category_id.in_(flt.category_ids))
    if flt.uncategorised:
        # entries that could have a category but have none: flows, and entries with no type yet
        # (what an import produces before anything classifies it); never transfers or derived entries
        options.append(and_(or_(le.c.type == "flow", le.c.type.is_(None)), le.c.category_id.is_(None)))
    return or_(*options)


def like_pattern(word: str) -> str:
    escaped = word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _word(word: str) -> ColumnElement[bool]:
    pattern = like_pattern(word)
    fields = (
        le.c.description,
        le.c.note,
        le.c.source_text,
        st.c.counterparty_name,
        st.c.purpose,
        st.c.end_to_end_id,
        st.c.mandate_ref,
        payee.c.name,
        category.c.name,
    )
    return or_(*(f.ilike(pattern, escape="\\") for f in fields))
