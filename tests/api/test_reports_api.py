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


@pytest.mark.parametrize("url", [OVERVIEW, BY_CATEGORY, OVER_TIME, BALANCES])
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


# ---- By category


def error_locations(response: Any) -> list[list[str]]:
    return [d["location"] for d in response.json()["error"]["details"]]


def test_by_category_needs_its_range_and_names_what_is_wrong(anna: TestClient):
    for params, named in (
        ({"to": "2026-10-31"}, "from"),
        ({"from": "2026-10-01"}, "to"),
        ({"from": "2026-10-31", "to": "2026-10-01"}, "to"),  # reversed
        ({"from": "2026-10-01", "to": "2026-10-31", "kind": "transfer"}, "kind"),
        ({"from": "2026-10-01", "to": "2026-10-31", "top": 0}, "top"),
        ({"from": "2026-10-01", "to": "2026-10-31", "account_id": 0}, "account_id"),
    ):
        r = anna.get(BY_CATEGORY, params=params)
        assert_envelope(r, 422, "validation_error")
        assert any(loc[:2] == ["query", named] for loc in error_locations(r)), params


def test_by_category_of_a_household_month(anna: TestClient, seeded: Household):
    body = get(anna, BY_CATEGORY, **{"from": "2026-10-01", "to": "2026-10-31"}, top=5)
    assert (body["from"], body["to"], body["kind"], body["base_currency"]) == (
        "2026-10-01",
        "2026-10-31",
        "expense",
        "EUR",
    )
    assert body["total"] == line(-9_500, 4, [usd_unvalued(-2_000)])
    rows = {r["category_id"]: r for r in body["categories"]}
    assert [r["category_id"] for r in body["categories"]] == [seeded.food, seeded.groceries, seeded.travel]
    assert rows[seeded.groceries]["parent_id"] == seeded.food
    assert rows[seeded.food]["own"] == line(0, 0) and rows[seeded.food]["total"] == line(-10_200, 2)
    assert rows[seeded.travel]["share_bp"] is None  # refunds beyond purchases
    assert [s["category_id"] for s in body["slices"]] == [seeded.food]
    assert body["other"] is None
    assert body["unclassified_out"] == line(-300, 1) and body["unclassified_in"] == line(2_500, 1)
    assert body["reconciliations"] == line(-700, 1)
    assert body["unconfirmed_count"] == 1


def test_by_category_without_top_has_no_slices_and_income_is_the_other_kind(
    anna: TestClient, seeded: Household
):
    body = get(anna, BY_CATEGORY, **{"from": "2026-10-01", "to": "2026-10-31"}, kind="income")
    assert body["slices"] is None and body["other"] is None
    assert body["total"] == line(301_000, 2)
    assert {r["category_id"] for r in body["categories"]} == {seeded.salary, seeded.gifts}


def test_by_category_takes_the_ledgers_filters_with_several_values_as_alternatives(
    anna: TestClient, seeded: Household
):
    sep = {"from": "2026-09-01", "to": "2026-09-30"}
    assert get(anna, BY_CATEGORY, **sep, tag_id=seeded.trip)["total"] == line(-40_000, 1)
    cash = get(anna, BY_CATEGORY, **{"from": "2026-10-01", "to": "2026-10-31"}, account_id=seeded.cash)
    assert cash["total"] == line(-1_200, 1)
    both = get(
        anna, BY_CATEGORY, **{"from": "2026-10-01", "to": "2026-10-31"}, account_id=[seeded.cash, seeded.giro]
    )
    assert both["total"]["count"] == 3


def test_the_overviews_spend_is_by_categorys_total_of_the_same_range(anna: TestClient, seeded: Household):
    ov = get(anna, OVERVIEW)["spend"]
    month = get(anna, BY_CATEGORY, **{"from": "2026-10-01", "to": "2026-10-20"})
    assert ov["this_month"]["spend"] == month["total"]
    assert ov["this_month"]["unclassified_out"] == month["unclassified_out"]
    assert ov["this_month"]["reconciliations"] == month["reconciliations"]
    last = get(anna, BY_CATEGORY, **{"from": "2026-09-01", "to": "2026-09-30"})
    assert ov["last_month"]["spend"] == last["total"]
    same_day = get(anna, BY_CATEGORY, **{"from": "2026-09-01", "to": "2026-09-20"})
    assert ov["last_month_to_date"]["spend"] == same_day["total"]


