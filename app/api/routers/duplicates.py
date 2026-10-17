"""Provenance, and marking or clearing a duplicate (architecture §4.1, spec §3.1, §5.6).

`GET /api/ledger/sources/{id}` reads one source transaction: the normalised columns, `raw`, the run it
arrived in and `duplicate_of`. `POST …/duplicate` marks an imported row as a duplicate of another row on
its account and `POST …/not-duplicate` clears one marked wrongly. Marking is the previewed operation:
`dry_run` returns what it would remove, unpair and repoint and the version of every entry it writes, which
the confirming request sends back as `expected_versions`. Both answer with everything they touched
(architecture §4.1 'Operations return everything they touched').
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine, text

from app.api.errors import map_error
from app.api.ids import EntityId, EntityVersion, PathId
from app.api.routers.accounts import Money
from app.api.routers.entries import EntryOut
from app.api.routers.maintenance import SettleOut
from app.api.routers.sources import EntryVersionOut, SourceWriteOut, UnitRefOut
from app.api.routers.statement import DuplicateOfOut
from app.api.session import CurrentUser, EngineDep
from app.core.domain.errors import (
    AlreadyDuplicate,
    DuplicateChain,
    DuplicateCrossAccount,
    DuplicateError,
    DuplicateOfSelf,
    DuplicateRowMissing,
    NotADuplicate,
    UserAuthoredRow,
    VersionConflict,
)
from app.core.ingest.duplicates import clear_duplicate, mark_duplicate
from app.core.ledger.entries import entries_by_ids
from app.core.ledger.provenance import Provenance, get_provenance
from app.core.ledger.sources import SourceMissing
from app.core.units.read import get_unit
from app.utils.db.locks import WriteConflict

router = APIRouter(prefix="/api/ledger/sources", tags=["sources"])

map_error(SourceMissing, 404, "not_found")
map_error(DuplicateRowMissing, 404, "not_found")
# the request names rows that cannot stand in this relation: input, not state
map_error(DuplicateOfSelf, 422, "invalid_duplicate", details=lambda e: {"reason": "of_self"})
map_error(DuplicateCrossAccount, 422, "invalid_duplicate", details=lambda e: {"reason": "cross_account"})
map_error(UserAuthoredRow, 422, "invalid_duplicate", details=lambda e: {"reason": "user_authored"})
# the rows are as they are: a state conflict
map_error(AlreadyDuplicate, 409, "conflict", details=lambda e: {"reason": "already_duplicate"})
map_error(DuplicateChain, 409, "conflict", details=lambda e: {"reason": "duplicate_chain"})
map_error(NotADuplicate, 409, "conflict", details=lambda e: {"reason": "not_a_duplicate"})
map_error(DuplicateError, 409, "conflict")
map_error(VersionConflict, 409, "conflict", details=lambda exc: {"entry_ids": list(exc.entry_ids)})
map_error(WriteConflict, 409, "try_again")


# ---- provenance ------------------------------------------------------------------------------


class RunRefOut(BaseModel):
    id: int
    importer: str
    instance_id: int | None
    instance_label: str | None  # null once the instance is deleted
    started_at: datetime
    finished_at: datetime | None


class ProvenanceOut(BaseModel):
    id: int
    account_id: int
    authored: bool  # entered by hand: no run, no raw source
    source_format: str | None
    booked_on: date
    value_on: date | None
    amount: Money
    instructed_amount: Money | None
    counterparty_name: str | None
    counterparty_ref: str | None
    counterparty_bic: str | None
    purpose: str | None
    booking_text: str | None
    end_to_end_id: str | None
    mandate_ref: str | None
    raw: Any  # what the source said, for the importer's widget (for an authored row: what the form submitted)
    run: RunRefOut | None
    duplicate_of: DuplicateOfOut | None
    entry_id: int | None  # opens the row's unit in review; null for a duplicate

    @staticmethod
    def of(p: Provenance) -> ProvenanceOut:
        def money(value: int, currency: str) -> Money:
            return Money(amount=value, currency=currency)

        dup = p.duplicate_of
        return ProvenanceOut(
            id=p.id,
            account_id=p.account_id,
            authored=p.authored,
            source_format=p.source_format,
            booked_on=p.booked_on,
            value_on=p.value_on,
            amount=money(p.amount, p.currency),
            instructed_amount=(
                None
                if p.instructed_amount is None or p.instructed_currency is None
                else money(p.instructed_amount, p.instructed_currency)
            ),
            counterparty_name=p.counterparty_name,
            counterparty_ref=p.counterparty_ref,
            counterparty_bic=p.counterparty_bic,
            purpose=p.purpose,
            booking_text=p.booking_text,
            end_to_end_id=p.end_to_end_id,
            mandate_ref=p.mandate_ref,
            raw=p.raw,
            run=None if p.run is None else RunRefOut(**vars(p.run)),
            duplicate_of=(
                None
                if dup is None
                else DuplicateOfOut(id=dup.id, booked_on=dup.booked_on, amount=money(dup.amount, p.currency))
            ),
            entry_id=p.entry_id,
        )


@router.get("/{source_id}")
def get_source(source_id: PathId, user: CurrentUser, engine: EngineDep) -> ProvenanceOut:
    """One source transaction by its id: provenance, a duplicate included. Read-only."""
    with engine.connect() as conn:
        found = get_provenance(conn, source_id)
    if found is None:
        raise SourceMissing(source_id)
    return ProvenanceOut.of(found)


# ---- marking and clearing --------------------------------------------------------------------


class DuplicateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    of: EntityId  # the row on the same account it duplicates
    dry_run: bool = False
    expected_versions: dict[EntityId, EntityVersion] | None = None


class AccountDerivedOut(BaseModel):
    type: str
    booked_on: date
    amount: Money


class DerivedChangeOut(BaseModel):
    account_id: int
    before: list[AccountDerivedOut]
    after: list[AccountDerivedOut]


class MarkDuplicateOut(BaseModel):
    dry_run: bool
    source_transaction_id: int
    of: int
    removed_entry_ids: list[int]  # the row's entries, gone through the removal routine
    partner_entry_ids: list[int]  # their transfer partners, unpaired and back in review
    freed_document_ids: list[int]
    repointed_source_ids: list[int]  # rows that duplicated this one, now duplicating `of`
    derived_changes: list[DerivedChangeOut]  # accounts whose opening, reconciliations or valuations moved
    versions: list[EntryVersionOut]  # what a real run must carry in `expected_versions`
    partners: list[EntryOut]  # the partners as they stand now (after settling on a real run)
    units: list[UnitRefOut]  # real run only: the units of the partners
    settle: SettleOut | None  # null on a dry run


def _currencies(engine: Engine, account_ids: list[int]) -> dict[int, str]:
    with engine.connect() as conn:
        return {
            int(r.id): str(r.currency)
            for r in conn.execute(
                text("SELECT id, currency FROM account WHERE id = ANY(:ids)"), {"ids": account_ids}
            )
        }


def _unit_refs(engine: Engine, entry_ids: list[int]) -> list[UnitRefOut]:
    seen: dict[int, UnitRefOut] = {}
    with engine.connect() as conn:
        for entry_id in entry_ids:
            view = get_unit(conn, entry_id)
            if view is not None and view.anchor_entry_id not in seen:
                seen[view.anchor_entry_id] = UnitRefOut.of(view)
    return list(seen.values())


@router.post("/{source_id}/duplicate")
def mark_source_duplicate(
    source_id: PathId, body: DuplicateBody, user: CurrentUser, engine: EngineDep
) -> MarkDuplicateOut:
    """Mark an imported row as a duplicate of another row on its account (spec §5.6).

    `dry_run` reports what would go and the versions to carry; a real run carries `expected_versions`.
    The client previews both directions with a second call, the roles swapped.
    """
    done = mark_duplicate(
        engine, source_id, body.of, expected_versions=body.expected_versions, dry_run=body.dry_run
    )
    partner_ids = list(done.affected.partner_entry_ids)
    with engine.connect() as conn:
        partners = entries_by_ids(conn, partner_ids)
    accounts = sorted({c.account_id for c in done.derived_changes})
    currency = _currencies(engine, accounts)

    def derived(rows: tuple[Any, ...], account: int) -> list[AccountDerivedOut]:
        return [
            AccountDerivedOut(
                type=r.type, booked_on=r.booked_on, amount=Money(amount=r.amount, currency=currency[account])
            )
            for r in rows
        ]

    return MarkDuplicateOut(
        dry_run=body.dry_run,
        source_transaction_id=source_id,
        of=body.of,
        removed_entry_ids=list(done.affected.removed_entry_ids),
        partner_entry_ids=partner_ids,
        freed_document_ids=list(done.affected.freed_document_ids),
        repointed_source_ids=list(done.repointed_source_ids),
        derived_changes=[
            DerivedChangeOut(
                account_id=c.account_id,
                before=derived(c.before, c.account_id),
                after=derived(c.after, c.account_id),
            )
            for c in done.derived_changes
        ],
        versions=[EntryVersionOut(entry_id=i, version=v) for i, v in sorted(done.versions.items())],
        partners=[EntryOut.of(e) for e in partners],
        units=[] if body.dry_run else _unit_refs(engine, partner_ids),
        settle=None if done.settle is None else SettleOut.of(done.settle),
    )


@router.post("/{source_id}/not-duplicate")
def clear_source_duplicate(source_id: PathId, user: CurrentUser, engine: EngineDep) -> SourceWriteOut:
    """Clear a row marked wrongly: it gets one new entry (spec §5.6). Answers as the entry form's writes do."""  # noqa: E501
    done = clear_duplicate(engine, source_id)
    assert done.created_entry_id is not None and done.settle is not None
    with engine.connect() as conn:
        view = get_unit(conn, done.created_entry_id)
    return SourceWriteOut(
        source_transaction_id=source_id,
        anchor_entry_id=None if view is None else view.anchor_entry_id,
        entries=[] if view is None else [EntryOut.of(e) for e in sorted(view.entries, key=lambda e: e.id)],
        units=[] if view is None else [UnitRefOut.of(view)],
        removed_entry_ids=[],
        settle=SettleOut.of(done.settle),
    )
