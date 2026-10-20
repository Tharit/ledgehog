"""`GET /api/ledger/entries/export`: the CSV of the ledger list's filter (architecture §4.1, spec §8)."""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.core.ledger import LedgerFilter
from app.core.ledger.export import COLUMNS, decimal, guard
from app.utils import clock
from tests.api.accounts_helpers import assert_envelope
from tests.api.conftest import login
from tests.fixtures import ledger_seed as seed
from tests.invariants.helpers import pair

URL = "/api/ledger/entries/export"
LIST = "/api/ledger/entries"
D = date(2026, 3, 10)


@pytest.fixture
def anna(client: TestClient) -> TestClient:
    login(client)
    return client


@pytest.fixture
def acct(api_engine: Engine) -> int:
    with api_engine.begin() as conn:
        return seed.account(conn)


def add(engine: Engine, account_id: int, **kw: Any) -> int:
    with engine.begin() as conn:
        return seed.entry(conn, account_id, **kw)


def exported(client: TestClient, **params: Any) -> list[dict[str, str]]:
    r = client.get(URL, params=params)
    assert r.status_code == 200, r.text
    return list(csv.DictReader(io.StringIO(r.text, newline="")))


def test_requires_a_session(client: TestClient):
    assert_envelope(client.get(URL), 401, "unauthenticated")


def test_is_not_read_as_an_entry_id(anna: TestClient):
    assert anna.get(URL).status_code == 200


def test_headers_header_and_line_ends(client: TestClient, api_engine: Engine, acct: int):
    add(api_engine, acct)
    with clock.frozen(datetime(2026, 10, 20, 12, tzinfo=UTC)):
        login(client)  # at the frozen day: a session made earlier would have expired by then
        r = client.get(URL)
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    assert r.headers["content-disposition"] == 'attachment; filename="ledger-2026-10-20.csv"'
    raw = r.content
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in raw and raw.endswith(b"\n")
    assert raw.decode().splitlines()[0] == ",".join(COLUMNS)
    assert list(COLUMNS) == [
        "id", "booked_on", "value_on", "account", "type", "amount", "currency", "category", "payee",
        "tags", "description", "note", "counter_account", "partner_id", "review_flags", "counterparty",
        "purpose", "instructed_amount", "instructed_currency", "importer",
    ]  # fmt: skip


def test_empty_ledger_is_just_the_header(anna: TestClient):
    r = anna.get(URL)
    assert r.text == ",".join(COLUMNS) + "\n"


def test_dimensions_are_joined_by_name(anna: TestClient, api_engine: Engine, acct: int):
    with api_engine.begin() as conn:
        food = seed.category(conn, "Food")  # a top-level category: the kind is the root (spec §3.5)
        groceries = seed.category(conn, "Groceries", food)
        salary = seed.category(conn, "Salary", kind="income")
        shop = seed.payee(conn, "Shop")
        t1, t2 = seed.tag(conn, "trip"), seed.tag(conn, "annual")
        e = seed.entry(
            conn,
            acct,
            amount=-1250,
            on=D,
            value_on=date(2026, 3, 11),
            description="Weekly",
            note="n",
            category_id=groceries,
            payee_id=shop,
            tags=(t1, t2),
            flags=("unconfirmed", "waiting"),
            counterparty="CP GmbH",
            purpose="Invoice 7",
            imported=True,
            source_cols={"instructed_amount": -1500, "instructed_currency": "USD"},
        )
    paid = add(api_engine, acct, amount=300000, on=date(2026, 3, 1), category_id=salary)
    rows = {int(r["id"]): r for r in exported(anna)}
    assert rows[paid]["category"] == "Income > Salary"
    row = rows[e]
    assert row == {
        "id": str(e),
        "booked_on": "2026-03-10",
        "value_on": "2026-03-11",
        "account": "Giro",
        "type": "flow",
        "amount": "-12.50",
        "currency": "EUR",
        "category": "Expense > Food > Groceries",
        "payee": "Shop",
        "tags": "annual; trip",
        "description": "Weekly",
        "note": "n",
        "counter_account": "",
        "partner_id": "",
        "review_flags": "unconfirmed; waiting",
        "counterparty": "CP GmbH",
        "purpose": "Invoice 7",
        "instructed_amount": "-15.00",
        "instructed_currency": "USD",
        "importer": "test",
    }


