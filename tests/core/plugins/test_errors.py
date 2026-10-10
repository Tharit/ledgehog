"""The importer error taxonomy (architecture §5.5)."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.plugins import errors
from app.core.plugins.importer import DryRunReport, FileImporter, ParsedFile


@pytest.mark.parametrize(
    ("name", "retryable"),
    [
        ("AuthRejected", True),  # after the user corrects the credentials
        ("ChallengeExpired", True),
        ("ChallengeAbandoned", True),
        ("SourceUnavailable", True),
        ("ParseFailed", False),
        ("NotRegistered", False),
    ],
)
def test_retryable_flag_per_table(name: str, retryable: bool) -> None:
    cls = getattr(errors, name)
    assert issubclass(cls, errors.ImporterError)
    assert cls.retryable is retryable
    assert cls("x").retryable is retryable


def test_parse_failed_carries_the_report() -> None:
    report = DryRunReport.empty()
    exc = errors.ParseFailed("no header row", report=report)
    assert exc.report is report
    assert str(exc) == "no header row"
    assert errors.ParseFailed("x").report is None


def test_invalid_profile_is_a_value_error_not_an_importer_error() -> None:
    assert issubclass(errors.InvalidProfile, ValueError)
    assert not issubclass(errors.InvalidProfile, errors.ImporterError)


def test_parsed_file_is_frozen_and_holds_the_result() -> None:
    pf = ParsedFile(
        rows=(),
        reported_balance=None,
        balance_on=None,
        covered_through=date(2026, 1, 1),
        data_start=None,
        importer_stats={"filtered": 0, "synthetic_skipped": 0},
        report=DryRunReport.empty(),
    )
    with pytest.raises(AttributeError):
        pf.rows = ()  # type: ignore[misc]
    assert FileImporter is not None
