"""The only caller of the system clock (architecture §5.6).

`now()` is an aware UTC instant; `today(tz)` requires an explicit zone, there is
deliberately no zero-argument form. Tests freeze time with `frozen()`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta, tzinfo

_override: FrozenClock | None = None


class FrozenClock:
    """A fixed, advanceable instant installed by `frozen()`."""

    def __init__(self, instant: datetime) -> None:
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("frozen clock needs an aware datetime")
        self._instant = instant.astimezone(UTC)

    def now(self) -> datetime:
        return self._instant

    def advance(self, delta: timedelta) -> None:
        self._instant += delta


def now() -> datetime:
    """The current instant, aware, in UTC."""
    if _override is not None:
        return _override.now()
    return datetime.now(UTC)


def today(tz: tzinfo) -> date:
    """The current calendar day in `tz` (whose day it means must always be said)."""
    return now().astimezone(tz).date()


@contextmanager
def frozen(instant: datetime) -> Iterator[FrozenClock]:
    """Freeze the clock at `instant` for the duration of the block."""
    global _override
    previous = _override
    _override = FrozenClock(instant)
    try:
        yield _override
    finally:
        _override = previous
