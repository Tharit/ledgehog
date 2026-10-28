"""The account statement (architecture §4.1 'The account statement', spec §3.10).

A read of the bank layer: the account's source transactions, duplicates included, and its counting
balance records in one list, newest first, with the running balance and each record's gap. No lock,
no write, no settle. Money travels as `{"amount", "currency"}` in the account's currency.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.errors import map_error
from app.api.ids import MAX_ID, PathId
from app.api.routers.accounts import Money
from app.api.routers.entries import BookingOut
from app.api.session import CurrentUser, EngineDep
from app.core.balance.statement import RecordItem, SourceItem, StatementAccountMissing, get_statement

router = APIRouter(prefix="/api/ledger/accounts", tags=["accounts"])

map_error(StatementAccountMissing, 404, "not_found")


class DuplicateOfOut(BaseModel):
    id: int
    booked_on: date
    amount: Money


class StatementSourceOut(BaseModel):
    kind: Literal["source"]
    id: int  # the source transaction's id: provenance is `GET /api/ledger/sources/{id}`
    booked_on: date
    value_on: date | None
    amount: Money
    counterparty_name: str | None
    purpose: str | None
    authored: bool  # entered by hand
    origin: Literal["import", "user", "booking"]
    booking: BookingOut | None  # a booking's source, for navigation; null for any other row
    duplicate_of: DuplicateOfOut | None
    entry_id: int | None  # opens the row's unit in the review panel; null for a duplicate
    run_id: int | None  # null for an authored row
    balance: Money | None  # the running balance after it; null for a duplicate


class StatementRecordOut(BaseModel):
    kind: Literal["record"]
    id: int
    balance_on: date
    record_kind: Literal["reported", "manual"]
    balance: Money
    anchor: bool  # the account's earliest counting record
    rows_sum: Money | None  # the movements of the record's interval; null for the anchor
    difference: Money | None  # what the record owns beyond them; null for the anchor


StatementItemOut = Annotated[StatementSourceOut | StatementRecordOut, Field(discriminator="kind")]


class StatementOut(BaseModel):
    items: list[StatementItemOut]
    total: int  # every item the account has, whatever the page
    limit: int
    offset: int


def _item(item: SourceItem | RecordItem, currency: str) -> StatementSourceOut | StatementRecordOut:
    def money(value: int) -> Money:
        return Money(amount=value, currency=currency)

    if isinstance(item, RecordItem):
        return StatementRecordOut(
            kind="record",
            id=item.id,
            balance_on=item.balance_on,
            record_kind=item.record_kind,  # type: ignore[arg-type]
            balance=money(item.balance),
            anchor=item.anchor,
            rows_sum=None if item.rows_sum is None else money(item.rows_sum),
            difference=None if item.difference is None else money(item.difference),
        )
    dup = item.duplicate_of
    return StatementSourceOut(
        kind="source",
        id=item.id,
        booked_on=item.booked_on,
        value_on=item.value_on,
        amount=money(item.amount),
        counterparty_name=item.counterparty_name,
        purpose=item.purpose,
        authored=item.authored,
        origin=cast(Literal["import", "user", "booking"], item.origin),
        booking=None
        if item.booking is None
        else BookingOut(
            kind=cast(Literal["document", "transfer"], item.booking.kind),
            id=item.booking.id,
            provider=item.booking.provider,
            reference=item.booking.reference,
            account_id=item.booking.account_id,
        ),
        duplicate_of=(
            None
            if dup is None
            else DuplicateOfOut(id=dup.id, booked_on=dup.booked_on, amount=money(dup.amount))
        ),
        entry_id=item.entry_id,
        run_id=item.run_id,
        balance=None if item.balance is None else money(item.balance),
    )


@router.get("/{account_id}/statement")
def account_statement(
    account_id: PathId,
    user: CurrentUser,
    engine: EngineDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=MAX_ID)] = 0,
    amount: Annotated[
        int | None,
        Query(
            ge=-MAX_ID,
            le=MAX_ID,
            description="Signed minor units: only the imported source transactions of that amount "
            "that are not duplicates, and no record.",
        ),
    ] = None,
) -> StatementOut:
    """The account's source transactions and counting balance records, newest first."""
    with engine.connect() as conn:
        found = get_statement(conn, account_id, limit=limit, offset=offset, amount=amount)
    return StatementOut(
        items=[_item(i, found.currency) for i in found.items],
        total=found.total,
        limit=found.limit,
        offset=found.offset,
    )