def test_every_node_of_by_category_counts_what_the_ledger_list_lists_for_its_drilldown(
    anna: TestClient, seeded: Household
):
    rng = {"from": "2026-08-01", "to": "2026-10-31"}
    body = get(anna, BY_CATEGORY, **rng)

    def listed(**params: Any) -> int:
        return int(get(anna, "/api/ledger/entries", limit=1, **rng, **params)["total"])

    for row in body["categories"]:
        assert row["total"]["count"] == listed(category_id=row["category_id"])
        assert row["own"]["count"] == listed(category_id=row["category_id"], category_descendants="false")
    roots = [r["category_id"] for r in body["categories"] if r["parent_id"] is None]
    assert body["total"]["count"] == listed(category_id=roots)  # a whole kind: its top-level categories
    assert body["unclassified_out"]["count"] == listed(uncategorised="true", direction="out")
    assert body["unclassified_in"]["count"] == listed(uncategorised="true", direction="in")
    assert body["reconciliations"]["count"] == listed(type="reconciliation")
    assert body["unconfirmed_count"] == listed(flag="unconfirmed")


# ---- Over time

SEP_OCT = {"from": "2026-09-01", "to": "2026-10-31"}


def test_over_time_names_the_parameter_at_fault(anna: TestClient):
    for params, named in (
        ({"to": "2026-10-31"}, "from"),
        ({"from": "2026-10-01"}, "to"),
        ({"from": "2026-10-31", "to": "2026-10-01"}, "to"),
        ({**SEP_OCT, "step": "week"}, "step"),
        ({**SEP_OCT, "mode": "chart"}, "mode"),
        ({**SEP_OCT, "kind": "transfer"}, "kind"),
        ({"from": "2015-01-01", "to": "2026-10-31", "step": "month"}, "step"),  # 142 months
    ):
        r = anna.get(OVER_TIME, params=params)
        assert_envelope(r, 422, "validation_error")
        assert any(loc[:2] == ["query", named] for loc in error_locations(r)), params
    quarters = anna.get(OVER_TIME, params={"from": "2015-01-01", "to": "2026-10-31", "step": "quarter"})
    assert quarters.status_code == 200


def test_over_time_savings_is_the_default_mode_and_carries_only_its_own_fields(
    anna: TestClient, seeded: Household
):
    body = get(anna, OVER_TIME, **SEP_OCT)
    assert set(body) == {"base_currency", "kind", "step", "periods", "savings", "total"}
    assert body["step"] == "month"
    assert body["periods"] == [
        {"from": "2026-09-01", "to": "2026-09-30"},
        {"from": "2026-10-01", "to": "2026-10-31"},
    ]
    sep, octo = body["savings"]
    assert sep["income"] == line(300_000, 1) and sep["expense"] == line(-49_500, 4)
    assert sep["unclassified"] == line(-1_500, 1) and sep["reconciliations"] == line(0, 0)
    assert sep["savings"] == line(249_000, 6) and sep["rate_bp"] == 8300 and sep["incomplete"] is True
    assert octo["rate_bp"] == 9734 and octo["reconciliations"] == line(-700, 1)
    total = body["total"]
    assert total["savings"]["total"] == eur(542_000) and total["rate_bp"] == 9018  # 542000 / 601000
    for field in ("income", "expense", "unclassified", "reconciliations", "savings"):
        assert total[field]["count"] == sep[field]["count"] + octo[field]["count"]
        parts = (sep[field]["total"]["amount"], octo[field]["total"]["amount"])
        assert total[field]["total"]["amount"] == sum(parts)


def test_over_time_cuts_by_quarter_and_year_in_calendar_buckets(anna: TestClient, seeded: Household):
    q = get(anna, OVER_TIME, **{"from": "2026-08-15", "to": "2026-10-20"}, step="quarter")
    assert q["periods"] == [
        {"from": "2026-08-15", "to": "2026-09-30"},
        {"from": "2026-10-01", "to": "2026-10-20"},
    ]
    year = get(anna, OVER_TIME, **{"from": "2026-01-01", "to": "2026-12-31"}, step="year")
    assert year["periods"] == [{"from": "2026-01-01", "to": "2026-12-31"}]
    assert year["savings"][0] == year["total"]  # one period is the whole range


