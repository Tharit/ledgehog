"""Calendar periods in the household's calendar (spec §8, `ux/patterns.md` §3).

Entries carry `booked_on` as a date of the household's calendar, so a period is plain date
arithmetic; what depends on the household's zone is only which day "today" is, and the caller
passes that in (`utils.clock.today(tz)`).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

Step = Literal["month", "quarter", "year"]
STEPS: tuple[Step, ...] = ("month", "quarter", "year")
MAX_PERIODS = 120


class TooManyPeriods(ValueError):
    """The range cut by the step gives more than `MAX_PERIODS` periods; `parameter` names what to change."""

    def __init__(self, parameter: str, message: str) -> None:
        super().__init__(message)
        self.parameter = parameter


@dataclass(frozen=True)
class Period:
    start: date  # inclusive, clipped to the range
    end: date  # inclusive, clipped to the range
    bucket: date  # the first day of the whole calendar period it belongs to (`date_trunc` of its dates)


def month_start(d: date) -> date:
    return d.replace(day=1)


def month_end(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def add_months(d: date, n: int) -> date:
    """The first of the month `n` months from `d`'s month (n may be negative)."""
    index = d.year * 12 + (d.month - 1) + n
    return date(index // 12, index % 12 + 1, 1)


def last_month_end(today: date) -> date:
    return today.replace(day=1) - timedelta(days=1)


def bucket_start(d: date, step: Step) -> date:
    if step == "month":
        return month_start(d)
    if step == "quarter":
        return date(d.year, (d.month - 1) // 3 * 3 + 1, 1)
    return date(d.year, 1, 1)


def _next_bucket(bucket: date, step: Step) -> date:
    return add_months(bucket, {"month": 1, "quarter": 3, "year": 12}[step])


def periods(start: date, end: date, step: Step) -> list[Period]:
    """The calendar months, quarters or years that `start..end` touches, each clipped to the range."""
    out: list[Period] = []
    bucket = bucket_start(start, step)
    while bucket <= end:
        following = _next_bucket(bucket, step)
        out.append(Period(max(bucket, start), min(following - timedelta(days=1), end), bucket))
        if len(out) > MAX_PERIODS:
            raise TooManyPeriods("step", f"the range has more than {MAX_PERIODS} periods: use a longer step")
        bucket = following
    return out


def same_day_last_month(today: date) -> date:
    """Today's day of the month in the previous month, clamped to its last day (31 Mar -> 28 Feb)."""
    last = add_months(today, -1)
    return last.replace(day=min(today.day, calendar.monthrange(last.year, last.month)[1]))
