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

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import Connection, Engine

from app.api.errors import map_error
from app.api.ids import PathId
from app.api.routers.maintenance import SettleOut
from app.api.session import CurrentUser, EngineDep
from app.core.accounts import (
    AccountError,
    AccountMissing,
    AccountNotEmpty,
    AccountView,
    DuplicateExternalRef,
    KindClassChange,
    UnknownCurrency,
    close_account,
    create_account,
    delete_account,
    list_accounts,
    reopen_account,
    update_account,
)
from app.core.balance.difference import records_since_zero
from app.core.settle.settle import SettleResult

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
map_error(KindClassChange, 409, "conflict", details=lambda e: {"reason": "kind_class_change"})
map_error(UnknownCurrency, 422, "validation_error", details=lambda e: {"reason": "unknown_currency"})
map_error(AccountError, 409, "conflict", details=lambda e: {"reason": "account_refused"})

Kind = Literal["checking", "savings", "card", "cash", "paypal", "depot", "loan", "asset"]
CurrencyCode = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


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
    closed_on: date | None
    sort_order: int
    note: str | None
    synced: bool
    synced_through: date | None
    last_data_on: date | None
    unexplained_difference: Money | None
    anchored: bool
    records_since_zero: list[int] | None  # the reported records to look at; null without a difference


class AccountsOut(BaseModel):
    accounts: list[AccountOut]


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
        closed_on=view.closed_on,
        sort_order=view.sort_order,
        note=view.note,
        synced=view.synced,
        synced_through=view.synced_through,
        last_data_on=view.last_data_on,
        unexplained_difference=None if diff is None else Money(amount=diff, currency=view.currency),
        anchored=view.anchored,
        records_since_zero=None if diff is None else records_since_zero(conn, view.id),
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


class CreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    kind: Kind
    currency: CurrencyCode
    external_ref: str | None = None
    sort_order: StrictInt = 0
    note: str | None = None


class UpdateBody(BaseModel):
    """Absent fields stay; `external_ref: null` clears it. No currency: it never changes."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    sort_order: StrictInt | None = None
    note: str | None = None
    external_ref: str | None = None
    kind: Kind | None = None


class CloseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    closed_on: date


@router.get("")
def list_all(user: CurrentUser, engine: EngineDep) -> AccountsOut:
    with engine.connect() as conn:
        return AccountsOut(accounts=[facts(conn, v) for v in list_accounts(conn)])


@router.post("", status_code=201)
def create(body: CreateBody, user: CurrentUser, engine: EngineDep) -> AccountWriteOut:
    account_id = create_account(
        engine,
        name=body.name,
        kind=body.kind,
        currency=body.currency,
        external_ref=body.external_ref,
        sort_order=body.sort_order,
        note=body.note,
    )
    # the core settles inside a create that sets an external_ref and reports nothing back
    return written(engine, account_id, SettleResult())


@router.put("/{account_id}")
def update(account_id: PathId, body: UpdateBody, user: CurrentUser, engine: EngineDep) -> AccountWriteOut:
    result = update_account(
        engine,
        account_id,
        name=body.name,
        sort_order=body.sort_order,
        note=body.note,
        external_ref=body.external_ref if "external_ref" in body.model_fields_set else ...,
        kind=body.kind,
    )
    return written(engine, account_id, result)


@router.delete("/{account_id}", status_code=204)
def delete(account_id: PathId, user: CurrentUser, engine: EngineDep) -> Response:
    delete_account(engine, account_id)
    return Response(status_code=204)


@router.post("/{account_id}/close")
def close(account_id: PathId, body: CloseBody, user: CurrentUser, engine: EngineDep) -> AccountWriteOut:
    return written(engine, account_id, close_account(engine, account_id, body.closed_on))


@router.post("/{account_id}/reopen")
def reopen(account_id: PathId, user: CurrentUser, engine: EngineDep) -> AccountWriteOut:
    return written(engine, account_id, reopen_account(engine, account_id))
