"""The account statement: source transactions and counting balance records in one list (architecture §4.1
'The account statement', spec §3.10).

A read of the bank layer only. The gap of each record comes from `derived.record_gaps`, the function that
derives the entries, so the two agree by construction; the running balance is the same rule applied to the
movements one by one. Household scale: the account's rows are read thin (id, date, amount) to compute
the balances, and only the requested page is read in full.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy import Connection, text

from app.core.balance.derived import RecordGap, record_gaps
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
    balance: int | None  # the running balance after it; None for a duplicate
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
    rows_sum: int | None  # None for the anchor
    difference: int | None  # None for the anchor
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


def _running_balances(rows: list[tuple[int, date, int]], gaps: list[RecordGap]) -> dict[int, int]:
    """Running balance after each movement `(id, booked_on, amount)` (duplicates excluded by the caller).

    In an interval i > 1: B(i-1) plus the interval's movements up to and including it; in the anchor's
    interval: B1 minus the interval's movements after it; after the last record: Bn plus the movements
    after it up to and including it; with no record: the sum from zero. Movements are taken by
    (booked_on, id).
    """
    ordered = sorted(rows, key=lambda r: (r[1], r[0]))
    dates = [g.balance_on for g in gaps]
    out: dict[int, int] = {}
    # group by interval: the first record whose date is not before the movement's (None: after the last)
    groups: dict[int | None, list[tuple[int, int]]] = {}
    for rid, on, amount in ordered:
        i = bisect_left(dates, on)
        groups.setdefault(i if i < len(gaps) else None, []).append((rid, amount))
    for index, members in groups.items():
        if index is None:
            base = gaps[-1].balance if gaps else 0
            running = base
            for rid, amount in members:
                running += amount
                out[rid] = running
        elif index == 0:  # the anchor's interval: counted back from the anchor
            running = gaps[0].balance - sum(a for _, a in members)
            for rid, amount in members:
                running += amount
                out[rid] = running
        else:
            running = gaps[index - 1].balance
            for rid, amount in members:
                running += amount
                out[rid] = running
    return out


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
    records = conn.execute(
        text(
            "SELECT id, balance_on, balance, kind FROM v_balance_record WHERE account_id = :a"
            " ORDER BY balance_on, id"
        ),
        {"a": account_id},
    ).all()
    movements = [(r.id, r.booked_on, int(r.amount)) for r in thin if not r.duplicate]
    gaps = record_gaps(
        [(r.id, r.balance_on, int(r.balance)) for r in records], [(d, a) for _, d, a in movements]
    )
    balances = _running_balances(movements, gaps)
    kinds = {r.id: r.kind for r in records}

    if amount is not None:  # the picker: balances stay what the whole account says
        keep = sorted(
            ((r.booked_on, r.id) for r in thin if r.imported and not r.duplicate and r.amount == amount),
            reverse=True,
        )
        ids = [i for _, i in keep][offset : offset + limit]
        found = _sources(conn, ids, balances)
        return Statement(account_id, currency, tuple(found[i] for i in ids), len(keep), limit, offset)

    # newest first; a record stands above the rows of its own date (rank 1 over 0)
    keys: list[tuple[date, int, int]] = [(r.booked_on, 0, r.id) for r in thin]
    keys += [(g.balance_on, 1, g.record_id) for g in gaps]
    keys.sort(reverse=True)
    page = keys[offset : offset + limit]
    sources = _sources(conn, [i for _, rank, i in page if rank == 0], balances)
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
                    rows_sum=None if g.anchor else g.rows_sum,
                    difference=None if g.anchor else g.amount,
                )
            )
    return Statement(account_id, currency, tuple(items), len(keys), limit, offset)


def _sources(conn: Connection, ids: list[int], balances: dict[int, int]) -> dict[int, SourceItem]:
    """The full rows of one page, with their running balances (a duplicate has none)."""
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
            balance=balances.get(r.id),
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
