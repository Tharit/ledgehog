from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.utils import clock


def test_now_is_aware_utc():
    n = clock.now()
    assert n.tzinfo is not None
    assert n.utcoffset() == timedelta(0)


def test_today_requires_an_explicit_zone():
    with pytest.raises(TypeError):
        clock.today()  # type: ignore[call-arg]


def test_today_follows_the_zone_not_utc():
    with clock.frozen(datetime(2026, 1, 1, 23, 30, tzinfo=UTC)):
        assert clock.today(ZoneInfo("UTC")) == date(2026, 1, 1)
        assert clock.today(ZoneInfo("Europe/Berlin")) == date(2026, 1, 2)
        assert clock.today(ZoneInfo("America/Los_Angeles")) == date(2026, 1, 1)


def test_frozen_restores_the_real_clock():
    with clock.frozen(datetime(2020, 1, 1, tzinfo=UTC)):
        assert clock.now() == datetime(2020, 1, 1, tzinfo=UTC)
    assert clock.now().year >= 2026


def test_frozen_rejects_naive_datetimes():
    with pytest.raises(ValueError), clock.frozen(datetime(2020, 1, 1)):
        pass


def test_frozen_can_advance():
    with clock.frozen(datetime(2020, 1, 1, tzinfo=UTC)) as c:
        c.advance(timedelta(days=2))
        assert clock.now() == datetime(2020, 1, 3, tzinfo=UTC)
