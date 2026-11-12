"""Account operations (architecture §4.1, spec §3.3).

Every write answers with what it touched: the account as it now stands (its facts are derived,
so they are read afresh) and the `settle` result. A settling failure is a notice inside a 200
response, never an HTTP error (architecture §5.2).

Money travels as `{"amount": <integer minor units>, "currency": <code>}`, never a bare number
(architecture §4.5).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Request
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import Connection, Engine

from app.api.errors import map_error
from app.api.ids import PathId
from app.api.routers.maintenance import SettleOut
from app.api.session import CurrentUser, EngineDep
from app.core import reporting as rp
from app.core.accounts import (
    AccountError,
    AccountMissing,
    AccountNotEmpty,
    AccountView,
    DuplicateExternalRef,
    InvalidProvider,
    NotClearance,
    ProviderTaken,
    StartRequired,
    UnknownCurrency,
    close_account,
    create_account_result,
    delete_account,
    list_accounts,
    reopen_account,
    update_account,
)
from app.core.balance.difference import records_since_zero
from app.core.settle.settle import SettleResult
from app.utils import clock

router = APIRouter(prefix="/api/ledger/accounts", tags=["accounts"])

# 404 for a missing account; 409 for a state conflict, told apart by `details.reason`; 422 for a
# value that is not valid input (an unknown currency).
map_error(AccountMissing, 404, "not_found")
map_error(DuplicateExternalRef, 409, "conflict", details=lambda e: {"reason": "duplicate_external_ref"})
map_error(
    AccountNotEmpty,
    409,
    "conflict",
    details=lambda e: {"reason": "account_not_empty", "held": e.held},
)
map_error(UnknownCurrency, 422, "validation_error", details=lambda e: {"reason": "unknown_currency"})
map_error(
    ProviderTaken,
    409,
    "conflict",
    details=lambda e: {
        "reason": "provider_taken",
        "provider": e.provider,
        "account": {"id": e.account_id, "name": e.account_name},
    },
)
map_error(
    InvalidProvider,
    422,
    "validation_error",
    details=lambda e: {"reason": "invalid_provider", "field": "providers"},
)
map_error(
    StartRequired,
    422,
    "validation_error",
    details=lambda e: {"reason": "start_required", "field": "start_date"},
)
map_error(
    NotClearance, 422, "validation_error", details=lambda e: {"reason": "not_clearance", "field": e.field}
)
map_error(AccountError, 409, "conflict", details=lambda e: {"reason": "account_refused"})

Kind = Literal[
    "checking",
    "savings",
    "card",
    "cash",
    "digital_wallet",
    "depot",
    "debt",
    "receivable",
    "asset",
    "clearance",
]
CurrencyCode = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


Name = Annotated[str, Field(min_length=1), AfterValidator(_not_blank)]
Providers = Annotated[
    list[Annotated[str, Field(max_length=200)]], Field(max_length=50)
]  # a clearance account's


class Money(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: StrictInt
    currency: CurrencyCode


class AccountOut(BaseModel):
    id: int
    name: str
    kind: str
    currency: str
    external_ref: str | None
    providers: list[str]  # a clearance account's providers, sorted; empty for any other kind
    closed_on: date | None
    sort_order: int
    note: str | None
    icon: str | None
    color: str | None
    synced: bool
    synced_through: date | None
    last_data_on: date | None
    unexplained_difference: Money | None
    anchored: bool
    balance: Money  # the sum of the account's entries
    balance_as_of: date | None  # the latest day the balance is known for
    records_since_zero: list[int] | None  # the reported records to look at; null without a difference
    # an investment account's performance (spec §8, D249); null on any other account and without a record
    net_deposits: Money | None
    gain: Money | None
    return_rate: int | None  # the annual return in basis points, as the savings `rate_bp`; null: none yet
    return_as_of: date | None  # the latest record's date


class NetWorthUnvaluedOut(BaseModel):
    amount: Money  # the accounts' native balances, summed
    accounts: int


class PointNetWorthOut(BaseModel):
    total: Money | None  # null when balances exist and none could be valued
    unvalued: list[NetWorthUnvaluedOut]


def worth_out(n: rp.NetWorth, base: str) -> PointNetWorthOut:
    return PointNetWorthOut(
        total=None if n.total is None else Money(amount=n.total, currency=base),
        unvalued=[
            NetWorthUnvaluedOut(amount=Money(amount=u.amount, currency=u.currency), accounts=u.accounts)
            for u in n.unvalued
        ],
    )


class GroupWorthOut(BaseModel):
    kind: Kind | None  # null = the closed accounts
    accounts: int
    net_worth: PointNetWorthOut  # at today's rate

    @staticmethod
    def of(g: rp.GroupWorth, base: str) -> GroupWorthOut:
        return GroupWorthOut(
            kind=g.kind,  # type: ignore[arg-type]
            accounts=g.accounts,
            net_worth=worth_out(g.net_worth, base),
        )


class ListGroupOut(BaseModel):
    kind: Kind | None  # null = the closed accounts
    accounts: int
    sums: list[Money]  # the balances summed per currency, ordered by code; nothing is converted

    @staticmethod
    def of(g: rp.GroupSums) -> ListGroupOut:
        return ListGroupOut(
            kind=g.kind,  # type: ignore[arg-type]
            accounts=g.accounts,
            sums=[Money(amount=a, currency=c) for c, a in g.sums],
        )


class AccountsOut(BaseModel):
    base_currency: str
    accounts: list[AccountOut]
    # the list's groups: a kind per kind with open accounts, in the kinds' usual order, then the closed
    groups: list[ListGroupOut]


class AccountWriteOut(BaseModel):
    account: AccountOut
    settle: SettleOut


def facts(conn: Connection, view: AccountView) -> AccountOut:
    diff = view.unexplained_difference
    return AccountOut(
        id=view.id,
        name=view.name,
        kind=view.kind,
        currency=view.currency,
        external_ref=view.external_ref,
        providers=list(view.providers),
        closed_on=view.closed_on,
        sort_order=view.sort_order,
        note=view.note,
        icon=view.icon,
        color=view.color,
        synced=view.synced,
        synced_through=view.synced_through,
        last_data_on=view.last_data_on,
        unexplained_difference=None if diff is None else Money(amount=diff, currency=view.currency),
        anchored=view.anchored,
        balance=Money(amount=view.balance, currency=view.currency),
        balance_as_of=view.balance_as_of,
        records_since_zero=None if diff is None else records_since_zero(conn, view.id),
        net_deposits=None
        if view.net_deposits is None
        else Money(amount=view.net_deposits, currency=view.currency),
        gain=None if view.gain is None else Money(amount=view.gain, currency=view.currency),
        return_rate=view.return_rate_bp,
        return_as_of=view.return_as_of,
    )


def account_facts(engine: Engine, account_id: int) -> AccountOut:
    """The account as it stands now (its facts are derived, so every write reads them afresh)."""
    with engine.connect() as conn:
        for view in list_accounts(conn):
            if view.id == account_id:
                return facts(conn, view)
    raise AccountMissing(account_id)


def written(engine: Engine, account_id: int, result: SettleResult) -> AccountWriteOut:
    return AccountWriteOut(account=account_facts(engine, account_id), settle=SettleOut.of(result))


class DeleteOut(BaseModel):
    settle: SettleOut


class CreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    kind: Kind
    currency: CurrencyCode
    external_ref: str | None = None
    sort_order: StrictInt = 0
    note: str | None = None
    icon: str | None = None
    color: str | None = None
    start_date: date | None = (
        None  # a clearance account requires it (its opening record), any other refuses it
    )
    providers: Providers = []  # a clearance account only


class UpdateBody(BaseModel):
    """Absent fields stay; `null` clears `external_ref`, `note`, `icon` and `color`.

    No currency, no kind: they never change.
    """

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    sort_order: StrictInt | None = None
    note: str | None = None
    external_ref: str | None = None
    icon: str | None = None
    color: str | None = None
    providers: Providers | None = None  # a clearance account: the whole list; absent leaves it


class CloseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    closed_on: date


@router.get("")
def list_ledger_accounts(user: CurrentUser, engine: EngineDep, request: Request) -> AccountsOut:
    """The accounts, and each group's count and balances summed per currency (every entry counts)."""
    config = request.app.state.config
    base: str = config.base_currency
    with engine.connect() as conn:
        return AccountsOut(
            base_currency=base,
            accounts=[facts(conn, v) for v in list_accounts(conn)],
            groups=[ListGroupOut.of(g) for g in rp.group_sums(conn, clock.today(config.timezone))],
        )


