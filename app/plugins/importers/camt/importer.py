"""`CamtImporter`: the file importer for camt bank statements (camt.md).

A pure parse: bytes in, `ParsedFile` out. It has no settings; the reader is chosen by the file's root
element. It never reads the database or the clock; `today` stands in for an export date the file does
not state. A currency mismatch of the entries is not raised here: the rows go out unchanged, ingest's
`ContractViolation` fails the run and the report records the mismatch (camt.md §6).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date
from typing import Any

from app.core.plugins.errors import InvalidProfile, ParseFailed
from app.core.plugins.importer import ParsedFile
from app.core.plugins.report import ReportBuilder
from app.plugins.importers.camt.core import run
from app.plugins.importers.camt.detect import read_statement


class CamtImporter:
    def validate_settings(self, settings: Mapping[str, Any]) -> None:
        if settings:
            raise InvalidProfile(f"{sorted(settings)[0]}: the camt importer has no settings")

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
        self.validate_settings(profile)
        rep = ReportBuilder(limit=dry_run_samples)

        def exponent(currency: str) -> int:
            try:
                return minor_units_of(currency)
            except KeyError:
                raise ParseFailed(f"unknown currency {currency!r}: no minor-unit exponent known") from None

        try:
            return run(read_statement(data), rep, account_currency, exponent, today)
        except ParseFailed as exc:
            if exc.report is not None:
                raise
            raise ParseFailed(str(exc), report=rep.build(failure=str(exc))) from None