def test_over_time_by_category_carries_the_tree_per_period(anna: TestClient, seeded: Household):
    body = get(anna, OVER_TIME, **SEP_OCT, mode="category")
    assert set(body) == {
        "base_currency",
        "kind",
        "step",
        "periods",
        "categories",
        "slices",
        "other",
        "totals",
        "sum",
    }
    rows = {c["category_id"]: c for c in body["categories"]}
    assert [c["category_id"] for c in body["categories"]] == [
        seeded.travel,
        seeded.food,
        seeded.groceries,
    ]
    assert rows[seeded.food]["total"] == [line(-9_500, 3), line(-10_200, 2)]
    assert rows[seeded.food]["own"] == [line(-2_000, 1), line(0, 0)]
    assert rows[seeded.food]["sum"] == line(-19_700, 5)
    assert rows[seeded.food]["own_sum"] == line(-2_000, 1)  # its own entries over the range
    assert rows[seeded.groceries]["own_sum"] == rows[seeded.groceries]["sum"]
    assert [s["category_id"] for s in body["slices"]] == [seeded.travel, seeded.food]
    assert body["other"] == [line(0, 0), line(0, 0)]
    assert body["totals"] == [line(-49_500, 4), line(-9_500, 4, [usd_unvalued(-2_000)])]
    whole = get(anna, BY_CATEGORY, **SEP_OCT)
    assert body["sum"] == whole["total"]  # the periods sum to the range
    assert {c["category_id"]: c["sum"] for c in body["categories"]} == {
        c["category_id"]: c["total"] for c in whole["categories"]
    }


def test_over_time_filters_are_the_ledgers(anna: TestClient, seeded: Household):
    body = get(anna, OVER_TIME, **SEP_OCT, tag_id=seeded.trip, mode="category")
    assert [c["category_id"] for c in body["categories"]] == [seeded.travel]
    savings = get(anna, OVER_TIME, **SEP_OCT, account_id=[seeded.cash])
    assert savings["total"]["expense"] == line(-1_200, 1)


def test_every_cell_of_over_time_counts_what_the_ledger_lists_for_its_drilldown(
    anna: TestClient, seeded: Household
):
    def listed(**params: Any) -> int:
        return int(get(anna, "/api/ledger/entries", limit=1, **params)["total"])

    body = get(anna, OVER_TIME, **SEP_OCT)
    income_roots = [seeded.salary, seeded.gifts]
    expense_roots = [seeded.food, seeded.travel]
    for period, s in zip(body["periods"], body["savings"], strict=True):
        rng = {"from": period["from"], "to": period["to"]}
        assert s["income"]["count"] == listed(**rng, category_id=income_roots)
        assert s["expense"]["count"] == listed(**rng, category_id=expense_roots)
        assert s["unclassified"]["count"] == listed(**rng, uncategorised="true")
        assert s["reconciliations"]["count"] == listed(**rng, type="reconciliation")


# ---- Balances

AUG_OCT = {"from": "2026-08-01", "to": "2026-10-31"}


def usd(amount: int) -> dict[str, Any]:
    return {"amount": amount, "currency": "USD"}


def test_balances_name_the_parameter_at_fault(anna: TestClient):
    for params, named in (
        ({"to": "2026-10-31"}, "from"),
        ({"from": "2026-10-01"}, "to"),
        ({"from": "2026-10-31", "to": "2026-10-01"}, "to"),
        ({"from": "2010-01-01", "to": "2026-10-31"}, "from"),  # more than 120 month-ends
    ):
        r = anna.get(BALANCES, params=params)
        assert_envelope(r, 422, "validation_error")
        assert any(loc[:2] == ["query", named] for loc in error_locations(r)), params


