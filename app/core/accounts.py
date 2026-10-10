"""Accounts (spec §3.3, architecture §4.1): create, update, delete, close, reopen, list.

Every write is ONE transaction: settle lock shared, then the account's lock; it commits, and
only then settles where it changed what pass 0 or the synced status reads (settling takes the
settle lock exclusively in its own transaction). A settling failure is reported on the
result, never raised into the committed write. Reads take a connection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from types import EllipsisType

import psycopg.errors
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

from app.core.ingest.identity import canonical_text
from app.core.settle.settle import SettleResult, settle
from app.utils.db.locks import lock_accounts, lock_settle_shared, retry_on_deadlock

INVESTMENT_KINDS = frozenset({"depot", "asset"})


class AccountError(Exception):
    """An account operation was refused; the message states the rule. Nothing was written."""


class AccountMissing(AccountError):
    def __init__(self, account_id: int) -> None:
        self.account_id = account_id
        super().__init__(f"account {account_id} does not exist")


class UnknownCurrency(AccountError):
    def __init__(self, currency: str) -> None:
        super().__init__(f"currency {currency!r} is not a known currency")


class DuplicateExternalRef(AccountError):
    """Another account already has this external_ref (compared canonicalised, spec §5.2)."""

    def __init__(self, external_ref: str) -> None:
        super().__init__(f"another account already has the external reference {external_ref!r}")


class KindClassChange(AccountError):
    """A depot or asset stays one, and any other kind never becomes one (I38)."""

    def __init__(self, account_id: int, kind: str) -> None:
        super().__init__(
            f"account {account_id} cannot become {kind!r}: whether an account is an investment "
            "account (depot, asset) is fixed at creation"
        )


class AccountNotEmpty(AccountError):
    """Delete refused: the account holds something; closing it keeps its history."""

    def __init__(self, account_id: int, held: dict[str, int]) -> None:
        self.held = held
        what = ", ".join(f"{n} {name}" for name, n in held.items())
        super().__init__(f"account {account_id} holds {what} and cannot be deleted: close it instead")


@dataclass(frozen=True)
class AccountView:
    id: int
    name: str
    kind: str
    currency: str
    external_ref: str | None
    closed_on: date | None
    sort_order: int
    note: str | None
    synced: bool
    synced_through: date | None
    last_data_on: date | None
    unexplained_difference: int | None
    anchored: bool  # False: it has entries but no counting balance record


def _canonical_ref(external_ref: str | None) -> str | None:
    return canonical_text(external_ref) or None


def _constraint(exc: DBAPIError) -> str | None:
    orig = exc.orig
    return getattr(getattr(orig, "diag", None), "constraint_name", None) if orig is not None else None


def _begin(conn: Connection, account_id: int | None = None) -> None:
    """Lock in the fixed order: settle shared, then the account; a missing account is named."""
    lock_settle_shared(conn)
    if account_id is None:
        return
    lock_accounts(conn, [account_id])
    if conn.execute(text("SELECT 1 FROM account WHERE id = :i"), {"i": account_id}).first() is None:
        raise AccountMissing(account_id)


def create_account(
    engine: Engine,
    *,
    name: str,
    kind: str,
    currency: str,
    external_ref: str | None = None,
    sort_order: int = 0,
    note: str | None = None,
) -> int:
    """Create an account, and nothing else. The currency must exist and never changes.

    `external_ref` is stored canonicalised (blank means none); setting one settles, because
    pass 0 compares it.
    """
    ref = _canonical_ref(external_ref)

    def run() -> int:
        with engine.begin() as conn:
            lock_settle_shared(conn)
            if conn.execute(text("SELECT 1 FROM currency WHERE code = :c"), {"c": currency}).first() is None:
                raise UnknownCurrency(currency)
            try:
                return int(
                    conn.execute(
                        text(
                            "INSERT INTO account (name, kind, currency, external_ref, sort_order, note)"
                            " VALUES (:name, :kind, :currency, :ref, :sort, :note) RETURNING id"
                        ),
                        {
                            "name": name,
                            "kind": kind,
                            "currency": currency,
                            "ref": ref,
                            "sort": sort_order,
                            "note": note,
                        },
                    ).scalar_one()
                )
            except DBAPIError as exc:
                if _constraint(exc) == "ux_account_external_ref":
                    raise DuplicateExternalRef(str(ref)) from exc
                raise

    account_id = retry_on_deadlock(run)
    if ref is not None:
        settle(engine)
    return account_id


def update_account(
    engine: Engine,
    account_id: int,
    *,
    name: str | None = None,
    sort_order: int | None = None,
    note: str | None = None,
    external_ref: str | None | EllipsisType = ...,
    kind: str | None = None,
) -> SettleResult:
    """Change what is given (`...` leaves `external_ref` alone, `None` clears it).

    Never the currency. A kind changes only within its class (investment or not). Setting or
    clearing the external reference settles; any other change returns an empty result.
    """
    sets: dict[str, object] = {}
    if name is not None:
        sets["name"] = name
    if sort_order is not None:
        sets["sort_order"] = sort_order
    if note is not None:
        sets["note"] = note
    if kind is not None:
        sets["kind"] = kind
    ref_given = external_ref is not ...
    if ref_given:
        assert not isinstance(external_ref, EllipsisType)
        sets["external_ref"] = _canonical_ref(external_ref)

    def run() -> None:
        with engine.begin() as conn:
            _begin(conn, account_id)
            if not sets:
                return
            assignments = ", ".join(f"{col} = :{col}" for col in sets)
            try:
                conn.execute(text(f"UPDATE account SET {assignments} WHERE id = :id"), {**sets, "id": account_id})  # noqa: S608
            except DBAPIError as exc:
                if _constraint(exc) == "ux_account_external_ref":
                    raise DuplicateExternalRef(str(sets["external_ref"])) from exc
                if isinstance(exc.orig, psycopg.errors.RaiseException) and "investment account" in str(exc.orig):
                    raise KindClassChange(account_id, str(kind)) from exc
                raise

    retry_on_deadlock(run)
    return settle(engine) if ref_given else SettleResult()


def delete_account(engine: Engine, account_id: int) -> SettleResult:
    """Delete an account that holds nothing: no entries, source rows, runs, balance records, links."""

    def run() -> None:
        with engine.begin() as conn:
            _begin(conn, account_id)
            held = {
                label: int(
                    conn.execute(text(f"SELECT count(*) FROM {table} WHERE account_id = :i"), {"i": account_id}).scalar_one()  # noqa: S608
                )
                for label, table in (
                    ("entries", "ledger_entry"),
                    ("source transactions", "source_transaction"),
                    ("runs", "import_run"),
                    ("balance records", "balance_record"),
                    ("links", "account_source"),
                )
            }
            held = {k: n for k, n in held.items() if n}
            if held:
                raise AccountNotEmpty(account_id, held)
            conn.execute(text("DELETE FROM account WHERE id = :i"), {"i": account_id})

    retry_on_deadlock(run)
    return settle(engine)


def _set_closed(engine: Engine, account_id: int, closed_on: date | None) -> SettleResult:
    def run() -> None:
        with engine.begin() as conn:
            _begin(conn, account_id)
            conn.execute(text("UPDATE account SET closed_on = :d WHERE id = :i"), {"d": closed_on, "i": account_id})

    retry_on_deadlock(run)
    return settle(engine)


def close_account(engine: Engine, account_id: int, closed_on: date) -> SettleResult:
    """Close: the account is unsynced at once; its links stay (spec §3.3)."""
    return _set_closed(engine, account_id, closed_on)


def reopen_account(engine: Engine, account_id: int) -> SettleResult:
    """Clear the closing date; the links make it synced again."""
    return _set_closed(engine, account_id, None)


_LIST_SQL = """
SELECT a.id, a.name, a.kind, a.currency, a.external_ref, a.closed_on, a.sort_order, a.note,
       s.synced, c.synced_through, d.last_data_on, u.difference,
       NOT (EXISTS (SELECT 1 FROM ledger_entry e WHERE e.account_id = a.id)
            AND NOT EXISTS (SELECT 1 FROM v_balance_record b WHERE b.account_id = a.id)) AS anchored
  FROM account a
  JOIN v_account_synced s ON s.account_id = a.id
  JOIN v_account_coverage c ON c.account_id = a.id
  JOIN v_account_data_age d ON d.account_id = a.id
  LEFT JOIN v_unexplained_difference u ON u.account_id = a.id
 ORDER BY (a.closed_on IS NOT NULL), a.sort_order, a.name, a.id
"""


def list_accounts(conn: Connection) -> list[AccountView]:
    """Every account, open ones first, with the facts the views derive."""
    return [
        AccountView(
            id=r.id,
            name=r.name,
            kind=r.kind,
            currency=r.currency,
            external_ref=r.external_ref,
            closed_on=r.closed_on,
            sort_order=r.sort_order,
            note=r.note,
            synced=r.synced,
            synced_through=r.synced_through,
            last_data_on=r.last_data_on,
            unexplained_difference=None if r.difference is None else int(r.difference),
            anchored=r.anchored,
        )
        for r in conn.execute(text(_LIST_SQL))
    ]
