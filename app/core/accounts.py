"""Accounts (spec §3.3, architecture §4.1): create, update, delete, close, reopen, list.

Every write is ONE transaction: settle lock shared, then the account's lock; it commits, and
only then settles where it changed what pass 0 or the synced status reads (settling takes the
settle lock exclusively in its own transaction). A settling failure is reported on the
result, never raised into the committed write. Reads take a connection.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from types import EllipsisType

from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

from app.core.balance.derived import recompute_derived
from app.core.ingest.identity import canonical_text
from app.core.settle.settle import SettleResult, settle
from app.utils.db.errors import constraint_name
from app.utils.db.locks import lock_accounts, lock_settle_shared, retry_on_deadlock


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


class AccountNotEmpty(AccountError):
    """Delete refused: the account holds something; closing it keeps its history."""

    def __init__(self, account_id: int, held: dict[str, int]) -> None:
        self.held = held
        what = ", ".join(f"{n} {name}" for name, n in held.items())
        super().__init__(f"account {account_id} holds {what} and cannot be deleted: close it instead")


class NotClearance(AccountError):
    """`start_date` and `providers` belong to clearance accounts only (spec §3.3)."""

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"{field} applies to a clearance account only")


class StartRequired(AccountError):
    """A clearance account is created with a start date: its opening record is dated on it (spec §3.3)."""

    def __init__(self) -> None:
        super().__init__("a clearance account needs a start date")


class InvalidProvider(AccountError):
    """A provider is a name: trimmed, not blank (spec §3.3)."""

    def __init__(self) -> None:
        super().__init__("a provider name must not be blank")


class ProviderTaken(AccountError):
    """Another clearance account in the same currency takes this provider (spec §3.3): the whole write is
    refused. `account_id` and `account_name` are the other account's."""

    def __init__(self, provider: str, currency: str, account_id: int, account_name: str) -> None:
        self.provider = provider
        self.currency = currency
        self.account_id = account_id
        self.account_name = account_name
        super().__init__(
            f"{provider!r} is already taken in {currency} by account {account_id} ({account_name})"
        )


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
    icon: str | None
    color: str | None
    synced: bool
    synced_through: date | None
    last_data_on: date | None
    unexplained_difference: int | None
    anchored: bool  # False: it has entries but no counting balance record
    balance: int  # the sum of its entries (`v_account_balance`), minor units of its currency
    providers: tuple[str, ...] = ()  # a clearance account's providers, sorted; empty for any other kind


def _canonical_ref(external_ref: str | None) -> str | None:
    return canonical_text(external_ref) or None


def _begin(conn: Connection, account_id: int | None = None) -> None:
    """Lock in the fixed order: settle shared, then the account; a missing account is named."""
    lock_settle_shared(conn)
    if account_id is None:
        return
    lock_accounts(conn, [account_id])
    if conn.execute(text("SELECT 1 FROM account WHERE id = :i"), {"i": account_id}).first() is None:
        raise AccountMissing(account_id)


@dataclass(frozen=True)
class CreatedAccount:
    account_id: int
    settle: SettleResult  # empty unless an external_ref was set


def create_account(
    engine: Engine,
    *,
    name: str,
    kind: str,
    currency: str,
    external_ref: str | None = None,
    sort_order: int = 0,
    note: str | None = None,
    icon: str | None = None,
    color: str | None = None,
    start_date: date | None = None,
    providers: Sequence[str] = (),
) -> int:
    """`create_account_result`'s id alone, for callers that have no use for the settle result."""
    return create_account_result(
        engine,
        name=name,
        kind=kind,
        currency=currency,
        external_ref=external_ref,
        sort_order=sort_order,
        note=note,
        icon=icon,
        color=color,
        start_date=start_date,
        providers=providers,
    ).account_id


