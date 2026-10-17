"""Uploading a file to a linked account (spec §5.3/§5.4, architecture §4.1 and §5.5).

One run per upload. The checks come first and write nothing; then the run is committed
`running`, the importer parses the bytes OUTSIDE any database transaction, and the delivery is
written by `ingest_delivery` (which settles after its commit). A dry run parses the same way and
then runs the very same write body in a transaction that is rolled back
(`ingest.run.preview_delivery`): no run row, no rows, no settle. A failure the real run would
end in comes back on `UploadResult.failure` together with the importer's report, never raised.

The importer is injected: `core` never imports a plugin.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import Engine, text

from app.core.accounts import AccountMissing
from app.core.domain.errors import ContractViolation, RunRefused
from app.core.importers.instances import InstanceDisabled, InstanceMissing
from app.core.ingest.run import (
    fail_run,
    ingest_delivery,
    preview_delivery,
    run_error_text,
    run_retryable,
    start_run,
)
from app.core.plugins.errors import ImporterError, InvalidProfile, ParseFailed
from app.core.plugins.importer import DryRunReport, FileImporter, ParsedFile
from app.core.settle.settle import SettleResult

log = logging.getLogger(__name__)


class UploadError(Exception):
    """An upload was refused before anything was written; the message states the rule."""


class NotAFileSource(UploadError):
    def __init__(self, instance_id: int) -> None:
        super().__init__(f"importer instance {instance_id} does not emit transactions: no file goes to it")


class AccountClosed(UploadError):
    def __init__(self, account_id: int) -> None:
        super().__init__(f"account {account_id} is closed: reopen it before uploading to it")


class AccountNotLinked(UploadError):
    def __init__(self, instance_id: int, account_id: int) -> None:
        super().__init__(f"account {account_id} is not linked to importer instance {instance_id}")


@dataclass(frozen=True)
class Failure:
    """What a dry run shows when the real run would have ended in an error.

    `kind` is `parse_failed`, `invalid_profile`, `importer_error`, `contract_violation` or, when
    the instance, account or link changed after the checks, the refusal (`instance_disabled`,
    `account_closed`, `account_not_linked`, ...); `rule` names the contract rule
    (e.g. `currency_mismatch`) for a contract violation, else None.
    """

    kind: str
    rule: str | None
    message: str


@dataclass(frozen=True)
class UploadResult:
    """The same shape for a dry run and a real one (architecture §4.1 'Previewed').

    `summary` is the run's stats as stored (inserted, skipped_by_identity, inserted_as_duplicates,
    importer, balance, unexplained_difference, since_zero); empty when `failure` is set.
    """

    run_id: int | None  # None on a dry run
    dry_run: bool
    summary: dict[str, Any]
    report: DryRunReport
    settle: SettleResult | None  # None on a dry run
    failure: Failure | None = None
    importer_stats: Mapping[str, int] = field(default_factory=dict)


def upload(
    engine: Engine,
    *,
    instance_id: int,
    account_id: int,
    data: bytes,
    importer: FileImporter,
    user_id: int | None,
    today: date,
    dry_run: bool = False,
) -> UploadResult:
    """Upload `data` for one account of one file-importer instance."""
    instance_name, label, profile, currency, exponents = _checked(engine, instance_id, account_id)

    run_id: int | None = None
    if not dry_run:
        run_id = start_run(
            engine,
            account_id,
            "transactions",
            importer=instance_name,
            importer_instance_id=instance_id,
            started_by=user_id,
        )
    try:
        parsed = importer.parse(
            data,
            profile,
            account_currency=currency,
            minor_units_of=exponents.__getitem__,
            today=today,
            name=label,
        )
    except (ImporterError, InvalidProfile) as exc:
        if run_id is None:
            return _failed_dry_run(exc)
        _fail(engine, run_id, run_error_text(exc), retryable=run_retryable(exc))
        raise
    except BaseException as exc:  # the run must not stay `running`; no message: it may quote the file
        if run_id is not None:
            _fail(engine, run_id, f"{type(exc).__name__}: the importer failed unexpectedly")
        raise

    if run_id is None:
        return _dry_run(engine, instance_id, instance_name, account_id, parsed)
    try:
        done = ingest_delivery(
            engine,
            run_id,
            parsed.rows,
            reported_balance=parsed.reported_balance,
            reported_balance_on=parsed.balance_on,
            covered_from=parsed.data_start,
            covered_through=parsed.covered_through,
            importer_stats=parsed.importer_stats,
        )
    except RunRefused as refused:  # lost a race after the checks: the same refusal as before
        raise _refusal(refused, instance_id, account_id) from refused
    return UploadResult(
        run_id=run_id,
        dry_run=False,
        summary=dict(done.stats),
        report=parsed.report,
        settle=done.settle,
        importer_stats=done.importer_stats,
    )


def _dry_run(
    engine: Engine, instance_id: int, importer_name: str, account_id: int, parsed: ParsedFile
) -> UploadResult:
    try:
        done = preview_delivery(
            engine,
            account_id=account_id,
            instance_id=instance_id,
            importer=importer_name,
            rows=parsed.rows,
            reported_balance=parsed.reported_balance,
            reported_balance_on=parsed.balance_on,
            covered_from=parsed.data_start,
            covered_through=parsed.covered_through,
            importer_stats=parsed.importer_stats,
        )
    except RunRefused as refused:
        return UploadResult(
            run_id=None,
            dry_run=True,
            summary={},
            report=parsed.report,
            settle=None,
            failure=Failure(refused.reason, None, str(refused)),
        )
    except ContractViolation as exc:
        return UploadResult(
            run_id=None,
            dry_run=True,
            summary={},
            report=parsed.report,
            settle=None,
            failure=Failure("contract_violation", exc.rule, str(exc)),
        )
    return UploadResult(
        run_id=None,
        dry_run=True,
        summary=dict(done.stats),
        report=parsed.report,
        settle=None,
        importer_stats=done.importer_stats,
    )


def _failed_dry_run(exc: ImporterError | InvalidProfile) -> UploadResult:
    if isinstance(exc, ParseFailed):
        kind, report = "parse_failed", exc.report
    elif isinstance(exc, InvalidProfile):
        kind, report = "invalid_profile", None
    else:
        kind, report = "importer_error", None
    return UploadResult(
        run_id=None,
        dry_run=True,
        summary={},
        report=report or DryRunReport.empty(),
        settle=None,
        failure=Failure(kind, None, str(exc)),
    )


def _refusal(refused: RunRefused, instance_id: int, account_id: int) -> Exception:
    """The `UploadError` (or the instance/account error) a refusal inside the write maps onto."""
    match refused.reason:
        case "instance_missing":
            return InstanceMissing(instance_id)
        case "not_a_file_source":
            return NotAFileSource(instance_id)
        case "instance_disabled":
            return InstanceDisabled(instance_id)
        case "account_missing":
            return AccountMissing(account_id)
        case "account_closed":
            return AccountClosed(account_id)
        case "account_not_linked":
            return AccountNotLinked(instance_id, account_id)
    return refused


def _fail(engine: Engine, run_id: int, message: str, *, retryable: bool = False) -> None:
    try:
        fail_run(engine, run_id, message, retryable=retryable)
    except Exception as exc:  # the type only: a database error's message quotes statement content
        log.error("could not mark run %s failed: %s", run_id, type(exc).__name__)


def _checked(
    engine: Engine, instance_id: int, account_id: int
) -> tuple[str, str, dict[str, Any], str, dict[str, int]]:
    """The refusals, then (importer name, instance label, profile, account currency, minor units)."""
    with engine.connect() as conn:
        inst = conn.execute(
            text("SELECT importer, label, emits, disabled, settings FROM importer_instance WHERE id = :i"),
            {"i": instance_id},
        ).one_or_none()
        if inst is None:
            raise InstanceMissing(instance_id)
        if "transactions" not in inst.emits:
            raise NotAFileSource(instance_id)
        if inst.disabled:
            raise InstanceDisabled(instance_id)
        acct = conn.execute(
            text("SELECT currency, closed_on FROM account WHERE id = :i"), {"i": account_id}
        ).one_or_none()
        if acct is None:
            raise AccountMissing(account_id)
        if acct.closed_on is not None:
            raise AccountClosed(account_id)
        linked = conn.execute(
            text("SELECT 1 FROM account_source WHERE account_id = :a AND importer_instance_id = :i"),
            {"a": account_id, "i": instance_id},
        ).first()
        if linked is None:
            raise AccountNotLinked(instance_id, account_id)
        exponents = {
            str(r.code): int(r.minor_units)
            for r in conn.execute(text("SELECT code, minor_units FROM currency"))
        }
        return str(inst.importer), str(inst.label), dict(inst.settings), str(acct.currency), exponents