def test_transfer_columns_and_empty_cells(anna: TestClient, api_engine: Engine):
    with api_engine.begin() as conn:
        a, b = seed.account(conn, "Giro"), seed.account(conn, "Cash")
        out = seed.entry(conn, a, amount=-500, type="transfer")
        into = seed.entry(conn, b, amount=500, type="transfer")
        lone = seed.entry(conn, a, amount=-1, type="transfer", on=date(2026, 3, 2))
        for entry_id, other in ((out, b), (into, a), (lone, b)):
            conn.execute(
                text("UPDATE ledger_entry SET counter_account_id = :c WHERE id = :i"),
                {"c": other, "i": entry_id},
            )
        pair(conn, out, into)
    rows = {int(r["id"]): r for r in exported(anna)}
    assert rows[out]["counter_account"] == "Cash" and rows[out]["partner_id"] == str(into)
    assert rows[into]["counter_account"] == "Giro" and rows[into]["partner_id"] == str(out)
    assert rows[out]["type"] == "transfer" and rows[out]["category"] == ""
    assert rows[out]["instructed_amount"] == "" and rows[out]["importer"] == ""
    assert rows[lone]["counter_account"] == "Cash" and rows[lone]["partner_id"] == ""


def test_untyped_and_derived_entries(anna: TestClient, api_engine: Engine, acct: int):
    with api_engine.begin() as conn:
        plain = seed.entry(conn, acct, type=None)
        opening = seed.derived(conn, acct)
    rows = {int(r["id"]): r for r in exported(anna)}
    assert rows[plain]["type"] == ""
    assert rows[opening]["type"] == "opening" and rows[opening]["counterparty"] == ""
    assert rows[opening]["amount"] == "50.00"


def test_amounts_use_the_currencys_own_exponent(anna: TestClient, api_engine: Engine):
    with api_engine.begin() as conn:
        jpy = seed.account(conn, "Yen", "JPY")
        eur = seed.account(conn, "Giro")
        a = seed.entry(conn, jpy, amount=-1234)
        b = seed.entry(conn, eur, amount=5, on=date(2026, 3, 9))
        c = seed.entry(conn, eur, amount=100000, on=date(2026, 3, 8))
    rows = {int(r["id"]): r for r in exported(anna)}
    assert (rows[a]["amount"], rows[a]["currency"]) == ("-1234", "JPY")
    assert rows[b]["amount"] == "0.05" and rows[c]["amount"] == "1000.00"


def test_decimal_formatting():
    assert decimal(-5, 2) == "-0.05"
    assert decimal(0, 2) == "0.00"
    assert decimal(12345, 3) == "12.345"
    assert decimal(-7, 0) == "-7"
    assert decimal(5, 4) == "0.0005"


def test_rfc4180_quoting_round_trips(anna: TestClient, api_engine: Engine, acct: int):
    awkward = 'say "hi", then\nleave'
    add(api_engine, acct, description=awkward, note="a;b,c")
    r = anna.get(URL)
    assert '"say ""hi"", then\nleave"' in r.text
    [row] = list(csv.DictReader(io.StringIO(r.text, newline="")))
    assert row["description"] == awkward and row["note"] == "a;b,c"


@pytest.mark.parametrize("lead", ["=", "+", "-", "@"])
def test_formula_guard_on_text_cells(anna: TestClient, api_engine: Engine, acct: int, lead: str):
    add(api_engine, acct, description=f"{lead}SUM(A1)", note="fine=", counterparty=f"{lead}x", imported=True)
    [row] = exported(anna)
    assert row["description"] == f"'{lead}SUM(A1)"
    assert row["counterparty"] == f"'{lead}x"
    assert row["note"] == "fine="


