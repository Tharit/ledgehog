"""Errors shared by write operations."""

from __future__ import annotations


class VersionConflict(Exception):
    """A write carried the version of an entry that has moved (architecture §4.1).

    It wrote nothing; the caller shows the current state and the user decides again.
    """

    def __init__(self, entry_ids: tuple[int, ...]) -> None:
        self.entry_ids = entry_ids
        super().__init__(f"entries changed since they were read: {list(entry_ids)}")


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
