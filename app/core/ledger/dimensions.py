"""What categories and payees share (spec §3.5, §3.6, architecture §4.1 'Management writes').

Value cleaning, the errors both raise, and the one transaction shape of a previewed write:
settle lock shared, the work, then commit, or rollback for a dry run. A real merge carries the
`expected_count` its dry run reported; a moved number rolls everything back.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import Connection, Engine

from app.core.ledger.tags import FilterResultChanged
from app.utils.db.locks import lock_settle_shared

MAX_NAME = 200
MAX_PRESENTATION = 64  # an icon or colour name


class DimensionError(Exception):
    """A category or payee operation was refused; the message states the rule. Nothing was written."""


class InvalidValue(DimensionError):
    """`parameter` names the body field at fault."""

    def __init__(self, parameter: str, message: str) -> None:
        self.parameter = parameter
        super().__init__(message)


class DuplicateName(DimensionError):
    def __init__(self, entity: str) -> None:
        super().__init__(f"another {entity} already has this name (names are compared case-insensitively)")


class ExpectedCountRequired(DimensionError):
    """A real merge must carry the entry count its dry run reported."""

    def __init__(self) -> None:
        super().__init__("a merge needs `expected_count`, the entry count its dry run reported")


class MergeCountChanged(FilterResultChanged):
    """The merge now repoints another number of entries than the preview showed."""

    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(expected, actual)
        self.args = (f"the merge now repoints {actual} entries, not the {expected} that were previewed",)


def clean_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise InvalidValue("name", "name must not be blank")
    if len(cleaned) > MAX_NAME:
        raise InvalidValue("name", f"name must be at most {MAX_NAME} characters")
    return cleaned


def clean_presentation(parameter: str, value: str | None) -> str | None:
    """An icon or colour: a name stored as given (the UI owns the sets), never blank; None clears it."""
    if value is None:
        return None
    if not value.strip():
        raise InvalidValue(parameter, f"{parameter} must not be blank (use null for none)")
    if len(value) > MAX_PRESENTATION:
        raise InvalidValue(parameter, f"{parameter} must be at most {MAX_PRESENTATION} characters")
    return value


def clean_text(value: str | None) -> str | None:
    """Free text (a note, a provider): trimmed, blank means none."""
    if value is None:
        return None
    return value.strip() or None


def previewable[T](engine: Engine, dry_run: bool, work: Callable[[Connection], T]) -> T:
    """One transaction: settle lock shared, `work`, then commit; a dry run rolls back instead."""
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            lock_settle_shared(conn)
            result = work(conn)
        except BaseException:
            trans.rollback()
            raise
        if dry_run:
            trans.rollback()
        else:
            trans.commit()
        return result


def check_count(dry_run: bool, expected: int | None, actual: int) -> None:
    """The real run's guard: the entries it repoints are the number the user confirmed."""
    if not dry_run and expected != actual:
        assert expected is not None  # `require_count` ran first
        raise MergeCountChanged(expected, actual)


def require_count(dry_run: bool, expected: int | None) -> None:
    if not dry_run and expected is None:
        raise ExpectedCountRequired()