def create_account_result(
    engine: Engine,
    *,
    name: str,
    kind: str,
    currency: str,
    external_ref: str | None = None,
    sort_order: int = 0,
    note: str | None = None,
    icon: str | None = None,
    color: str | None = None,
    start_date: date | None = None,
    providers: Sequence[str] = (),
) -> CreatedAccount:
    """Create an account, and nothing else. The currency must exist and never changes.

    `external_ref` is stored canonicalised (blank means none); setting one settles, because
    pass 0 compares it, and the settle result is returned.

    A clearance account (spec §3.3) is created with its `start_date` D, which writes its opening in the same
    write: a manual balance record of zero at the end of D; and with its `providers`, if any (see
    `set_clearance_providers`). Any other kind takes neither. A clearance account's providers book the
    documents they take, so creating one settles.
    """
    ref = _canonical_ref(external_ref)
    clearance = kind == "clearance"
    if clearance and start_date is None:
        raise StartRequired()
    if not clearance and start_date is not None:
        raise NotClearance("start_date")
    if not clearance and providers:
        raise NotClearance("providers")
    names = _provider_names(providers)

    def run() -> int:
        with engine.begin() as conn:
            lock_settle_shared(conn)
            if conn.execute(text("SELECT 1 FROM currency WHERE code = :c"), {"c": currency}).first() is None:
                raise UnknownCurrency(currency)
            try:
                account_id = int(
                    conn.execute(
                        text(
                            "INSERT INTO account"
                            " (name, kind, currency, external_ref, sort_order, note, icon, color)"
                            " VALUES (:name, :kind, :currency, :ref, :sort, :note, :icon, :color)"
                            " RETURNING id"
                        ),
                        {
                            "name": name,
                            "kind": kind,
                            "currency": currency,
                            "ref": ref,
                            "sort": sort_order,
                            "note": note,
                            "icon": icon,
                            "color": color,
                        },
                    ).scalar_one()
                )
            except DBAPIError as exc:
                if constraint_name(exc) == "ux_account_external_ref":
                    raise DuplicateExternalRef(str(ref)) from exc
                raise
            if clearance:
                _write_opening(conn, account_id, currency, start_date)
                _write_providers(conn, account_id, currency, names)
            return account_id

    account_id = retry_on_deadlock(run)
    return CreatedAccount(account_id, settle(engine) if ref is not None or clearance else SettleResult())


def update_account(
    engine: Engine,
    account_id: int,
    *,
    name: str | None = None,
    sort_order: int | None = None,
    note: str | None | EllipsisType = ...,
    external_ref: str | None | EllipsisType = ...,
    icon: str | None | EllipsisType = ...,
    color: str | None | EllipsisType = ...,
) -> SettleResult:
    """Change what is given (`...` leaves `note`, `external_ref`, `icon` or `color` alone, `None` clears it).

    Never the currency or the kind (I38). Setting or
    clearing the external reference settles; any other change returns an empty result.
    """
    sets: dict[str, object] = {}
    if name is not None:
        sets["name"] = name
    if sort_order is not None:
        sets["sort_order"] = sort_order
    if note is not ...:
        sets["note"] = note
    if icon is not ...:
        sets["icon"] = icon
    if color is not ...:
        sets["color"] = color
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
                conn.execute(
                    text(f"UPDATE account SET {assignments} WHERE id = :id"), {**sets, "id": account_id}
                )  # noqa: S608
            except DBAPIError as exc:
                if constraint_name(exc) == "ux_account_external_ref":
                    raise DuplicateExternalRef(str(sets["external_ref"])) from exc
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
                    conn.execute(
                        text(f"SELECT count(*) FROM {table} WHERE account_id = :i"), {"i": account_id}
                    ).scalar_one()  # noqa: S608
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


def _provider_names(providers: Sequence[str]) -> list[str]:
    """The names trimmed, none blank, one spelling per name compared without regard to case (the first)."""
    seen: dict[str, str] = {}
    for provider in providers:
        name = provider.strip()
        if not name:
            raise InvalidProvider()
        seen.setdefault(name.lower(), name)
    return list(seen.values())


def _write_opening(conn: Connection, account_id: int, currency: str, start_date: date | None) -> None:
    """The clearance account's start: a manual balance record of zero at the end of the start date."""
    conn.execute(
        text(
            "INSERT INTO balance_record (account_id, kind, balance, currency, balance_on)"
            " VALUES (:a, 'manual', 0, :c, :on)"
        ),
        {"a": account_id, "c": currency, "on": start_date},
    )
    recompute_derived(conn, account_id)


