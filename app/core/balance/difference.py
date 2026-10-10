"""The unexplained difference and what localises it (spec §3.11, §5.10); anchoring status."""

from __future__ import annotations

from sqlalchemy import Connection, text


def unexplained_difference(conn: Connection, account_id: int) -> int | None:
    """The account's unexplained difference in minor units, `None` when it has none."""
    value = conn.execute(
        text("SELECT difference FROM v_unexplained_difference WHERE account_id = :a"), {"a": account_id}
    ).scalar_one_or_none()
    return None if value is None else int(value)


def records_since_zero(conn: Connection, account_id: int) -> list[int]:
    """The reported records since the running sum of reconciliations was last zero, in order.

    The sum runs over the counting records from the first reported one (ordered by date, then id),
    manual ones included, as in `v_unexplained_difference`; the list stops at the latest reported
    record and is empty while the difference is zero.
    """
    records = conn.execute(
        text(
            "SELECT b.id, b.kind, COALESCE(e.amount, 0) AS rec FROM v_balance_record b "
            "LEFT JOIN ledger_entry e ON e.balance_record_id = b.id AND e.type = 'reconciliation' "
            "WHERE b.account_id = :a ORDER BY b.balance_on, b.id"
        ),
        {"a": account_id},
    ).all()
    reported = [i for i, r in enumerate(records) if r.kind == "reported"]
    if not reported:
        return []
    total = 0
    last_zero = reported[0] - 1  # before the first reported record the sum is zero
    for i in range(reported[0], reported[-1] + 1):
        total += int(records[i].rec)
        if total == 0:
            last_zero = i
    return [int(records[i].id) for i in reported if i > last_zero]


def is_anchored(conn: Connection, account_id: int) -> bool:
    """False when the account holds entries but no counting record: 'balance not anchored'."""
    return bool(
        conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM v_balance_record WHERE account_id = :a) "
                "OR NOT EXISTS (SELECT 1 FROM ledger_entry WHERE account_id = :a)"
            ),
            {"a": account_id},
        ).scalar_one()
    )
