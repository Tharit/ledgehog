"""User-authored source transactions: the entry form (architecture §4.1, spec §3.9, §5.6).

`POST /api/ledger/sources` enters a movement, `PUT /{id}` edits its amount, date or purpose,
`DELETE /{id}` removes it with its entries. Edit and delete take `dry_run` (a preview that writes
nothing) and carry `expected_versions` (entry id -> the version the client saw). Every real write
settles after it commits and answers with the rows it touched (architecture §4.1 'Operations return
everything they touched'): `entries` in the row shape of the list, `units` and `settle`, whose
`error` is a notice, never an HTTP error.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictInt, StringConstraints

from app.api.errors import ApiError, map_error
from app.api.ids import MAX_ID, EntityId, EntityVersion, PathId
from app.api.routers.entries import EntryOut
from app.api.routers.maintenance import SettleOut
from app.api.routers.units import UnitStateOut
from app.api.session import CurrentUser, EngineDep
from app.core.domain.errors import VersionConflict
from app.core.ledger.sources import (
    MAX_PURPOSE,
    AccountSynced,
    Created,
    Deleted,
    Edited,
    EditEffects,
    EmptyEdit,
    NotUserAuthored,
    SourceIdTaken,
    SourceMissing,
    Units,
    create_source,
    delete_source,
    update_source,
)
from app.core.units.read import UnitView
from app.utils.db.locks import WriteConflict

router = APIRouter(prefix="/api/ledger/sources", tags=["sources"])

map_error(SourceMissing, 404, "not_found")
map_error(AccountSynced, 422, "account_synced")
map_error(NotUserAuthored, 422, "not_user_authored")
map_error(EmptyEdit, 422, "validation_error")
map_error(SourceIdTaken, 409, "conflict", details=lambda e: {"reason": "id_taken"})
map_error(VersionConflict, 409, "conflict", details=lambda exc: {"entry_ids": list(exc.entry_ids)})
map_error(WriteConflict, 409, "try_again")


# a money amount in signed minor units, in the ledger sign convention (an expense is negative); never zero
def _non_zero(value: int) -> int:
    if value == 0:
        raise ValueError("an amount is never zero")
    return value


Amount = Annotated[StrictInt, Field(ge=-MAX_ID, le=MAX_ID), AfterValidator(_non_zero)]
Purpose = Annotated[str, StringConstraints(max_length=MAX_PURPOSE)]
ClientId = Annotated[str, StringConstraints(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")]
Versions = dict[EntityId, EntityVersion]


class SourceCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: ClientId  # random, made by the form before it submits: a repeated submission is a no-op
    account_id: EntityId
    amount: Amount
    booked_on: date
    purpose: Purpose | None = None  # trimmed; blank means none


class SourceUpdateBody(BaseModel):
    """Absent fields stay; `purpose: null` or blank clears it. Never the account (422)."""

    model_config = ConfigDict(extra="forbid")

    amount: Amount | None = None
    booked_on: date | None = None
    purpose: Purpose | None = None
    expected_versions: Versions = {}
    dry_run: bool = False


class UnitRefOut(BaseModel):
    anchor_entry_id: int  # what opens the unit in the panel
    entry_ids: list[int]
    state: UnitStateOut

    @staticmethod
    def of(view: UnitView) -> UnitRefOut:
        return UnitRefOut(
            anchor_entry_id=view.anchor_entry_id,
            entry_ids=[e.id for e in view.entries],
            state=UnitStateOut.of(view.state),
        )


class EntryVersionOut(BaseModel):
    entry_id: int
    version: int


def _units(units: Units) -> list[UnitRefOut]:
    return [UnitRefOut.of(v) for v in units.views]


def _entries(units: Units) -> list[EntryOut]:
    return [EntryOut.of(e) for e in units.entries]


class SourceWriteOut(BaseModel):
    source_transaction_id: int
    anchor_entry_id: int | None  # the unit of the row: the panel opens on it
    entries: list[EntryOut]  # the rows of every unit concerned, ascending
    units: list[UnitRefOut]  # the row's unit first
    removed_entry_ids: list[int]
    settle: SettleOut

    @staticmethod
    def of_created(done: Created) -> SourceWriteOut:
        return SourceWriteOut(
            source_transaction_id=done.source_id,
            anchor_entry_id=done.units.views[0].anchor_entry_id if done.units.views else None,
            entries=_entries(done.units),
            units=_units(done.units),
            removed_entry_ids=[],
            settle=SettleOut.of(done.settle),
        )


class EditEffectsOut(BaseModel):
    collapsed_entry_ids: list[int]  # split entries deleted, the original takes the whole amount
    unpaired_entry_ids: list[int]  # surviving entries that lost their counterpart, partners included
    deleted_entry_ids: list[int]  # every entry the edit removes
    rederived_entry_ids: list[int]  # entries whose values or keys are derived again
    returned_to_review_ids: list[int]  # confirmed before the edit, not confirmed after it
    followed_entry_ids: list[int]  # partners that took the negated new amount and stay paired (spec §5.7)
    versions: list[EntryVersionOut]  # what a real run must carry in `expected_versions`

    @staticmethod
    def of(e: EditEffects) -> EditEffectsOut:
        return EditEffectsOut(
            collapsed_entry_ids=list(e.collapsed_entry_ids),
            unpaired_entry_ids=list(e.unpaired_entry_ids),
            deleted_entry_ids=list(e.deleted_entry_ids),
            rederived_entry_ids=list(e.rederived_entry_ids),
            returned_to_review_ids=list(e.returned_to_review_ids),
            followed_entry_ids=list(e.followed_entry_ids),
            versions=[EntryVersionOut(entry_id=i, version=v) for i, v in e.versions],
        )


class SourceEditOut(BaseModel):
    dry_run: bool
    source_transaction_id: int
    effects: EditEffectsOut  # what the edit does (a dry run: what it would do)
    anchor_entry_id: int | None  # real run only
    entries: list[EntryOut]  # real run only: the rows of every unit concerned
    units: list[UnitRefOut]  # real run only
    removed_entry_ids: list[int]
    settle: SettleOut | None  # null on a dry run

    @staticmethod
    def of(done: Edited) -> SourceEditOut:
        return SourceEditOut(
            dry_run=done.dry_run,
            source_transaction_id=done.source_id,
            effects=EditEffectsOut.of(done.effects),
            anchor_entry_id=done.units.views[0].anchor_entry_id if done.units.views else None,
            entries=_entries(done.units),
            units=_units(done.units),
            removed_entry_ids=[] if done.dry_run else list(done.effects.deleted_entry_ids),
            settle=None if done.settle is None else SettleOut.of(done.settle),
        )


class DeleteCountsOut(BaseModel):
    entries: int
    confirmed_entries: int  # removed entries whose unit was confirmed
    tagged_entries: int
    tag_memberships: int
    partners_returning_to_review: int


class SourceDeleteOut(BaseModel):
    dry_run: bool
    source_transaction_id: int
    counts: DeleteCountsOut
    removed: list[EntryOut]  # the entries as they stood, with their versions and tags
    removed_entry_ids: list[int]
    partners: list[EntryOut]  # the partners left behind; a dry run: as they stand (their versions)
    units: list[UnitRefOut]  # real run only: the units of the partners
    settle: SettleOut | None

    @staticmethod
    def of(done: Deleted) -> SourceDeleteOut:
        return SourceDeleteOut(
            dry_run=done.dry_run,
            source_transaction_id=done.source_id,
            counts=DeleteCountsOut(**vars(done.counts)),
            removed=[EntryOut.of(e) for e in done.removed],
            removed_entry_ids=[e.id for e in done.removed],
            partners=[EntryOut.of(e) for e in done.partners],
            units=_units(done.units),
            settle=None if done.settle is None else SettleOut.of(done.settle),
        )


@router.post("", status_code=201, responses={200: {"model": SourceWriteOut}})
def create_ledger_source(
    body: SourceCreateBody, response: Response, user: CurrentUser, engine: EngineDep
) -> SourceWriteOut:
    """Enter a movement on an unsynced account. A repeated `id` returns the row already entered (200)."""
    done = create_source(
        engine,
        client_id=body.id,
        account_id=body.account_id,
        amount=body.amount,
        booked_on=body.booked_on,
        purpose=body.purpose,
    )
    if not done.created:
        response.status_code = 200
    return SourceWriteOut.of_created(done)


@router.put("/{source_id}")
def update_ledger_source(
    source_id: PathId, body: SourceUpdateBody, user: CurrentUser, engine: EngineDep
) -> SourceEditOut:
    """Edit a user-authored row's amount, date or purpose; the entries follow (spec §5.6).

    `dry_run` reports what the edit would collapse, unpair and derive again, and writes nothing. A real
    run carries `expected_versions` for the row's entries and the partners it unpairs.
    """
    fields: dict[str, Any] = {}
    if "purpose" in body.model_fields_set:
        fields["purpose"] = body.purpose
    done = update_source(
        engine,
        source_id,
        amount=body.amount,
        booked_on=body.booked_on,
        expected_versions=body.expected_versions,
        dry_run=body.dry_run,
        **fields,
    )
    return SourceEditOut.of(done)


def _parse_versions(raw: list[str] | None) -> dict[int, int] | None:
    if raw is None:
        return None
    out: dict[int, int] = {}
    for item in raw:
        entry, sep, version = item.partition(":")
        try:
            e, v = int(entry), int(version)
            if not sep or not 0 < e <= MAX_ID or not 0 < v <= 2**31 - 1:
                raise ValueError(item)
        except ValueError as exc:
            raise ApiError(
                422,
                "validation_error",
                "The request is not valid.",
                [
                    {
                        "location": ["query", "expected_versions"],
                        "message": "each value is `entry_id:version`, two positive integers",
                        "type": "invalid_versions",
                    }
                ],
            ) from exc
        out[e] = v
    return out


@router.delete("/{source_id}")
def delete_ledger_source(
    source_id: PathId,
    user: CurrentUser,
    engine: EngineDep,
    dry_run: bool = False,
    expected_versions: Annotated[
        list[str] | None,
        Query(description="Repeatable `entry_id:version`: the row's entries and their partners."),
    ] = None,
) -> SourceDeleteOut:
    """Delete a user-authored row and its entries (the removal routine). `dry_run` reports what goes."""
    done = delete_source(
        engine, source_id, expected_versions=_parse_versions(expected_versions), dry_run=dry_run
    )
    return SourceDeleteOut.of(done)
