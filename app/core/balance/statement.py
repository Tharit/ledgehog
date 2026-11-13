"""The account statement: source transactions and counting balance records in one list (architecture §4.1
'The account statement', spec §3.10).

A read of the bank layer only. The gap of each record comes from `derived.record_gaps`, the function that
derives the entries, so the two agree by construction. Household scale: the account's rows are read thin
(id, date, amount) to compute the gaps, and only the requested page is read in full.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy import Connection, text

from app.core.balance.derived import load_derivation_input, record_gaps
from app.core.domain.source import BookingRef


@dataclass(frozen=True)
class DuplicateRef:
    """The row a duplicate duplicates, named by what a person recognises it by."""

    id: int
    booked_on: date
    amount: int


@dataclass(frozen=True)
class SourceItem:
    id: int
    booked_on: date
    value_on: date | None
    amount: int
    counterparty_name: str | None
    purpose: str | None
    authored: bool
    duplicate_of: DuplicateRef | None
    entry_id: int | None  # the lowest id among its entries; None for a duplicate
    run_id: int | None
    kind: Literal["source"] = "source"
    origin: str = "import"  # `import`, `user` or `booking`
    booking: BookingRef | None = None  # a booking's source, for navigation


@dataclass(frozen=True)
class RecordItem:
    id: int
    balance_on: date
    record_kind: str  # 'reported' | 'manual'
    balance: int
    anchor: bool
    difference: int  # the record's derived entry; for the anchor, its opening
    late_arrivals: int
    kind: Literal["record"] = "record"


@dataclass(frozen=True)
class Statement:
    account_id: int
    currency: str
    items: tuple[SourceItem | RecordItem, ...]
    total: int
    limit: int
    offset: int


class StatementAccountMissing(LookupError):
    def __init__(self, account_id: int) -> None:
        self.account_id = account_id
        super().__init__(f"account {account_id} does not exist")


def get_statement(
    conn: Connection, account_id: int, *, limit: int = 100, offset: int = 0, amount: int | None = None
) -> Statement:
    """The account's statement, newest first. `amount` keeps the imported, non-duplicate source
    transactions of that amount and no record (the picker of 'mark as duplicate of...')."""
    currency = conn.execute(
        text("SELECT currency FROM account WHERE id = :a"), {"a": account_id}
    ).scalar_one_or_none()
    if currency is None:
        raise StatementAccountMissing(account_id)
    thin = conn.execute(
        text(
            "SELECT id, booked_on, amount, duplicate_of IS NOT NULL AS duplicate,"
            " origin = 'import' AS imported"
            " FROM source_transaction WHERE account_id = :a"
        ),
        {"a": account_id},
    ).all()
    data = load_derivation_input(conn, account_id)
    gaps = record_gaps(data)
    kinds = {r.id: "reported" if r.run_id is not None else "manual" for r in data.records}

    if amount is not None:  # the picker
        keep = sorted(
            ((r.booked_on, r.id) for r in thin if r.imported and not r.duplicate and r.amount == amount),
            reverse=True,
        )
        ids = [i for _, i in keep][offset : offset + limit]
        found = _sources(conn, ids)
        return Statement(account_id, currency, tuple(found[i] for i in ids), len(keep), limit, offset)

    # newest first; a record stands above the rows of its own date (rank 1 over 0)
    keys: list[tuple[date, int, int]] = [(r.booked_on, 0, r.id) for r in thin]
    keys += [(g.balance_on, 1, g.record_id) for g in gaps]
    keys.sort(reverse=True)
    page = keys[offset : offset + limit]
    sources = _sources(conn, [i for _, rank, i in page if rank == 0])
    by_record = {g.record_id: g for g in gaps}
    items: list[SourceItem | RecordItem] = []
    for _, rank, item_id in page:
        if rank == 0:
            items.append(sources[item_id])
        else:
            g = by_record[item_id]
            items.append(
                RecordItem(
                    id=g.record_id,
                    balance_on=g.balance_on,
                    record_kind=kinds[g.record_id],
                    balance=g.balance,
                    anchor=g.anchor,
                    difference=g.amount,
                    late_arrivals=g.late_arrivals,
                )
            )
    return Statement(account_id, currency, tuple(items), len(keys), limit, offset)


def _sources(conn: Connection, ids: list[int]) -> dict[int, SourceItem]:
    """The full rows of one page."""
    if not ids:
        return {}
    rows = conn.execute(
        text(
            "SELECT s.id, s.booked_on, s.value_on, s.amount, s.counterparty_name, s.purpose,"
            " s.origin = 'user' AS authored, s.origin, s.source_id, s.import_run_id AS run_id,"
            " o.id AS of_id, o.booked_on AS of_on, o.amount AS of_amount,"
            " d.provider, d.reference, c.account_id AS charge_account_id,"
            " (SELECT min(e.id) FROM ledger_entry e WHERE e.source_transaction_id = s.id) AS entry_id"
            " FROM source_transaction s LEFT JOIN source_transaction o ON o.id = s.duplicate_of"
            " LEFT JOIN external_document d ON d.id = CASE WHEN s.origin = 'booking'"
            "   AND split_part(s.source_id, ':', 1) = 'document'"
            "   THEN CAST(split_part(s.source_id, ':', 2) AS bigint) END"
            " LEFT JOIN ledger_entry c ON c.id = CASE WHEN s.origin = 'booking'"
            "   AND split_part(s.source_id, ':', 1) = 'transfer'"
            "   THEN CAST(split_part(s.source_id, ':', 2) AS bigint) END"
            " WHERE s.id = ANY(:ids)"
        ),
        {"ids": ids},
    )
    return {
        r.id: SourceItem(
            id=r.id,
            booked_on=r.booked_on,
            value_on=r.value_on,
            amount=int(r.amount),
            counterparty_name=r.counterparty_name,
            purpose=r.purpose,
            authored=r.authored,
            duplicate_of=None if r.of_id is None else DuplicateRef(r.of_id, r.of_on, int(r.of_amount)),
            entry_id=r.entry_id,  # a duplicate has no entries
            run_id=r.run_id,
            origin=r.origin,
            booking=None
            if r.origin != "booking"
            else BookingRef(
                r.source_id.partition(":")[0],
                int(r.source_id.partition(":")[2]),
                provider=r.provider,
                reference=r.reference,
                account_id=r.charge_account_id,
            ),
        )
        for r in rows
    }
