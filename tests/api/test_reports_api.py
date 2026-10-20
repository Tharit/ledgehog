"""`GET /api/reports/*`: the Overview and the three reports (architecture §4.1, spec §8)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.api import create_app
from app.utils import clock
from app.utils.config import Config
from tests.api.accounts_helpers import assert_envelope
from tests.api.conftest import login
from tests.core.reporting.helpers import TODAY, Household, household, rate
from tests.fixtures import ledger_seed as seed

OVERVIEW = "/api/reports/overview"
BY_CATEGORY = "/api/reports/by-category"
OVER_TIME = "/api/reports/over-time"
BALANCES = "/api/reports/balances"
NOON = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)


@pytest.fixture
def today() -> Iterator[None]:
    with clock.frozen(NOON):
        yield


@pytest.fixture
def anna(client: TestClient, today: None) -> TestClient:
    login(client)  # at the frozen day: a session made earlier would have expired by then
    return client


@pytest.fixture
def seeded(api_engine: Engine) -> Household:
    with api_engine.begin() as conn:
        return household(conn)


def get(client: TestClient, url: str, **params: Any) -> dict[str, Any]:
    r = client.get(url, params=params)
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def eur(amount: int) -> dict[str, Any]:
    return {"amount": amount, "currency": "EUR"}


def line(total: int | None, count: int, unvalued: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"total": None if total is None else eur(total), "count": count, "unvalued": unvalued or []}


def usd_unvalued(amount: int, count: int = 1) -> dict[str, Any]:
    return {"amount": {"amount": amount, "currency": "USD"}, "count": count}


@pytest.mark.parametrize("url", [OVERVIEW])
def test_every_report_requires_a_session(client: TestClient, url: str):
    assert_envelope(client.get(url), 401, "unauthenticated")


# ---- the Overview


def test_the_overview_of_an_empty_ledger(anna: TestClient, today: None):
    body = get(anna, OVERVIEW)
    assert body["as_of"] == "2026-10-20" and body["base_currency"] == "EUR"
    assert body["accounts"] == []
    assert body["net_worth"] == {
        "total": eur(0),
        "unvalued": [],
        "unpaired_transfers": line(0, 0),
        "since": None,
    }
    last_12 = body["savings"]["last_12"]
    assert (last_12["from"], last_12["to"]) == ("2025-10-01", "2026-09-30")
    assert last_12["rate_bp"] is None and last_12["incomplete"] is False
    assert (body["savings"]["this_month"]["from"], body["savings"]["this_month"]["to"]) == (
        "2026-10-01",
        "2026-10-20",
    )


def test_the_overview_of_a_household(anna: TestClient, seeded: Household, today: None):
    body = get(anna, OVERVIEW)
    worth = body["net_worth"]
    assert worth["total"] == eur(640_000)
    assert worth["unvalued"] == [{"amount": {"amount": 28_000, "currency": "USD"}, "accounts": 1}]
    assert worth["unpaired_transfers"] == line(-7_000, 2)
    assert worth["since"] == {"on": "2026-09-30", "change": eur(286_000)}

    spend = body["spend"]
    assert (spend["this_month"]["from"], spend["this_month"]["to"]) == ("2026-10-01", "2026-10-20")
    assert spend["this_month"]["spend"] == line(-9_500, 4, [usd_unvalued(-2_000)])
    assert spend["this_month"]["unclassified_out"] == line(-300, 1)
    assert spend["this_month"]["reconciliations"] == line(-700, 1)
    assert spend["last_month"]["spend"] == line(-49_500, 4)
    assert (spend["last_month_to_date"]["from"], spend["last_month_to_date"]["to"]) == (
        "2026-09-01",
        "2026-09-20",
    )
    assert spend["last_month_to_date"]["spend"] == line(-49_500 + 40_000, 3)  # the trip is on the 30th

    this_month = body["savings"]["this_month"]
    assert this_month["savings"] == line(293_000, 9, [usd_unvalued(-2_000)])
    assert this_month["rate_bp"] == 9734 and this_month["incomplete"] is True
    assert body["savings"]["last_month"]["rate_bp"] == 8300


def test_the_overviews_accounts_by_data_age_with_the_account_facts(
    anna: TestClient, api_engine: Engine, seeded: Household, today: None
):
    with api_engine.begin() as conn:
        closed = seed.account(conn, "Closed and empty")
        conn.execute(text("UPDATE account SET closed_on = DATE '2026-01-01' WHERE id = :i"), {"i": closed})
        fresh = seed.account(conn, "Never fed")
    accounts = get(anna, OVERVIEW)["accounts"]
    assert closed not in {a["id"] for a in accounts}  # closed with nothing in it
    # never fed first; then the stalest (the openings' records of 1 Aug, ties by id); the Giro's is 12 Oct
    assert [a["id"] for a in accounts] == [fresh, seeded.cash, seeded.usd, seeded.giro]
    assert [a["data_age_days"] for a in accounts] == [None, 80, 80, 8]
    listed = {a["id"]: a for a in get(anna, "/api/ledger/accounts")["accounts"]}
    for a in accounts:  # AccountOut, plus the data age
        assert {k: v for k, v in a.items() if k != "data_age_days"} == listed[a["id"]]


def _app_in(api_config: Config, api_engine: Engine, zone: str) -> TestClient:
    client = TestClient(
        create_app(replace(api_config, timezone=ZoneInfo(zone)), api_engine), base_url="http://localhost"
    )
    login(client)
    return client


@contextmanager
def at(instant: datetime) -> Iterator[None]:
    with clock.frozen(instant):
        yield


def test_the_month_turns_in_the_households_zone_not_in_utc(api_config: Config, api_engine: Engine):
    with api_engine.begin() as conn:
        acct = seed.account(conn)
        food = seed.category(conn, "Food")
        seed.entry(conn, acct, amount=-100, on=date(2026, 9, 30), category_id=food)
        seed.entry(conn, acct, amount=-200, on=date(2026, 10, 1), category_id=food)
    late = datetime(2026, 9, 30, 23, 30, tzinfo=UTC)  # 01:30 on 1 October in Berlin
    with at(late):
        berlin = get(_app_in(api_config, api_engine, "Europe/Berlin"), OVERVIEW)
        utc = get(_app_in(api_config, api_engine, "UTC"), OVERVIEW)
    assert berlin["as_of"] == "2026-10-01"
    assert berlin["spend"]["this_month"]["spend"] == line(-200, 1)
    assert berlin["spend"]["last_month"]["spend"] == line(-100, 1)
    assert utc["as_of"] == "2026-09-30"
    assert utc["spend"]["this_month"]["spend"] == line(-100, 1)


def test_an_unvalued_foreign_account_is_a_remainder_until_a_rate_arrives(
    anna: TestClient, api_engine: Engine, seeded: Household, today: None
):
    before = get(anna, OVERVIEW)["net_worth"]
    assert before["unvalued"] and before["total"] == eur(640_000)
    with api_engine.begin() as conn:
        rate(conn, "USD", TODAY, "2.0")
    after = get(anna, OVERVIEW)["net_worth"]
    assert after["unvalued"] == [] and after["total"] == eur(640_000 + 14_000)
