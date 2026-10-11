"""The ledger entry list (architecture §4.1, spec §8): `GET /api/ledger/entries`.

A read: no lock, no write, no settle. The row carries ids, never names, icons or colours; the
client already holds the account, category and payee lists. Money travels as
`{"amount": <integer minor units>, "currency": <code>}` (architecture §4.5).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Query
from pydantic import BaseModel, StringConstraints

from app.api.errors import map_error
from app.api.ids import MAX_ID, EntityId
from app.api.routers.accounts import CurrencyCode, Money
from app.api.session import CurrentUser, EngineDep
from app.core.ledger import EntryRow, InvalidFilter, LedgerFilter, list_entries

router = APIRouter(prefix="/api/ledger/entries", tags=["entries"])

# a 422 in the same shape as a pydantic validation problem, located at the query parameter
map_error(
    InvalidFilter,
    422,
    "validation_error",
    details=lambda e: [{"location": ["query", e.parameter], "message": str(e), "type": "invalid_filter"}],
)

Ids = Annotated[list[EntityId] | None, Query()]
SearchText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


# the tokens of app.core.ledger.ENTRY_TYPES / REVIEW_FLAGS (a test keeps them equal)
EntryType = Literal["flow", "transfer", "opening", "valuation", "reconciliation"]
ReviewFlag = Literal["unconfirmed", "unclassified", "document_suggested", "waiting", "unmatched_transfer"]


class EntryOut(BaseModel):
    id: int
    version: int
    account_id: int
    booked_on: date
    value_on: date | None
    amount: Money
    type: EntryType | None
    description: str | None
    note: str | None
    counterparty_name: str | None
    purpose: str | None
    display_text: str | None
    payee_id: int | None
    category_id: int | None
    counter_account_id: int | None
    counterpart_entry_id: int | None
    source_transaction_id: int | None
    document_id: int | None
    review_flags: list[ReviewFlag]
    tag_ids: list[int]

    @staticmethod
    def of(row: EntryRow) -> EntryOut:
        return EntryOut(
            id=row.id,
            version=row.version,
            account_id=row.account_id,
            booked_on=row.booked_on,
            value_on=row.value_on,
            amount=Money(amount=row.amount, currency=row.currency),
            type=cast(EntryType | None, row.type),
            description=row.description,
            note=row.note,
            counterparty_name=row.counterparty_name,
            purpose=row.purpose,
            display_text=row.display_text,
            payee_id=row.payee_id,
            category_id=row.category_id,
            counter_account_id=row.counter_account_id,
            counterpart_entry_id=row.counterpart_entry_id,
            source_transaction_id=row.source_transaction_id,
            document_id=row.document_id,
            review_flags=cast(list[ReviewFlag], list(row.review_flags)),
            tag_ids=list(row.tag_ids),
        )


class EntryPageOut(BaseModel):
    entries: list[EntryOut]
    total: int  # entries matching the filter, whatever the page
    limit: int
    offset: int


@router.get("")
def list_entries_view(
    user: CurrentUser,
    engine: EngineDep,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    account_id: Ids = None,
    category_id: Ids = None,
    category_descendants: bool = True,
    uncategorised: bool = False,
    payee_id: Ids = None,
    tag_id: Ids = None,
    amount_min: Annotated[int | None, Query(ge=0, le=2**63 - 1)] = None,
    amount_max: Annotated[int | None, Query(ge=0, le=2**63 - 1)] = None,
    currency: CurrencyCode | None = None,
    direction: Literal["in", "out"] | None = None,
    q: SearchText | None = None,
    type: Annotated[list[str] | None, Query()] = None,
    flag: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=MAX_ID)] = 0,
) -> EntryPageOut:
    flt = LedgerFilter(
        date_from=from_,
        date_to=to,
        account_ids=tuple(account_id or ()),
        category_ids=tuple(category_id or ()),
        category_descendants=category_descendants,
        uncategorised=uncategorised,
        payee_ids=tuple(payee_id or ()),
        tag_ids=tuple(tag_id or ()),
        amount_min=amount_min,
        amount_max=amount_max,
        currency=currency,
        direction=direction,
        text=q,
        types=tuple(type or ()),
        flags=tuple(flag or ()),
    )
    with engine.connect() as conn:
        page = list_entries(conn, flt, limit=limit, offset=offset)
    return EntryPageOut(
        entries=[EntryOut.of(e) for e in page.entries], total=page.total, limit=page.limit, offset=page.offset
    )
