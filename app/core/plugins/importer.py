"""Importer-facing record types (architecture §5.5, spec §5.1).

The record type ingest consumes, and the file-importer protocol with its result and
dry-run report (architecture §5.5). Importers never dedup or hash: they emit
`IncomingRow`s and ingest derives identity from them (spec §5.2).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class IncomingRow:
    """One final, booked transaction record in ledger sign convention.

    Field names follow `source_transaction`. `amount_minor` is signed integer
    minor units and never zero: the importer drops zero
    bookings and reports their count (`filtered`); ingest fails the run on one (`zero_amount`).
    """

    amount_minor: int
    currency: str
    booked_on: date
    source_format: str
    raw: Any
    value_on: date | None = None
    instructed_amount_minor: int | None = None
    instructed_currency: str | None = None
    counterparty_ref: str | None = None
    counterparty_bic: str | None = None
    counterparty_name: str | None = None
    purpose: str | None = None
    end_to_end_id: str | None = None
    mandate_ref: str | None = None
    booking_text: str | None = None
    # The id the SOURCE assigns, None when it does not (spec §5.2).
    source_id: str | None = None


@dataclass(frozen=True, slots=True)
class Example:
    """One row picked out for the report: its line number and why. Never cell content."""

    row: int
    reason: str


@dataclass(frozen=True, slots=True)
class Category:
    """A count with up to N examples."""

    count: int = 0
    examples: tuple[Example, ...] = ()


@dataclass(frozen=True, slots=True)
class MappedColumn:
    field: str
    name: str
    index: int


@dataclass(frozen=True, slots=True)
class SampleRow:
    """A parsed row: cells AFTER the header only, each truncated for display."""

    row: int
    booked_on: date
    amount_minor: int
    cells: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BalanceReport:
    """The balance record that would be written and how it was found."""

    amount_minor: int
    dated_on: date
    source: str
    figure_minor: int
    figure_on: date
    rolled_back_by_minor: int = 0
    rolled_back_rows: int = 0


@dataclass(frozen=True, slots=True)
class SyntheticReport:
    amount_minor: int
    booked_on: date
    row_count: int
    sum_minor: int


@dataclass(frozen=True, slots=True)
class DryRunReport:
    """What a parse did, safe to show: counts, mapped columns, examples, never the preamble."""

    header_line: int | None = None
    encoding: str | None = None
    delimiter: str | None = None
    columns: tuple[MappedColumn, ...] = ()
    rows_read: int = 0
    emitted: int = 0
    skipped: Category = field(default_factory=Category)
    filtered: Category = field(default_factory=Category)
    zero_dropped: Category = field(default_factory=Category)
    currency_mismatch: Category = field(default_factory=Category)
    sample: tuple[SampleRow, ...] = ()
    coverage: date | None = None
    coverage_source: str | None = None
    export_date: date | None = None
    export_date_source: str | None = None
    balance: BalanceReport | None = None
    synthetic: SyntheticReport | None = None
    warnings: tuple[str, ...] = ()
    failure: str | None = None

    @classmethod
    def empty(cls) -> DryRunReport:
        return cls()


@dataclass(frozen=True, slots=True)
class ParsedFile:
    """A file importer's result (architecture §5.5).

    `importer_stats` holds named integers the run's statistics store: `filtered` (zero
    bookings dropped, only those) and `synthetic_skipped`.
    """

    rows: tuple[IncomingRow, ...]
    reported_balance: int | None
    balance_on: date | None
    covered_through: date
    data_start: date | None
    importer_stats: Mapping[str, int]
    report: DryRunReport


@runtime_checkable
class FileImporter(Protocol):
    """A pure parse of uploaded bytes. Reads neither the database nor the clock."""

    def validate_settings(self, settings: Mapping[str, Any]) -> None:
        """Raise `InvalidProfile` naming the setting that is wrong."""
        ...

    def parse(
        self,
        data: bytes,
        profile: Mapping[str, Any],
        *,
        account_currency: str,
        minor_units_of: Callable[[str], int],
        today: date,
        name: str,
        dry_run_samples: int = 5,
    ) -> ParsedFile:
        """Raise `ParseFailed` (carrying the report) for any problem on the importer's side.

        `name` is the instance's label at the time of the run, which an importer may put in the
        `source_format` of its rows (the CSV importer's `csv:<label>`).

        `minor_units_of` maps a currency code to its minor-unit exponent (the caller supplies it
        from the `currency` table); it raises `KeyError` for a code it does not know, which the
        importer reports as `ParseFailed`. It serves the account's amounts and any other
        currency an amount is stated in (an instructed amount).
        """
        ...


@dataclass(frozen=True, slots=True)
class IncomingDocumentLine:
    """One line of a document. `amount_minor` is signed like the document's total (a charge's lines
    are negative, spec §5.5)."""

    description: str
    amount_minor: int
    qty: int | None = None


@dataclass(frozen=True, slots=True)
class IncomingDocument:
    """One document (spec §5.5), keyed on `(provider, external_id)`. `total_minor` is signed integer
    minor units of `currency`, negative for a charge, and never zero."""

    provider: str
    external_id: str
    occurred_on: date
    total_minor: int
    currency: str
    raw: Any
    merchant_name: str | None = None
    title: str | None = None
    lines: tuple[IncomingDocumentLine, ...] = ()


@dataclass(frozen=True, slots=True)
class DocumentDelivery:
    """A document importer's result. `covered_through` is the date up to which the provider's
    documents are known complete, in its own dates (spec §5.5); `covered_from` where the data starts."""

    documents: tuple[IncomingDocument, ...]
    covered_through: date
    covered_from: date | None = None