def test_balances_at_the_month_ends_with_today_as_the_current_months_point(
    anna: TestClient, seeded: Household
):
    body = get(anna, BALANCES, **AUG_OCT)
    assert body["base_currency"] == "EUR"
    assert body["points"] == ["2026-08-31", "2026-09-30", "2026-10-20"]
    assert [n["total"] for n in body["net_worth"]] == [eur(105_000), eur(354_000), eur(640_000)]
    assert [n["unvalued"] for n in body["net_worth"]] == [
        [{"amount": usd(30_000), "accounts": 1}],
        [{"amount": usd(30_000), "accounts": 1}],
        [{"amount": usd(28_000), "accounts": 1}],
    ]
    accounts = {a["account_id"]: a for a in body["accounts"]}
    assert set(accounts) == {seeded.giro, seeded.cash, seeded.usd}
    giro = accounts[seeded.giro]
    # the opening and the reconciliation are in the balances
    assert giro["balances"] == [eur(100_000), eur(349_000), eur(631_200)]
    assert giro["native"] == giro["balances"]
    foreign = accounts[seeded.usd]
    assert foreign["balances"] == [None, None, None]  # no rate: unvalued, never zero
    assert foreign["native"] == [usd(30_000), usd(30_000), usd(28_000)]


def test_balances_carry_each_kinds_net_worth_in_the_kind_order(anna: TestClient, seeded: Household):
    body = get(anna, BALANCES, **AUG_OCT)
    assert [k["kind"] for k in body["kinds"]] == ["checking", "card", "cash"]  # Giro, Travel card, Cash
    by_kind = {k["kind"]: k["net_worth"] for k in body["kinds"]}
    accounts = {a["account_id"]: a for a in body["accounts"]}
    assert [n["total"] for n in by_kind["cash"]] == accounts[seeded.cash]["balances"]  # its one account
    assert by_kind["card"][0] == {"total": None, "unvalued": [{"amount": usd(30_000), "accounts": 1}]}
    assert [n["total"] for n in by_kind["checking"]] == accounts[seeded.giro]["balances"]
    for i, worth in enumerate(body["net_worth"]):  # the kinds add up to the net worth, here
        parts = [k["net_worth"][i]["total"] for k in body["kinds"] if k["net_worth"][i]["total"]]
        assert sum(p["amount"] for p in parts) == worth["total"]["amount"]


def test_balances_at_today_are_the_overviews_net_worth(anna: TestClient, seeded: Household):
    body = get(anna, BALANCES, **AUG_OCT)
    assert body["net_worth"][-1] == {
        "total": get(anna, OVERVIEW)["net_worth"]["total"],
        "unvalued": get(anna, OVERVIEW)["net_worth"]["unvalued"],
    }


def test_balances_value_a_foreign_account_when_a_rate_is_in_the_window(
    anna: TestClient, api_engine: Engine, seeded: Household
):
    with api_engine.begin() as conn:
        rate(conn, "USD", date(2026, 9, 28), "2.0")
    body = get(anna, BALANCES, **AUG_OCT)
    foreign = next(a for a in body["accounts"] if a["account_id"] == seeded.usd)
    assert foreign["balances"] == [None, eur(15_000), None]  # 30 Sep is in the window; 20 Oct is not
    assert body["net_worth"][1]["unvalued"] == [] and body["net_worth"][1]["total"] == eur(369_000)
    assert body["net_worth"][2]["unvalued"] != []


def test_balances_list_a_closed_account_only_when_it_held_a_balance_in_the_range(
    anna: TestClient, api_engine: Engine, seeded: Household
):
    with api_engine.begin() as conn:
        old = seed.account(conn, "Old")
        seed.entry(conn, old, amount=500, on=date(2026, 3, 1))
        seed.entry(conn, old, amount=-500, on=date(2026, 4, 1))
        conn.execute(text("UPDATE account SET closed_on = DATE '2026-04-01' WHERE id = :i"), {"i": old})
    assert old not in {a["account_id"] for a in get(anna, BALANCES, **AUG_OCT)["accounts"]}
    spring = get(anna, BALANCES, **{"from": "2026-03-01", "to": "2026-05-31"})
    held = next(a for a in spring["accounts"] if a["account_id"] == old)
    assert [b["amount"] for b in held["balances"]] == [500, 0, 0]
