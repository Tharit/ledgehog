"""The importer error taxonomy (architecture §5.5).

Errors are exception classes because the queue's behaviour depends on two attributes:
`retryable` (whether running it again can help) and `scope` (what the failure ends: the run, or
the instance whose remaining runs then fail with it, architecture §5.3). `code` is the machine name
the events and the API use.

`ContractViolation` (the importer delivered what its contract forbids) is raised by ingest and
lives in `app.core.domain.errors`; it is not retryable and ends its run only. `error_code` and
`scope_of` read all of it, taxonomy and ingest errors alike.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from app.core.domain.errors import ContractViolation, RunRefused

if TYPE_CHECKING:
    from app.core.plugins.importer import DryRunReport

Scope = Literal["item", "instance"]


class ImporterError(Exception):
    """Base of the importer failures; `retryable` says whether the queue may try again.

    A failure of an unnamed class ends its run only (`scope` item): the least destructive reading.
    """

    retryable: bool = False
    scope: Scope = "item"
    code: str = "importer_error"


class AuthRejected(ImporterError):
    """Wrong PIN or password. Retryable: every run asks for the PIN afresh."""

    retryable = True
    scope = "instance"
    code = "auth_rejected"


class ChallengeExpired(ImporterError):
    """A TAN timed out; retry the instance."""

    retryable = True
    scope = "instance"
    code = "challenge_expired"


class ChallengeAbandoned(ImporterError):
    """The user cancelled, or the sync was aborted."""

    retryable = True
    scope = "instance"
    code = "challenge_abandoned"


class SourceUnavailable(ImporterError):
    """The bank is unreachable or timed out."""

    retryable = True
    scope = "instance"
    code = "source_unavailable"


class ParseFailed(ImporterError):
    """The format changed or the profile does not fit; needs a code or profile fix.

    `report` is the dry-run report up to the failure, so the caller can show what was read.
    """

    retryable = False
    scope = "item"
    code = "parse_failed"

    def __init__(self, message: str, *, report: DryRunReport | None = None) -> None:
        super().__init__(message)
        self.report = report


class NotRegistered(ImporterError):
    """FinTS product registration is missing (spec §7.1)."""

    retryable = False
    scope = "instance"
    code = "not_registered"


class BankSetupRequired(ImporterError):
    """The bank has not activated what a sync needs (no active TAN procedure or device): the user
    finishes setup with the bank, then runs again."""

    retryable = False
    scope = "instance"
    code = "bank_setup_required"


class AccountUnsupported(ImporterError):
    """The bank offers no booking retrieval for this account."""

    retryable = False
    scope = "item"
    code = "account_unsupported"


class InvalidProfile(ValueError):
    """An importer setting is invalid; the message names the setting."""


def error_code(exc: BaseException) -> str:
    """The code an event and the API give a failure: the taxonomy's, `contract_violation`,
    `invalid_profile`, a refusal's own reason, else `unexpected`."""
    if isinstance(exc, ImporterError):
        return exc.code
    if isinstance(exc, ContractViolation):
        return "contract_violation"
    if isinstance(exc, InvalidProfile):
        return "invalid_profile"
    if isinstance(exc, RunRefused):
        return exc.reason
    return "unexpected"


def scope_of(exc: BaseException) -> Scope:
    """What a failure ends. Only the importer classes that name the sign-in or the bank end the
    instance; a contract violation, a refusal and anything unexpected end their run."""
    return exc.scope if isinstance(exc, ImporterError) else "item"
