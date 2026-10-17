"""The importer error taxonomy (architecture §5.5)."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.plugins import errors
from app.core.plugins.importer import DryRunReport, FileImporter, ParsedFile


@pytest.mark.parametrize(
    ("name", "retryable", "scope", "code"),
    [
        ("AuthRejected", True, "instance", "auth_rejected"),  # every run asks for the PIN afresh
        ("ChallengeExpired", True, "instance", "challenge_expired"),
        ("ChallengeAbandoned", True, "instance", "challenge_abandoned"),
        ("SourceUnavailable", True, "instance", "source_unavailable"),
        ("ParseFailed", False, "item", "parse_failed"),
        ("NotRegistered", False, "instance", "not_registered"),
        ("BankSetupRequired", False, "instance", "bank_setup_required"),
        ("AccountUnsupported", False, "item", "account_unsupported"),
    ],
)
def test_retryable_scope_and_code_per_table(name: str, retryable: bool, scope: str, code: str) -> None:
    cls = getattr(errors, name)
    assert issubclass(cls, errors.ImporterError)
    assert (cls.retryable, cls.scope, cls.code) == (retryable, scope, code)
    assert cls("x").retryable is retryable


def test_error_code_and_scope_read_ingest_errors_too() -> None:
    from app.core.domain.errors import ContractViolation, RunRefused

    cv = ContractViolation("zero_amount", "row 0")
    assert (errors.error_code(cv), errors.scope_of(cv)) == ("contract_violation", "item")
    refused = RunRefused("account_closed", "closed")
    assert (errors.error_code(refused), errors.scope_of(refused)) == ("account_closed", "item")
    assert (errors.error_code(errors.InvalidProfile("x")), errors.scope_of(errors.InvalidProfile("x"))) == (
        "invalid_profile",
        "item",
    )
    assert errors.error_code(RuntimeError("x")) == "unexpected"
    assert errors.scope_of(RuntimeError("x")) == "item"
    assert errors.error_code(errors.AuthRejected("x")) == "auth_rejected"


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
