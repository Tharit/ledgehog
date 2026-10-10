"""Row filters: skip a row when a column equals or matches a value (csv.md §4)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.plugins.importers.csv.profile import RowFilter


@dataclass(frozen=True, slots=True)
class CompiledFilter:
    index: int
    equals: str | None
    pattern: re.Pattern[str] | None
    description: str  # profile data only, never cell content

    def hit(self, cells: Sequence[str]) -> bool:
        cell = cells[self.index].strip() if self.index < len(cells) else ""
        if self.equals is not None:
            return cell == self.equals
        assert self.pattern is not None
        return self.pattern.search(cell) is not None


def compile_filter(f: RowFilter, index: int, name: str) -> CompiledFilter:
    if f.equals is not None:
        return CompiledFilter(index, f.equals, None, f"{name} equals {f.equals!r}")
    assert f.matches is not None
    return CompiledFilter(index, None, re.compile(f.matches), f"{name} matches {f.matches!r}")


def first_hit(filters: Sequence[CompiledFilter], cells: Sequence[str]) -> CompiledFilter | None:
    for f in filters:
        if f.hit(cells):
            return f
    return None
