"""The scratch one settle shares between its steps (architecture §5.2).

A step is `fn(conn) -> StepOutcome`, so what the rounds carry from one step to the next lives
here: the set of confirmed entries (to see what a round newly confirmed), the entries history has
not learned from yet, and what resolution loaded once (accounts, classifiers for the rules, the
history snapshot). `settle()` opens one per call in a context variable; a step called outside a
settle gets a fresh one that nothing else sees.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from app.core.plugins.classifier import AccountFact, Classifier
from app.core.resolution.snapshot import Grown, HistorySnapshot


@dataclass(frozen=True)
class StepOutcome:
    """What one step did: the entry ids it changed and how many units it newly confirmed."""

    touched: Iterable[int] = ()
    newly_confirmed: int = 0


@dataclass(slots=True)
class ResolutionContext:
    accounts: Sequence[AccountFact]
    classifiers: Sequence[Classifier]
    snapshot: HistorySnapshot
    # buckets history grew in since the last pass; None before the first pass: every entry is resolved
    grown: Grown | None = None


@dataclass(slots=True)
class SettleRun:
    # confirmed movement entries as of the last flags step; None until a settle seeded it
    confirmed: set[int] | None = None
    # confirmed since the history snapshot was taken or last extended
    to_teach: list[int] = field(default_factory=list)
    resolution: ResolutionContext | None = None


_RUN: ContextVar[SettleRun | None] = ContextVar("settle_run", default=None)


def current_run() -> SettleRun:
    run = _RUN.get()
    return run if run is not None else SettleRun()


@contextmanager
def settle_run() -> Iterator[SettleRun]:
    run = SettleRun()
    token = _RUN.set(run)
    try:
        yield run
    finally:
        _RUN.reset(token)
