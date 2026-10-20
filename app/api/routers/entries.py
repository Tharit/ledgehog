"""The ledger entry list (architecture §4.1, spec §8): `GET /api/ledger/entries`.

A read: no lock, no write, no settle. The row carries ids, never names, icons or colours; the
client already holds the account, category and payee lists. Money travels as
`{"amount": <integer minor units>, "currency": <code>}` (architecture §4.5).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, StringConstraints

from app.api.errors import map_error
from app.api.ids import MAX_ID, EntityId, PathId
from app.api.routers.accounts import CurrencyCode, Money
from app.api.session import CurrentUser, EngineDep
from app.core.domain.source import SourceFields
from app.core.ledger import EntryRow, InvalidFilter, LedgerFilter, export_csv, get_entry, list_entries
from app.utils import clock

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


class SourceTransactionOut(BaseModel):
    """An entry's source transaction as the UI and rules read it; never the raw record or the hash."""

    amount: Money  # the source transaction's own amount; a split part's entry carries only its part
    counterparty_name: str | None
    counterparty_ref: str | None
    counterparty_bic: str | None
    purpose: str | None
    booking_text: str | None
    end_to_end_id: str | None
    mandate_ref: str | None
    instructed_amount: Money | None  # the instructed amount with its currency, where the source reports one
    source_format: str | None

    @staticmethod
    def of(src: SourceFields | None) -> SourceTransactionOut | None:
        if src is None:
            return None
        instructed = (
            None
            if src.instructed_amount is None or src.instructed_currency is None
            else Money(amount=src.instructed_amount, currency=src.instructed_currency)
        )
        return SourceTransactionOut(
            amount=Money(amount=src.amount, currency=src.currency),
            counterparty_name=src.counterparty_name,
            counterparty_ref=src.counterparty_ref,
            counterparty_bic=src.counterparty_bic,
            purpose=src.purpose,
            booking_text=src.booking_text,
            end_to_end_id=src.end_to_end_id,
            mandate_ref=src.mandate_ref,
            instructed_amount=instructed,
            source_format=src.source_format,
        )


class PartnerOut(BaseModel):
    """The other leg of a paired transfer: where, when and how much."""

    entry_id: int
    account_id: int
    booked_on: date
    amount: Money


class EntryDocumentOut(BaseModel):
    """The document of the entry's transaction (every entry of a split reads the one its original carries)."""

    id: int
    provider: str
    merchant_name: str | None
    line_count: int


class EntryDocumentLineOut(BaseModel):
    """The entry's own line of that document: what a rule's `document_line` reads (spec §5.8)."""

    line_no: int
    description: str


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
    display_text: str | None
    payee_id: int | None
    category_id: int | None
    counter_account_id: int | None
    counterpart_entry_id: int | None
    source_transaction_id: int | None
    document_id: int | None
    review_flags: list[ReviewFlag]
    tag_ids: list[int]
    source: SourceTransactionOut | None  # null only for derived entries
    derivation: dict[str, Any]  # as stored: derived field -> {"pass", "basis", ...}; `{}` when none
    unit_key: int | None  # the unit it is reviewed in (spec §6); null for a derived entry
    authored: bool  # entered by the user (the entry form); its `source` is the authored row
    partner: PartnerOut | None  # the other leg of a paired transfer, null otherwise
    # the transaction's document (null when none), whichever entry of the transaction carries the link; and
    # the entry's own line of it (null when the entry has none: an unsplit transaction of several lines, a
    # split made by hand). `document_id` stays the entry's own column: set on the original entry only
    document: EntryDocumentOut | None
    document_line: EntryDocumentLineOut | None

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
            display_text=row.display_text,
            payee_id=row.payee_id,
            category_id=row.category_id,
            counter_account_id=row.counter_account_id,
            counterpart_entry_id=row.counterpart_entry_id,
            source_transaction_id=row.source_transaction_id,
            document_id=row.document_id,
            review_flags=cast(list[ReviewFlag], list(row.review_flags)),
            tag_ids=list(row.tag_ids),
            source=SourceTransactionOut.of(row.source),
            derivation=dict(row.derivation),
            unit_key=row.unit_key,
            authored=row.authored,
            partner=None
            if row.partner is None
            else PartnerOut(
                entry_id=row.partner.entry_id,
                account_id=row.partner.account_id,
                booked_on=row.partner.booked_on,
                amount=Money(amount=row.partner.amount, currency=row.partner.currency),
            ),
            document=None
            if row.document is None
            else EntryDocumentOut(
                id=row.document.id,
                provider=row.document.provider,
                merchant_name=row.document.merchant_name,
                line_count=row.document.line_count,
            ),
            document_line=None
            if row.document_line is None
            else EntryDocumentLineOut(
                line_no=row.document_line.line_no, description=row.document_line.description
            ),
        )


class EntryPageOut(BaseModel):
    entries: list[EntryOut]
    total: int  # entries matching the filter, whatever the page
    limit: int
    offset: int


def ledger_filter(
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
) -> LedgerFilter:
    """The ledger filter as query parameters: the one definition, shared by the list and the export."""
    return LedgerFilter(
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


FilterQuery = Annotated[LedgerFilter, Depends(ledger_filter)]


@router.get("")
def list_entries_view(
    user: CurrentUser,
    engine: EngineDep,
    flt: FilterQuery,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=MAX_ID)] = 0,
) -> EntryPageOut:
    with engine.connect() as conn:
        page = list_entries(conn, flt, limit=limit, offset=offset)
    return EntryPageOut(
        entries=[EntryOut.of(e) for e in page.entries], total=page.total, limit=page.limit, offset=page.offset
    )


@router.get(
    "/export",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}, "description": "The CSV."}},
)
def export_entries(
    user: CurrentUser, engine: EngineDep, request: Request, flt: FilterQuery
) -> StreamingResponse:
    """Every entry matching the list's filter, in the list's order, as CSV (one row per entry).

    Declared before `/{entry_id}`. Streamed from a server-side cursor: no page, no cap.
    """

    def body() -> Iterator[str]:
        with engine.connect() as conn:
            yield from export_csv(conn, flt)

    filename = f"ledger-{clock.today(request.app.state.config.timezone).isoformat()}.csv"
    return StreamingResponse(
        body(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class EntryMissing(LookupError):
    def __init__(self, entry_id: int) -> None:
        self.entry_id = entry_id
        super().__init__(f"entry {entry_id} does not exist")


map_error(EntryMissing, 404, "not_found")


@router.get("/{entry_id}")
def get_ledger_entry(entry_id: PathId, user: CurrentUser, engine: EngineDep) -> EntryOut:
    """One entry in the row shape of the list, its `source` included."""
    with engine.connect() as conn:
        row = get_entry(conn, entry_id)
    if row is None:
        raise EntryMissing(entry_id)
    return EntryOut.of(row)
