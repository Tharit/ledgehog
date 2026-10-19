"""The bank's return codes to the error taxonomy (fints.md §7).

After every request the codes decide, and the library's own exceptions never do, because they hide the
bank's text. A message carries a code and the bank's text, never the dialog's data, an account number
or anything the user typed (architecture §5.5).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.core.plugins.errors import (
    AuthRejected,
    BankSetupRequired,
    ImporterError,
    ParseFailed,
    SourceUnavailable,
)
from app.plugins.importers.fints.bank import ReturnCode

WRONG_PIN = ("9931", "9942", "9040")
LOCKED = ("9930", "3938")  # 3938 is the library's "account locked", sent as a warning-class code
NOT_ACTIVATED = ("9940", "9960")
MEDIUM_REFUSED = "9210"
CANNOT_READ = ("9110", "9120", "9160")
STRONG_AUTH_REQUIRED = "9075"
NO_ENTRIES = "3010"


def is_error(code: ReturnCode) -> bool:
    return code.code.startswith("9") or code.code in LOCKED


def errors_in(codes: Iterable[ReturnCode]) -> list[ReturnCode]:
    return [c for c in codes if is_error(c)]


def has(codes: Iterable[ReturnCode], *wanted: str) -> bool:
    return any(c.code in wanted for c in codes)


def _first(codes: Sequence[ReturnCode], wanted: Iterable[str]) -> ReturnCode | None:
    kinds = tuple(wanted)
    return next((c for c in codes if c.code in kinds), None)


def _said(code: ReturnCode) -> str:
    return f"{code.code} {code.text}".strip()


def error_for(codes: Sequence[ReturnCode], detail: str | None = None) -> ImporterError:
    """What a dialog that ended on `codes` is. `detail` names the library failure when no code does."""
    errors = errors_in(codes)
    if (hit := _first(errors, WRONG_PIN)) is not None:
        return AuthRejected(
            f"the bank rejected the login name or the PIN ({_said(hit)}). It is not tried again: a bank "
            "locks a login after a few rejected attempts, so check the PIN in the bank's own login first"
        )
    if (hit := _first(errors, LOCKED)) is not None:
        return BankSetupRequired(f"the bank has locked this login ({_said(hit)}): unlock it with the bank")
    if (hit := _first(errors, NOT_ACTIVATED)) is not None:
        return BankSetupRequired(
            f"the bank has no active TAN procedure or device for this login ({_said(hit)}): "
            "finish setup with the bank, then run again"
        )
    if (hit := _first(errors, (MEDIUM_REFUSED,))) is not None:
        return BankSetupRequired(
            f"the bank does not accept the TAN medium name ({_said(hit)}): check the device name "
            "in the bank's own app, then run again"
        )
    if (hit := _first(errors, CANNOT_READ)) is not None:
        return ParseFailed(f"the bank cannot read our message ({_said(hit)})")
    if errors:
        return SourceUnavailable(f"the bank refused the request ({_said(errors[0])})")
    return ParseFailed(f"the bank's answer could not be processed ({detail or 'no reason given'})")