def _write_providers(conn: Connection, account_id: int, currency: str, names: Sequence[str]) -> None:
    """Replace the account's provider list whole. A name that another account takes in this currency refuses
    the whole write (`ProviderTaken`); the caller's transaction then rolls back."""
    conn.execute(text("DELETE FROM clearance_provider WHERE account_id = :a"), {"a": account_id})
    if not names:
        return
    _refuse_taken(conn, account_id, currency, names)
    try:
        with conn.begin_nested():
            conn.execute(
                text(
                    "INSERT INTO clearance_provider (account_id, currency, provider)"
                    " SELECT :a, :c, p FROM unnest(CAST(:names AS text[])) AS p"
                ),
                {"a": account_id, "c": currency, "names": list(names)},
            )
    except DBAPIError as exc:
        if constraint_name(exc) == "ux_clearance_provider":  # a concurrent write on another account won
            _refuse_taken(conn, account_id, currency, names)
        raise


def _refuse_taken(conn: Connection, account_id: int, currency: str, names: Sequence[str]) -> None:
    taken = conn.execute(
        text(
            "SELECT p.provider, p.account_id, a.name FROM clearance_provider p"
            " JOIN account a ON a.id = p.account_id"
            " WHERE p.currency = :c AND p.account_id <> :a AND lower(p.provider) = ANY(:lowers)"
            " ORDER BY p.account_id"
        ),
        {"a": account_id, "c": currency, "lowers": [n.lower() for n in names]},
    ).all()
    if not taken:
        return
    holders = {r.provider.lower(): r for r in taken}
    for name in names:  # the first of the requested names that is taken, as the user wrote it
        if (r := holders.get(name.lower())) is not None:
            raise ProviderTaken(name, currency, int(r.account_id), r.name)


@dataclass(frozen=True)
class ProvidersResult:
    providers: tuple[str, ...]
    settle: SettleResult


def set_clearance_providers(engine: Engine, account_id: int, providers: Sequence[str]) -> ProvidersResult:
    """Replace a clearance account's list of providers, whole (spec §3.3).

    Names are trimmed and not blank, compared without regard to case (the first spelling of a name is
    kept); a name that another clearance account in the same currency takes refuses the write
    (`ProviderTaken`, naming the provider and that account). Another kind of account has none
    (`NotClearance`). The write only changes the list: documents it now covers are booked by the settle
    that follows, and bookings of providers removed stay where they are.
    """
    names = _provider_names(providers)

    def run() -> tuple[str, ...]:
        with engine.begin() as conn:
            _begin(conn, account_id)
            row = conn.execute(
                text("SELECT kind, currency FROM account WHERE id = :i"), {"i": account_id}
            ).one()
            if row.kind != "clearance":
                raise NotClearance("providers")
            _write_providers(conn, account_id, row.currency, names)
            return tuple(sorted(names))

    stored = retry_on_deadlock(run)
    return ProvidersResult(stored, settle(engine))


def _set_closed(engine: Engine, account_id: int, closed_on: date | None) -> SettleResult:
    def run() -> None:
        with engine.begin() as conn:
            _begin(conn, account_id)
            conn.execute(
                text("UPDATE account SET closed_on = :d WHERE id = :i"), {"d": closed_on, "i": account_id}
            )

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
       a.icon, a.color, s.synced, c.synced_through, d.last_data_on, u.difference, bal.balance,
       COALESCE((SELECT array_agg(p.provider ORDER BY p.provider) FROM clearance_provider p
                  WHERE p.account_id = a.id), '{}') AS providers,
       NOT (EXISTS (SELECT 1 FROM ledger_entry e WHERE e.account_id = a.id)
            AND NOT EXISTS (SELECT 1 FROM v_balance_record b WHERE b.account_id = a.id)) AS anchored
  FROM account a
  JOIN v_account_synced s ON s.account_id = a.id
  JOIN v_account_coverage c ON c.account_id = a.id
  JOIN v_account_data_age d ON d.account_id = a.id
  JOIN v_account_balance bal ON bal.account_id = a.id
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
            icon=r.icon,
            color=r.color,
            synced=r.synced,
            synced_through=r.synced_through,
            last_data_on=r.last_data_on,
            unexplained_difference=None if r.difference is None else int(r.difference),
            anchored=r.anchored,
            balance=int(r.balance),
            providers=tuple(r.providers),
        )
        for r in conn.execute(text(_LIST_SQL))
    ]
