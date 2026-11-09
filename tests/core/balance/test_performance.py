"""An investment account's net deposits, gain and money-weighted return (spec §8, D249)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

import pytest
from sqlalchemy import Connection, text

from app.core.accounts import AccountView, list_accounts
from app.core.balance.performance import xirr
from tests.core.balance.scene import Scene
from tests.invariants.helpers import make_run, make_source

Make = Callable[..., int]

D0 = date(2025, 1, 1)


def _npv(rate: float, flows: list[tuple[date, int]]) -> float:
    first = min(d for d, _ in flows)
    return float(sum(a * (1 + rate) ** (-(d - first).days / 365) for d, a in flows))


# ---- xirr: a pure function --------------------------------------------------------------------


def test_one_payment_and_one_payout_a_year_apart_is_the_simple_rate() -> None:
    assert xirr([(D0, -1000), (D0 + timedelta(days=365), 1100)]) == pytest.approx(0.10, abs=1e-9)
    assert xirr([(D0, -1000), (D0 + timedelta(days=365), 900)]) == pytest.approx(-0.10, abs=1e-9)


def test_two_payments_and_a_payout_match_the_closed_form() -> None:
    # 1000 * x^2 + 1000 * x = 2310 with x = 1 + r: x = (-1 + sqrt(10.24)) / 2 = 1.1
    flows = [(D0, -1000), (date(2026, 1, 1), -1000), (date(2027, 1, 1), 2310)]
    assert xirr(flows) == pytest.approx(0.10, abs=1e-9)


def test_the_order_of_the_flows_does_not_matter() -> None:
    flows = [(D0, -1000), (date(2025, 4, 1), -300), (date(2025, 9, 1), 200), (date(2026, 3, 1), 1250)]
    rate = xirr(flows)
    assert rate is not None and xirr(list(reversed(flows))) == pytest.approx(rate, abs=1e-12)
    assert _npv(rate, flows) == pytest.approx(0, abs=1e-6)  # it is a root


def test_a_loss_and_a_short_span_have_a_root_too() -> None:
    assert xirr([(D0, -1000), (D0 + timedelta(days=30), 1010)]) == pytest.approx(
        1.01 ** (365 / 30) - 1, rel=1e-9
    )
    assert xirr([(D0, -1000), (D0 + timedelta(days=730), 250)]) == pytest.approx(-0.5, abs=1e-9)


def test_no_sign_change_has_no_rate() -> None:
    assert xirr([(D0, -1000), (date(2026, 1, 1), -50)]) is None
    assert xirr([(D0, 1000), (date(2026, 1, 1), 50)]) is None
    assert xirr([(D0, 0), (date(2026, 1, 1), 0)]) is None
    assert xirr([]) is None


def test_a_rate_outside_the_searched_range_is_none() -> None:
    assert xirr([(D0, -100), (D0 + timedelta(days=365), 2000)]) is None  # +1900 % a year


# ---- the account's figures ---------------------------------------------------------------------


def _depot(db_conn: Connection, make_account: Make) -> Scene:
    return Scene(db_conn, make_account, kind="depot", name="Depot")


def _facts(db_conn: Connection, s: Scene) -> AccountView:
    (view,) = [v for v in list_accounts(db_conn) if v.id == s.account]
    return view


def test_net_deposits_gain_and_return_of_a_depot(db_conn: Connection, make_account: Make) -> None:
    s = _depot(db_conn, make_account)
    s.manual(date(2024, 1, 1), 1_000_000)  # the anchor
    s.move(date(2024, 7, 1), 100_000)  # paid in
    s.move(date(2025, 1, 15), -20_000)  # a distribution paid out to the cash account
    s.manual(date(2025, 6, 30), 1_300_000)
    s.move(date(2025, 7, 10), 50_000)  # after the latest record: net deposits, not the return
    s.recompute()
    v = _facts(db_conn, s)
    assert v.balance == 1_350_000
    assert v.net_deposits == 1_000_000 + 100_000 - 20_000 + 50_000
    assert v.gain == v.balance - v.net_deposits == 220_000
    assert v.return_as_of == date(2025, 6, 30)
    flows = [
        (date(2024, 1, 1), -1_000_000),
        (date(2024, 7, 1), -100_000),
        (date(2025, 1, 15), 20_000),
        (date(2025, 6, 30), 1_300_000),
    ]
    assert v.return_rate_bp is not None
    assert _npv(v.return_rate_bp / 10_000, flows) == pytest.approx(0, abs=200)  # within a basis point
    # the gain is the sum of the account's valuations: the derived entries agree with the figures
    valuations = db_conn.execute(
        text(
            "SELECT coalesce(sum(amount), 0) FROM ledger_entry WHERE account_id = :a AND type = 'valuation'"
        ),
        {"a": s.account},
    ).scalar_one()
    assert v.gain == valuations
    s.check()


def test_the_return_waits_for_a_year_between_the_anchor_and_the_latest_record(
    db_conn: Connection, make_account: Make
) -> None:
    s = _depot(db_conn, make_account)
    s.manual(date(2025, 1, 1), 500_000)
    last = s.manual(date(2025, 12, 31), 530_000)  # 364 days
    s.recompute()
    v = _facts(db_conn, s)
    assert (v.net_deposits, v.gain, v.return_rate_bp) == (500_000, 30_000, None)
    db_conn.execute(text("UPDATE balance_record SET balance_on = '2026-01-01' WHERE id = :i"), {"i": last})
    s.recompute()  # 365 days
    assert _facts(db_conn, s).return_rate_bp == 600


def test_an_anchor_alone_has_net_deposits_and_no_gain_or_return(
    db_conn: Connection, make_account: Make
) -> None:
    s = _depot(db_conn, make_account)
    s.manual(date(2025, 1, 1), 500_000)
    s.recompute()
    v = _facts(db_conn, s)
    assert (v.net_deposits, v.gain, v.return_rate_bp, v.return_as_of) == (500_000, 0, None, date(2025, 1, 1))


def test_a_depot_without_a_record_has_none_of_the_figures(db_conn: Connection, make_account: Make) -> None:
    s = _depot(db_conn, make_account)
    s.move(date(2025, 1, 1), 1000)
    v = _facts(db_conn, s)
    assert (v.net_deposits, v.gain, v.return_rate_bp, v.return_as_of) == (None, None, None, None)


def test_a_duplicate_row_is_no_movement(db_conn: Connection, make_account: Make) -> None:
    s = _depot(db_conn, make_account)
    s.manual(date(2025, 1, 1), 100_000)
    original = make_source(db_conn, s.account, amount=5_000, booked_on=date(2025, 2, 1))
    make_source(db_conn, s.account, amount=5_000, booked_on=date(2025, 2, 1), duplicate_of=original)
    s.recompute()
    assert _facts(db_conn, s).net_deposits == 105_000


def test_a_reverted_runs_record_does_not_count(db_conn: Connection, make_account: Make) -> None:
    s = _depot(db_conn, make_account)
    s.manual(date(2024, 1, 1), 100_000)
    s.manual(date(2025, 2, 1), 110_000)
    reverted = make_run(db_conn, s.account, status="reverted", covered_through=date(2026, 1, 1))
    s.reported(date(2026, 1, 1), 999_999, run_id=reverted)
    s.recompute()
    v = _facts(db_conn, s)
    assert (v.return_as_of, v.gain) == (date(2025, 2, 1), 10_000)


@pytest.mark.parametrize("kind", ["checking", "savings", "cash", "card"])
def test_another_kind_of_account_has_none_of_the_figures(
    db_conn: Connection, make_account: Make, kind: str
) -> None:
    s = Scene(db_conn, make_account, kind=kind)
    s.manual(date(2024, 1, 1), 100_000)
    s.manual(date(2026, 1, 1), 120_000)
    s.recompute()
    v = _facts(db_conn, s)
    assert (v.net_deposits, v.gain, v.return_rate_bp, v.return_as_of) == (None, None, None, None)


def test_an_asset_account_has_the_figures_too(db_conn: Connection, make_account: Make) -> None:
    s = Scene(db_conn, make_account, kind="asset")
    s.manual(date(2024, 1, 1), 100_000)
    s.manual(date(2025, 1, 1), 120_000)  # 366 days: 2024 is a leap year
    s.recompute()
    v = _facts(db_conn, s)
    assert (v.net_deposits, v.gain) == (100_000, 20_000)
    assert v.return_rate_bp == round((1.2 ** (365 / 366) - 1) * 10_000)