@router.post("", status_code=201)
def create_ledger_account(body: CreateBody, user: CurrentUser, engine: EngineDep) -> AccountWriteOut:
    created = create_account_result(
        engine,
        name=body.name,
        kind=body.kind,
        currency=body.currency,
        external_ref=body.external_ref,
        sort_order=body.sort_order,
        note=body.note,
        icon=body.icon,
        color=body.color,
        start_date=body.start_date,
        providers=body.providers,
    )
    return written(engine, created.account_id, created.settle)


@router.put("/{account_id}")
def update_ledger_account(
    account_id: PathId, body: UpdateBody, user: CurrentUser, engine: EngineDep
) -> AccountWriteOut:
    result = update_account(
        engine,
        account_id,
        name=body.name,
        sort_order=body.sort_order,
        note=body.note if "note" in body.model_fields_set else ...,
        external_ref=body.external_ref if "external_ref" in body.model_fields_set else ...,
        icon=body.icon if "icon" in body.model_fields_set else ...,
        color=body.color if "color" in body.model_fields_set else ...,
        providers=body.providers,
    )
    return written(engine, account_id, result)


@router.delete("/{account_id}")
def delete_ledger_account(account_id: PathId, user: CurrentUser, engine: EngineDep) -> DeleteOut:
    return DeleteOut(settle=SettleOut.of(delete_account(engine, account_id)))


@router.post("/{account_id}/close")
def close_ledger_account(
    account_id: PathId, body: CloseBody, user: CurrentUser, engine: EngineDep
) -> AccountWriteOut:
    return written(engine, account_id, close_account(engine, account_id, body.closed_on))


@router.post("/{account_id}/reopen")
def reopen_ledger_account(account_id: PathId, user: CurrentUser, engine: EngineDep) -> AccountWriteOut:
    return written(engine, account_id, reopen_account(engine, account_id))