def test_formula_guard_leaves_numbers_alone(anna: TestClient, api_engine: Engine, acct: int):
    add(api_engine, acct, amount=-1000, source_cols={"instructed_amount": -50, "instructed_currency": "USD"})
    [row] = exported(anna)
    assert row["amount"] == "-10.00" and row["instructed_amount"] == "-0.50"
    assert guard("-1") == "'-1" and guard("1") == "1" and guard(None) == "" and guard("") == ""


def test_the_lists_order(anna: TestClient, api_engine: Engine, acct: int):
    for day in (3, 9, 5):
        add(api_engine, acct, on=date(2026, 3, day))
    add(api_engine, acct, on=date(2026, 3, 9))
    listed = [e["id"] for e in anna.get(LIST).json()["entries"]]
    assert [int(r["id"]) for r in exported(anna)] == listed


FILTERS: list[dict[str, Any]] = [
    {},
    {"from": "2026-03-05"},
    {"from": "2026-03-04", "to": "2026-03-09"},
    {"direction": "in"},
    {"direction": "out", "currency": "EUR", "amount_min": 600, "amount_max": 1500},
    {"type": ["flow"]},
    {"flag": ["unconfirmed"]},
    {"q": "bakery"},
    {"uncategorised": "true"},
    {"payee_id": 0},  # filled in below
]


def test_row_count_equals_the_lists_total(anna: TestClient, api_engine: Engine, acct: int):
    with api_engine.begin() as conn:
        cat = seed.category(conn, "Food")
        shop = seed.payee(conn, "Shop")
        tg = seed.tag(conn, "t")
    for i in range(12):
        add(
            api_engine,
            acct,
            amount=(-1) ** i * (400 + 100 * i),
            on=date(2026, 3, 1 + i),
            description="bakery" if i % 4 == 0 else None,
            category_id=cat if i % 3 == 0 else None,
            payee_id=shop if i % 2 == 0 else None,
            tags=(tg,) if i % 5 == 0 else (),
            flags=("unconfirmed",) if i % 3 == 1 else (),
        )
    filters = [
        *FILTERS[:-1],
        {"payee_id": shop},
        {"category_id": cat},
        {"tag_id": tg},
        {"category_id": cat, "category_descendants": "false"},
    ]
    totals = set()
    for params in filters:
        total = anna.get(LIST, params={**params, "limit": 1}).json()["total"]
        rows = exported(anna, **params)
        assert len(rows) == total, params
        totals.add(total)
    assert len(totals) > 3  # the filters really differ


def test_bad_filter_is_a_422_before_any_row(anna: TestClient):
    r = anna.get(URL, params={"from": "2026-03-09", "to": "2026-03-01"})
    assert_envelope(r, 422, "validation_error")
    assert anna.get(URL, params={"currency": "eur"}).status_code == 422


def test_a_larger_set_streams_in_batches(anna: TestClient, api_engine: Engine, acct: int, monkeypatch):
    n = 1234
    with api_engine.begin() as conn:
        for i in range(n):
            seed.entry(conn, acct, amount=-(i + 1), on=date(2026, 1, 1 + i % 28), description=f"row {i}")
    sizes: list[int] = []
    from app.core.ledger import export as export_mod

    real = export_mod.stream_entries

    def spy(conn, flt, *, batch=500):
        for rows in real(conn, flt, batch=batch):
            sizes.append(len(rows))
            yield rows

    monkeypatch.setattr(export_mod, "stream_entries", spy)
    r = anna.get(URL)
    assert sizes == [500, 500, 234]  # read in batches from the cursor, never as one result
    rows = list(csv.DictReader(io.StringIO(r.text, newline="")))
    assert len(rows) == n
    assert anna.get(LIST, params={"limit": 1}).json()["total"] == n

    # the generator is lazy: the header comes out before any row is read
    sizes.clear()
    with api_engine.connect() as conn:
        chunks = export_mod.export_csv(conn, LedgerFilter(), batch=100)
        assert next(chunks).startswith("id,booked_on")
        assert sizes == []
        assert next(chunks).count("\n") == 100 and sizes == [100]
        chunks.close()
