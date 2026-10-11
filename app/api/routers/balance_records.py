"""Balance record operations (architecture §4.1, spec §3.10): set, correct and delete.

Records change the account's derived entries, so every response carries the record, the
account's refreshed facts (anchored, unexplained difference) and the `settle` result.
Money is `{"amount": <integer minor units>, "currency": <code>}` in the account's currency.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine

from app.api.errors import ApiError, map_error
from app.api.routers.accounts import AccountOut, Money, account_facts
from app.api.routers.maintenance import SettleOut
from app.api.session import CurrentUser, EngineDep
from app.core.balance.read import RecordView, get_record, manual_record_id_on
from app.core.balance.records import (
    AccountNotFound,
    RecordDateTaken,
    RecordError,
    RecordNotFound,
    RecordResult,
    ReportedRecordNotEditable,
    delete_record,
    set_manual_record,
    update_manual_record,
)
from app.core.settle.settle import SettleResult

router = APIRouter(prefix="/api/ledger", tags=["balance records"])

map_error(AccountNotFound, 404, "not_found")
map_error(RecordNotFound, 404, "not_found")
map_error(RecordDateTaken, 409, "conflict", details=lambda e: {"reason": "record_date_taken"})
map_error(
    ReportedRecordNotEditable, 409, "conflict", details=lambda e: {"reason": "reported_record_not_editable"}
)
map_error(RecordError, 409, "conflict", details=lambda e: {"reason": "record_refused"})


class RecordOut(BaseModel):
    id: int
    account_id: int
    kind: str
    balance_on: date
    balance: Money

    @classmethod
    def of(cls, view: RecordView) -> RecordOut:
        return cls(
            id=view.id,
            account_id=view.account_id,
            kind=view.kind,
            balance_on=view.balance_on,
            balance=Money(amount=view.balance, currency=view.currency),
        )


class RecordWriteOut(BaseModel):
    record: RecordOut
    account: AccountOut
    settle: SettleOut


class RecordDeleteOut(BaseModel):
    deleted_record: RecordOut  # as it was
    account: AccountOut
    settle: SettleOut


class SetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    balance_on: date
    balance: Money


class CorrectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    balance: Money
    balance_on: date | None = None


def _same_currency(money: Money, currency: str) -> None:
    if money.currency != currency:
        raise ApiError(
            422,
            "validation_error",
            f"the balance is in {money.currency}; the account's currency is {currency}",
            {"reason": "currency_mismatch"},
        )


def _written(engine: Engine, record_id: int, result: RecordResult | SettleResult) -> RecordWriteOut:
    settle_result = result.settle if isinstance(result, RecordResult) else result
    with engine.connect() as conn:
        record = get_record(conn, record_id)
    return RecordWriteOut(
        record=RecordOut.of(record),
        account=account_facts(engine, record.account_id),
        settle=SettleOut.of(settle_result),
    )


@router.post("/accounts/{account_id}/balance-records", status_code=201)
def set_balance(
    account_id: int, body: SetBody, response: Response, user: CurrentUser, engine: EngineDep
) -> RecordWriteOut:
    """A manual record; a date that already has one edits it (200 instead of 201)."""
    _same_currency(body.balance, account_facts(engine, account_id).currency)
    with engine.connect() as conn:
        existed = manual_record_id_on(conn, account_id, body.balance_on) is not None
    result = set_manual_record(engine, account_id, body.balance_on, body.balance.amount, user_id=user.id)
    if existed:
        response.status_code = 200
    return _written(engine, result.record_id, result)


@router.put("/balance-records/{record_id}")
def correct_balance(
    record_id: int, body: CorrectBody, user: CurrentUser, engine: EngineDep
) -> RecordWriteOut:
    with engine.connect() as conn:
        record = get_record(conn, record_id)
    _same_currency(body.balance, record.currency)
    result = update_manual_record(engine, record_id, balance=body.balance.amount, balance_on=body.balance_on)
    return _written(engine, record_id, result)


@router.delete("/balance-records/{record_id}")
def remove_balance(record_id: int, user: CurrentUser, engine: EngineDep) -> RecordDeleteOut:
    with engine.connect() as conn:
        record = get_record(conn, record_id)
    result = delete_record(engine, record_id)
    return RecordDeleteOut(
        deleted_record=RecordOut.of(record),
        account=account_facts(engine, record.account_id),
        settle=SettleOut.of(result.settle),
    )
