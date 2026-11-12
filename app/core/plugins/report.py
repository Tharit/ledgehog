"""What a parse collects on the way, for any file importer: the dry-run report builder."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.core.plugins.importer import Category, DryRunReport, Example, MappedColumn, SampleRow


@dataclass(slots=True)
class Counter:
    count: int = 0
    examples: list[Example] = field(default_factory=list)

    def add(self, row: int, reason: str, limit: int) -> None:
        self.count += 1
        if len(self.examples) < limit:
            self.examples.append(Example(row, reason))

    def freeze(self) -> Category:
        return Category(self.count, tuple(self.examples))


@dataclass(slots=True)
class ReportBuilder:
    """Collects what the parse did; `build` is safe at any point, including after a failure."""

    limit: int
    header_line: int | None = None
    encoding: str | None = None
    delimiter: str | None = None
    columns: list[MappedColumn] = field(default_factory=list)
    rows_read: int = 0
    emitted: int = 0
    skipped: Counter = field(default_factory=Counter)
    filtered: Counter = field(default_factory=Counter)
    zero_dropped: Counter = field(default_factory=Counter)
    currency_mismatch: Counter = field(default_factory=Counter)
    sample: list[SampleRow] = field(default_factory=list)
    coverage: date | None = None
    coverage_source: str | None = None
    export_date: date | None = None
    export_date_source: str | None = None
    balance: Any = None
    synthetic: Any = None
    warnings: list[str] = field(default_factory=list)
    format: str | None = None

    def build(self, failure: str | None = None) -> DryRunReport:
        return DryRunReport(
            header_line=self.header_line,
            encoding=self.encoding,
            delimiter=self.delimiter,
            columns=tuple(self.columns),
            rows_read=self.rows_read,
            emitted=self.emitted,
            skipped=self.skipped.freeze(),
            filtered=self.filtered.freeze(),
            zero_dropped=self.zero_dropped.freeze(),
            currency_mismatch=self.currency_mismatch.freeze(),
            sample=tuple(self.sample),
            coverage=self.coverage,
            coverage_source=self.coverage_source,
            export_date=self.export_date,
            export_date_source=self.export_date_source,
            balance=self.balance,
            synthetic=self.synthetic,
            warnings=tuple(self.warnings),
            failure=failure,
            format=self.format,
        )
