"""`GET /api/ledger/entries`: the filtered, paged ledger list (architecture §4.1, spec §8)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.api.accounts_helpers import assert_envelope
from tests.api.conftest import login
from tests.fixtures import ledger_seed as seed

URL = "/api/ledger/entries"
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


def listed(client: TestClient, **params: Any) -> dict[str, Any]:
    r = client.get(URL, params=params)
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def entry_ids(client: TestClient, **params: Any) -> list[int]:
    return [e["id"] for e in listed(client, **params)["entries"]]


def test_requires_a_session(client: TestClient):
    assert_envelope(client.get(URL), 401, "unauthenticated")


def test_empty_ledger(anna: TestClient):
    assert listed(anna) == {"entries": [], "total": 0, "limit": 100, "offset": 0}


def test_row_json_shape_and_money(anna: TestClient, api_engine: Engine, acct: int):
    with api_engine.begin() as conn:
        p, c, t = seed.payee(conn, "Shop"), seed.category(conn, "Food"), seed.tag(conn, "trip")
        e = seed.entry(
            conn,
            acct,
            amount=-1250,
            on=D,
            value_on=date(2026, 3, 11),
            description=None,
            note="n",
            category_id=c,
            payee_id=p,
            tags=(t,),
            counterparty="CP",
            purpose="PU",
            flags=("unconfirmed", "unclassified"),
            imported=True,
            end_to_end_id="E2E",
            mandate_ref="M-1",
            source_cols={
                "counterparty_ref": "DE00 1",
                "counterparty_bic": "BIC1",
                "booking_text": "Kartenzahlung",
                "instructed_amount": -1400,
                "instructed_currency": "USD",
            },
        )
        src = seed.source_of(conn, e)
    body = listed(anna)
    assert (body["total"], body["limit"], body["offset"]) == (1, 100, 0)
    assert body["entries"] == [
        {
            "id": e,
            "version": 1,
            "account_id": acct,
            "booked_on": "2026-03-10",
            "value_on": "2026-03-11",
            "amount": {"amount": -1250, "currency": "EUR"},
            "type": "flow",
            "description": None,
            "note": "n",
            "display_text": "CP",
            "source_text": None,
            "payee_id": p,
            "category_id": c,
            "counter_account_id": None,
            "counterpart_entry_id": None,
            "source_transaction_id": src,
            "review_flags": ["unclassified", "unconfirmed"],
            "tag_ids": [t],
            "source": {
                "amount": {"amount": -1250, "currency": "EUR"},
                "counterparty_name": "CP",
                "counterparty_ref": "DE00 1",
                "counterparty_bic": "BIC1",
                "purpose": "PU",
                "booking_text": "Kartenzahlung",
                "end_to_end_id": "E2E",
                "mandate_ref": "M-1",
                "instructed_amount": {"amount": -1400, "currency": "USD"},
                "source_format": "camt053",
                "booking": None,
            },
            "derivation": {},
            "unit_key": src,
            "authored": False,
            "origin": "import",
            "partner": None,
        }
    ]
    # the one-entry read answers with the same row, nothing more and nothing less
    one = anna.get(f"{URL}/{e}")
    assert one.status_code == 200 and one.json() == body["entries"][0]
    assert "raw" not in one.text and "content_hash" not in one.text


def test_each_dimension_over_http(anna: TestClient, api_engine: Engine, acct: int):
    with api_engine.begin() as conn:
        b = seed.account(conn, "B")
        root = seed.category(conn, "Living")
        kid = seed.category(conn, "Food", root)
        p = seed.payee(conn, "Pizzeria")
        t = seed.tag(conn, "x")
        a1 = seed.entry(
            conn, acct, on=D, category_id=kid, payee_id=p, tags=(t,), amount=-700, description="Lunch"
        )
        a2 = seed.entry(conn, b, on=date(2026, 4, 1), amount=300, type=None, flags=("unclassified",))
        o = seed.derived(conn, b, type="opening", on=date(2026, 1, 1))
    assert entry_ids(anna, account_id=[acct, b]) == [a2, a1, o]
    assert entry_ids(anna, account_id=b) == [a2, o]
    assert entry_ids(anna, **{"from": "2026-03-10", "to": "2026-03-10"}) == [a1]
    assert entry_ids(anna, category_id=root) == [a1]
    assert entry_ids(anna, category_id=root, category_descendants="false") == []
    assert entry_ids(anna, payee_id=p) == [a1]
    assert entry_ids(anna, tag_id=t) == [a1]
    assert entry_ids(anna, amount_min=700, amount_max=700, currency="EUR") == [a1]
    assert entry_ids(anna, currency="EUR", direction="in") == [a2, o]
    assert entry_ids(anna, q="lunch") == [a1]
    assert entry_ids(anna, type=["opening", "transfer"]) == [o]
    assert entry_ids(anna, flag="unclassified") == [a2]
    assert entry_ids(anna, flag=["unclassified", "waiting"], type="flow") == []


def test_uncategorised_over_http(anna: TestClient, api_engine: Engine, acct: int):
    with api_engine.begin() as conn:
        c = seed.category(conn, "Food")
        seed.entry(conn, acct, category_id=c)
        plain = seed.entry(conn, acct)
    assert entry_ids(anna, uncategorised="true") == [plain]
    assert len(entry_ids(anna, uncategorised="false")) == 2


def test_pagination_over_http(anna: TestClient, api_engine: Engine, acct: int):
    made = [add(api_engine, acct, on=date(2026, 1, 1 + i // 2)) for i in range(7)]
    first = listed(anna, limit=3)
    assert first["total"] == 7 and len(first["entries"]) == 3
    seen: list[int] = []
    for offset in (0, 3, 6):
        page = listed(anna, limit=3, offset=offset)
        assert (page["limit"], page["offset"], page["total"]) == (3, offset, 7)
        seen += [e["id"] for e in page["entries"]]
    assert sorted(seen) == sorted(made) and len(set(seen)) == 7
    assert seen == entry_ids(anna)
    past = listed(anna, limit=3, offset=500)
    assert past == {"entries": [], "total": 7, "limit": 3, "offset": 500}
    assert listed(anna, limit=500)["limit"] == 500


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 501}, {"limit": -1}, {"offset": -1}, {"limit": "x"}]
)
def test_limit_and_offset_bounds(anna: TestClient, params: dict[str, Any]):
    assert_envelope(anna.get(URL, params=params), 422, "validation_error")


@pytest.mark.parametrize("name", ["account_id", "category_id", "payee_id", "tag_id"])
@pytest.mark.parametrize("bad", [0, -1, 2**63, 10**20, "x"])
def test_every_id_parameter_is_bounded(anna: TestClient, name: str, bad: Any):
    err = assert_envelope(anna.get(URL, params={name: bad}), 422, "validation_error")
    assert any(name in d["location"] for d in err["details"])
    assert_envelope(anna.get(URL, params={name: [1, bad]}), 422, "validation_error")


@pytest.mark.parametrize("bad", [2**63, 10**20])
def test_offset_cannot_overflow(anna: TestClient, bad: int):
    assert_envelope(anna.get(URL, params={"offset": bad}), 422, "validation_error")


@pytest.mark.parametrize(
    "params",
    [
        {"amount_min": 5},
        {"amount_max": 5},
        {"amount_min": 5, "currency": "eur"},
        {"currency": "EU"},
        {"amount_min": -1, "currency": "EUR"},
        {"amount_max": "x", "currency": "EUR"},
        {"amount_min": 9, "amount_max": 1, "currency": "EUR"},
        {"direction": "sideways"},
        {"type": "bogus"},
        {"type": ["flow", "bogus"]},
        {"flag": "bogus"},
        {"from": "2026-13-01"},
        {"from": "yesterday"},
        {"from": "2026-03-02", "to": "2026-03-01"},
        {"q": ""},
        {"q": "   "},
        {"q": "x" * 201},
        {"category_descendants": "maybe"},
    ],
)
def test_invalid_values_are_422_envelopes(anna: TestClient, params: dict[str, Any]):
    r = anna.get(URL, params=params)
    err = assert_envelope(r, 422, "validation_error")
    assert err["details"]


def test_amount_bound_without_currency_names_the_currency_parameter(anna: TestClient):
    err = assert_envelope(anna.get(URL, params={"amount_min": 5}), 422, "validation_error")
    assert any("currency" in d["location"] for d in err["details"])


def test_the_search_text_is_never_echoed(anna: TestClient):
    secret = "SeCrEtSearch" + "x" * 200
    r = anna.get(URL, params={"q": secret})
    assert r.status_code == 422
    assert "SeCrEt" not in r.text


def test_search_wildcards_are_literal_over_http(anna: TestClient, api_engine: Engine, acct: int):
    hit = add(api_engine, acct, description="50% off")
    add(api_engine, acct, description="500 off")
    assert entry_ids(anna, q="50%") == [hit]


def test_unknown_parameters_are_ignored(anna: TestClient, api_engine: Engine, acct: int):
    add(api_engine, acct)
    assert listed(anna, nonsense="1")["total"] == 1


def test_it_writes_nothing_and_never_settles(
    anna: TestClient, api_engine: Engine, acct: int, monkeypatch: pytest.MonkeyPatch
):
    import importlib

    settle_module = importlib.import_module("app.core.settle.settle")
    calls: list[int] = []
    monkeypatch.setattr(settle_module, "settle", lambda *a, **k: calls.append(1))
    add(api_engine, acct, flags=("unclassified",))
    snapshot = (
        "SELECT (SELECT count(*) FROM ledger_entry), (SELECT sum(version) FROM ledger_entry),"
        " (SELECT count(*) FROM import_run)"
    )
    with api_engine.connect() as conn:
        before = conn.execute(text(snapshot)).one()
    listed(anna, q="x", flag="unclassified", tag_id=[1])
    with api_engine.connect() as conn:
        assert conn.execute(text(snapshot)).one() == before
    assert calls == []
    import app.api.routers.entries as entries_module

    assert not hasattr(entries_module, "settle")


def test_operation_ids_are_unique(client: TestClient):
    ids = [op.get("operationId") for item in client.app.openapi()["paths"].values() for op in item.values()]  # type: ignore[attr-defined]
    assert len(ids) == len(set(ids))


def test_user_authored_entries_carry_their_source_and_derived_have_none(
    anna: TestClient, api_engine: Engine, acct: int
):
    with api_engine.begin() as conn:
        user = seed.entry(conn, acct, purpose="Hand entered", description=None)  # user-authored
        derived = seed.derived(conn, acct)
    rows = {e["id"]: e for e in listed(anna)["entries"]}
    for got in (rows[user], anna.get(f"{URL}/{user}").json()):
        assert got["authored"] is True and got["display_text"] == "Hand entered"
        src = got["source"]
        assert src["purpose"] == "Hand entered" and src["amount"] == {"amount": -1000, "currency": "EUR"}
        assert src["source_format"] is None
        assert all(src[k] is None for k in ("counterparty_name", "counterparty_ref", "counterparty_bic"))
    assert rows[derived]["source"] is None and rows[derived]["authored"] is False
    assert anna.get(f"{URL}/{derived}").json()["source"] is None
    assert "counterparty_name" not in rows[user] and "purpose" not in rows[user]


def test_an_imported_source_without_an_instructed_amount_has_none(
    anna: TestClient, api_engine: Engine, acct: int
):
    e = add(api_engine, acct, counterparty="X", imported=True)
    src = anna.get(f"{URL}/{e}").json()["source"]
    assert src["instructed_amount"] is None and src["counterparty_name"] == "X"
    assert set(src) == {
        "amount", "counterparty_name", "counterparty_ref", "counterparty_bic", "purpose", "booking_text",
        "end_to_end_id", "mandate_ref", "instructed_amount", "source_format", "booking",
    }  # fmt: skip


def test_a_missing_entry_is_a_404_envelope_and_the_id_is_bounded(anna: TestClient):
    assert_envelope(anna.get(f"{URL}/999999"), 404, "not_found")
    for bad in (0, -1, 2**53 + 1, 2**70):
        assert_envelope(anna.get(f"{URL}/{bad}"), 422, "validation_error")
    assert_envelope(anna.get(f"{URL}/abc"), 422, "validation_error")


def test_the_single_read_needs_a_session(client: TestClient):
    assert_envelope(client.get(f"{URL}/1"), 401, "unauthenticated")


def test_the_search_still_reads_the_source_fields(anna: TestClient, api_engine: Engine, acct: int):
    hit = add(api_engine, acct, counterparty="Findable GmbH", imported=True)
    add(api_engine, acct, counterparty="Other", imported=True)
    assert entry_ids(anna, q="findable") == [hit]


def test_the_list_reads_sources_in_one_query(anna: TestClient, api_engine: Engine, acct: int):
    from sqlalchemy import event

    for i in range(6):
        add(api_engine, acct, counterparty=f"C{i}", imported=True)

    def statements() -> int:
        seen: list[str] = []
        event.listen(api_engine, "before_cursor_execute", lambda *a: seen.append(a[2]))
        listed(anna)
        return len([s for s in seen if "source_transaction" in s])

    # the page, its count, the pairs' sources and the documents: constant, however many rows
    assert statements() <= 4


def test_a_split_part_carries_the_whole_source_amount(
    anna: TestClient, api_engine: Engine, make_account: Any
):
    from tests.core.units.helpers import Bench

    with api_engine.begin() as conn:
        b = Bench(conn, make_account)
        s = b.source(amount=-300, parts=2)  # an imported source of -600 in two parts of -300
        p1, p2 = b.flow(s), b.flow(s, amount=-300)
    rows = {e["id"]: e for e in listed(anna)["entries"]}
    for i in (p1, p2):
        assert rows[i]["amount"]["amount"] == -300
        assert rows[i]["source"]["amount"] == {"amount": -600, "currency": "EUR"}


def test_rows_carry_derivation_unit_key_authored_and_partner(
    anna: TestClient, api_engine: Engine, make_account: Any
):
    from tests.core.units.helpers import Bench, keys

    with api_engine.begin() as conn:
        b = Bench(conn, make_account)
        s1, s2 = b.source(), b.source(b.b, amount=100, parts=2, authored=True)
        x, y = b.transfer(s1, derivation=keys(counter_account="rule")), b.transfer(s2)
        sib = b.flow(s2)
        b.pair(x, y)
        alone = b.flow(b.source(authored=True), derivation=keys(category="history"))
    rows = {e["id"]: e for e in listed(anna)["entries"]}
    assert rows[x]["derivation"] == {"counter_account": {"pass": "rule"}}
    assert (rows[x]["unit_key"], rows[y]["unit_key"], rows[sib]["unit_key"]) == (s1, s1, s1)  # via the pair
    assert rows[alone]["unit_key"] == rows[alone]["source_transaction_id"]
    assert (rows[x]["authored"], rows[y]["authored"], rows[alone]["authored"]) == (False, True, True)
    assert rows[y]["source"]["amount"] == {"amount": 200, "currency": "EUR"}  # the authored row
    assert rows[x]["source"] is not None
    assert rows[x]["partner"] == {
        "entry_id": y,
        "account_id": b.b,
        "booked_on": "2026-03-10",
        "amount": {"amount": 100, "currency": "EUR"},
    }
    assert rows[y]["partner"]["entry_id"] == x and rows[y]["partner"]["account_id"] == b.a
    assert rows[sib]["partner"] is None and rows[alone]["partner"] is None
    assert anna.get(f"{URL}/{x}").json() == rows[x]


def test_derived_entries_have_no_unit_and_are_not_authored(anna: TestClient, api_engine: Engine, acct: int):
    with api_engine.begin() as conn:
        d = seed.derived(conn, acct)
    (row,) = listed(anna)["entries"]
    assert row["id"] == d and (row["unit_key"], row["authored"], row["partner"], row["derivation"]) == (
        None,
        False,
        None,
        {},
    )
