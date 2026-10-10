"""The importer error taxonomy (architecture §5.5).

Errors are exception classes because the queue's behaviour depends on `retryable`.
`ContractViolation` (the importer delivered what its contract forbids) is raised by ingest
and lives in `app.core.domain.errors`; it is not retryable either.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.plugins.importer import DryRunReport


class ImporterError(Exception):
    """Base of the importer failures; `retryable` says whether the queue may try again."""

    retryable: bool = False


class AuthRejected(ImporterError):
    """Wrong PIN or password. Retryable only after the user corrects it."""

    retryable = True


class ChallengeExpired(ImporterError):
    """A TAN timed out; retry the instance."""

    retryable = True


class ChallengeAbandoned(ImporterError):
    """The user cancelled."""

    retryable = True


class SourceUnavailable(ImporterError):
    """The bank is unreachable or timed out."""

    retryable = True


class ParseFailed(ImporterError):
    """The format changed or the profile does not fit; needs a code or profile fix.

    `report` is the dry-run report up to the failure, so the caller can show what was read.
    """

    retryable = False

    def __init__(self, message: str, *, report: DryRunReport | None = None) -> None:
        super().__init__(message)
        self.report = report


class NotRegistered(ImporterError):
    """FinTS product registration is missing (spec §7.1)."""

    retryable = False


class InvalidProfile(ValueError):
    """An importer setting is invalid; the message names the setting."""
