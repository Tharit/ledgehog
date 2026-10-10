"""Errors shared by write operations."""

from __future__ import annotations


class VersionConflict(Exception):
    """A write carried the version of an entry that has moved (architecture §4.1).

    It wrote nothing; the caller shows the current state and the user decides again.
    """

    def __init__(self, entry_ids: tuple[int, ...]) -> None:
        self.entry_ids = entry_ids
        super().__init__(f"entries changed since they were read: {list(entry_ids)}")
