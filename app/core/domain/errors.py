"""Errors shared by write operations."""

from __future__ import annotations


class VersionConflict(Exception):
    """A write carried the version of an entry that has moved (architecture §4.1).

    It wrote nothing; the caller shows the current state and the user decides again.
    """

    def __init__(self, entry_ids: tuple[int, ...]) -> None:
        self.entry_ids = entry_ids
        super().__init__(f"entries changed since they were read: {list(entry_ids)}")


class IngestError(Exception):
    """A delivery or removal that cannot be written; nothing is kept (a run ends `failed`)."""


class ContractViolation(IngestError):
    """The importer delivered what its contract forbids (spec §5.1); the run fails.

    Ingest never repairs, skips or counts such a record. `rule` is a stable identifier:
    `currency_mismatch`, `zero_amount`, `repeated_source_id`, `no_coverage`, and for a
    reported balance `balance_without_date` (a figure without its date, or a date without
    a figure) and `balance_after_coverage` (the record would claim a day the run did not
    cover, I36). The message names the row index and field, and quotes only amounts and
    currency codes.
    """

    def __init__(self, rule: str, message: str) -> None:
        self.rule = rule
        super().__init__(f"contract violation [{rule}]: {message}")


class RunRefused(IngestError):
    """The write transaction found that the run may no longer write (architecture §4.1).

    The checks before the locks can lose a race against an unlink, a close or a disable, so the
    shared write body repeats them inside the transaction. `reason` is one of `instance_missing`,
    `not_a_file_source`, `not_a_document_source`, `instance_disabled`, `account_missing`, `account_closed`,
    `account_not_linked`. Nothing was written; a real run ends `failed`, a preview reports it.
    """

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


class DuplicateError(Exception):
    """Marking or clearing a duplicate was refused; the message states the rule. Nothing was written."""


class DuplicateRowMissing(DuplicateError):
    def __init__(self, row_id: int) -> None:
        super().__init__(f"source transaction {row_id} does not exist")


class DuplicateOfSelf(DuplicateError):
    def __init__(self, row_id: int) -> None:
        super().__init__(f"source transaction {row_id} cannot be a duplicate of itself")


class DuplicateCrossAccount(DuplicateError):
    def __init__(self, row_id: int, of_row_id: int) -> None:
        super().__init__(
            f"source transaction {row_id} can only duplicate a row on the same account, "
            f"and {of_row_id} is on another"
        )


class UserAuthoredRow(DuplicateError):
    def __init__(self, row_id: int, of_row_id: int, user_authored: int) -> None:
        super().__init__(
            f"source transaction {user_authored} is user-authored: only imported rows are marked "
            f"as duplicates ({row_id} of {of_row_id}); a user-authored one is deleted through the entry form"
        )


class DuplicateChain(DuplicateError):
    def __init__(self, row_id: int, of_row_id: int) -> None:
        super().__init__(
            f"source transaction {of_row_id} is itself a duplicate: duplicates are never chained, "
            f"so {row_id} cannot duplicate it"
        )


class AlreadyDuplicate(DuplicateError):
    def __init__(self, row_id: int) -> None:
        super().__init__(
            f"source transaction {row_id} is already a duplicate: clear it before marking it again"
        )


class NotADuplicate(DuplicateError):
    def __init__(self, row_id: int) -> None:
        super().__init__(f"source transaction {row_id} is not a duplicate, so there is nothing to clear")
