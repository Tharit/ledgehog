"""Provenance: what one source transaction said and where it came from (architecture §4.1, spec §3.1).

A read of the bank layer by the source transaction's id. A duplicate, which has no entry, is read the
same way; a user-authored row has no run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import Connection, text

from app.core.balance.statement import DuplicateRef


@dataclass(frozen=True)
class RunRef:
    """The import run a row arrived in."""

    id: int
    importer: str
    instance_id: int | None
    instance_label: str | None  # None once the instance is deleted: the run outlives it
    started_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True)
class Provenance:
    id: int
    account_id: int
    currency: str
    authored: bool  # entered by hand
    source_format: str | None
    booked_on: date
    value_on: date | None
    amount: int
    instructed_amount: int | None
    instructed_currency: str | None
    counterparty_name: str | None
    counterparty_ref: str | None
    counterparty_bic: str | None
    purpose: str | None
    booking_text: str | None
    end_to_end_id: str | None
    mandate_ref: str | None
    raw: Any
    run: RunRef | None
    duplicate_of: DuplicateRef | None
    entry_id: int | None  # the lowest id among its entries; None for a duplicate


def get_provenance(conn: Connection, source_id: int) -> Provenance | None:
    r = conn.execute(
        text(
            "SELECT s.id, s.account_id, s.currency, s.origin = 'user' AS authored, s.source_format,"
            " s.booked_on, s.value_on, s.amount, s.instructed_amount, s.instructed_currency,"
            " s.counterparty_name, s.counterparty_ref, s.counterparty_bic, s.purpose, s.booking_text,"
            " s.end_to_end_id, s.mandate_ref, s.raw,"
            " r.id AS run_id, r.importer AS run_importer, r.importer_instance_id AS instance_id,"
            " i.label AS instance_label, r.started_at, r.finished_at,"
            " o.id AS of_id, o.booked_on AS of_on, o.amount AS of_amount,"
            " (SELECT min(e.id) FROM ledger_entry e WHERE e.source_transaction_id = s.id) AS entry_id"
            " FROM source_transaction s"
            " LEFT JOIN import_run r ON r.id = s.import_run_id"
            " LEFT JOIN importer_instance i ON i.id = r.importer_instance_id"
            " LEFT JOIN source_transaction o ON o.id = s.duplicate_of"
            " WHERE s.id = :i"
        ),
        {"i": source_id},
    ).one_or_none()
    if r is None:
        return None
    return Provenance(
        id=r.id,
        account_id=r.account_id,
        currency=r.currency,
        authored=r.authored,
        source_format=r.source_format,
        booked_on=r.booked_on,
        value_on=r.value_on,
        amount=int(r.amount),
        instructed_amount=None if r.instructed_amount is None else int(r.instructed_amount),
        instructed_currency=r.instructed_currency,
        counterparty_name=r.counterparty_name,
        counterparty_ref=r.counterparty_ref,
        counterparty_bic=r.counterparty_bic,
        purpose=r.purpose,
        booking_text=r.booking_text,
        end_to_end_id=r.end_to_end_id,
        mandate_ref=r.mandate_ref,
        raw=r.raw,
        run=(
            None
            if r.run_id is None
            else RunRef(
                r.run_id, r.run_importer, r.instance_id, r.instance_label, r.started_at, r.finished_at
            )
        ),
        duplicate_of=None if r.of_id is None else DuplicateRef(r.of_id, r.of_on, int(r.of_amount)),
        entry_id=r.entry_id,
    )
