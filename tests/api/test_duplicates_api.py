"""Provenance and marking or clearing duplicates over HTTP (architecture §4.1, spec §3.1, §5.6)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.core.balance.derived import recompute_derived
from tests.api.accounts_helpers import assert_envelope, seed_account, seed_manual
from tests.api.conftest import login
from tests.invariants.helpers import make_entry, make_run, make_source, pair

URL = "/api/ledger/sources"
DAY = date(2026, 3, 10)


@pytest.fixture
def anna(client: TestClient) -> TestClient:
    login(client)
    return client


@pytest.fixture
def acct(api_engine: Engine) -> int:
    return seed_account(api_engine)


def movement(
    engine: Engine, account: int, *, amount: int = -500, on: date = DAY, **kw: Any
) -> tuple[int, int]:
    """(source id, entry id) of an imported row that has its entry."""
    with engine.begin() as conn:
        src = make_source(conn, account, amount=amount, booked_on=on, **kw)
        return src, make_entry(conn, src)


def versions(engine: Engine, *ids: int) -> dict[str, int]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, version FROM ledger_entry WHERE id = ANY(:i)"), {"i": list(ids)})
        return {str(r.id): int(r.version) for r in rows}


def counts(engine: Engine) -> tuple[int, int]:
    with engine.connect() as conn:
        return (
            int(conn.execute(text("SELECT count(*) FROM ledger_entry")).scalar_one()),
            int(
                conn.execute(
                    text("SELECT count(*) FROM source_transaction WHERE duplicate_of IS NOT NULL")
                ).scalar_one()
            ),
        )


def transfer_pair(engine: Engine, a: int, b: int, *, amount: int = -50) -> tuple[int, int, int, int]:
    """(source out, entry out, source in, entry in): a confirmed transfer between accounts a and b."""
    with engine.begin() as conn:
        s_out = make_source(conn, a, amount=amount, booked_on=DAY)
        s_in = make_source(conn, b, amount=-amount, booked_on=DAY)
        e_out = make_entry(conn, s_out, type="transfer")
        e_in = make_entry(conn, s_in, type="transfer")
        conn.execute(
            text("UPDATE ledger_entry SET counter_account_id = :c WHERE id = :i"), {"c": b, "i": e_out}
        )
        conn.execute(
            text("UPDATE ledger_entry SET counter_account_id = :c WHERE id = :i"), {"c": a, "i": e_in}
        )
        pair(conn, e_out, e_in)
    return s_out, e_out, s_in, e_in


# ---- sessions --------------------------------------------------------------------------------


def test_the_routes_need_a_session(client: TestClient) -> None:
    assert_envelope(client.get(f"{URL}/1"), 401, "unauthenticated")
    assert_envelope(client.post(f"{URL}/1/duplicate", json={"of": 2}), 401, "unauthenticated")
    assert_envelope(client.post(f"{URL}/1/not-duplicate"), 401, "unauthenticated")


# ---- provenance ------------------------------------------------------------------------------


def test_provenance_of_an_imported_row_carries_the_columns_raw_and_the_run(
    anna: TestClient, api_engine: Engine, acct: int
) -> None:
    with api_engine.begin() as conn:
        instance = int(
            conn.execute(
                text(
                    "INSERT INTO importer_instance (importer, label, emits, access, settings)"
                    " VALUES ('csv', 'Giro CSV', ARRAY['transactions'], 'shared', '{}') RETURNING id"
                )
            ).scalar_one()
        )
        run = make_run(conn, acct, instance_id=instance)
        src = make_source(
            conn,
            acct,
            amount=-1250,
            booked_on=DAY,
            run_id=run,
            instance_id=instance,
            purpose="Coffee",
            columns={"counterparty_name": "Cafe", "booking_text": "CARD", "raw": '{"cells": ["x"]}'},
        )
        entry = make_entry(conn, src)
    body = anna.get(f"{URL}/{src}").json()
    assert body["id"] == src and body["account_id"] == acct and body["authored"] is False
    assert body["amount"] == {"amount": -1250, "currency": "EUR"}
    assert (body["counterparty_name"], body["purpose"], body["booking_text"]) == ("Cafe", "Coffee", "CARD")
    assert body["raw"] == {"cells": ["x"]}
    assert body["run"]["id"] == run and body["run"]["importer"] == "test"
    assert (body["run"]["instance_id"], body["run"]["instance_label"]) == (instance, "Giro CSV")
    assert body["run"]["started_at"]
    assert body["duplicate_of"] is None and body["entry_id"] == entry


def test_provenance_of_an_authored_row_has_no_run(anna: TestClient, api_engine: Engine, acct: int) -> None:
    src, _ = movement(api_engine, acct, importer=None)
    body = anna.get(f"{URL}/{src}").json()
    assert body["authored"] is True and body["run"] is None and body["source_format"] is None


def test_provenance_of_a_duplicate_names_the_row_it_duplicates(
    anna: TestClient, api_engine: Engine, acct: int
) -> None:
    original, _ = movement(api_engine, acct, amount=-40)
    with api_engine.begin() as conn:
        dup = make_source(conn, acct, amount=-40, booked_on=date(2026, 3, 11), duplicate_of=original)
    body = anna.get(f"{URL}/{dup}").json()
    assert body["entry_id"] is None
    assert body["duplicate_of"] == {
        "id": original,
        "booked_on": "2026-03-10",
        "amount": {"amount": -40, "currency": "EUR"},
    }


def test_provenance_of_a_missing_row_is_not_found(anna: TestClient) -> None:
    assert_envelope(anna.get(f"{URL}/999999"), 404, "not_found")
    assert_envelope(anna.get(f"{URL}/0"), 422, "validation_error")


# ---- marking ---------------------------------------------------------------------------------


def test_a_dry_run_reports_the_consequences_and_writes_nothing(
    anna: TestClient, api_engine: Engine, acct: int
) -> None:
    other = seed_account(api_engine, "Savings")
    s_out, e_out, s_in, e_in = transfer_pair(api_engine, acct, other)
    original, _ = movement(api_engine, acct, amount=-50)
    before = counts(api_engine)
    r = anna.post(f"{URL}/{s_out}/duplicate", json={"of": original, "dry_run": True})
    assert r.status_code == 200, r.text
    out = r.json()
    assert counts(api_engine) == before
    assert (out["dry_run"], out["source_transaction_id"], out["of"]) == (True, s_out, original)
    assert out["removed_entry_ids"] == [e_out] and out["partner_entry_ids"] == [e_in]
    assert {v["entry_id"] for v in out["versions"]} == {e_out, e_in}
    assert [p["id"] for p in out["partners"]] == [e_in]
    assert out["partners"][0]["version"] == versions(api_engine, e_in)[str(e_in)]
    assert out["settle"] is None and out["units"] == []
    assert s_in  # the partner's own row is untouched


def test_a_real_mark_with_the_previews_versions_answers_with_everything_it_touched(
    anna: TestClient, api_engine: Engine, acct: int
) -> None:
    other = seed_account(api_engine, "Savings")
    s_out, e_out, _, e_in = transfer_pair(api_engine, acct, other)
    original, _ = movement(api_engine, acct, amount=-50)
    probe = anna.post(f"{URL}/{s_out}/duplicate", json={"of": original, "dry_run": True}).json()
    seen = {str(v["entry_id"]): v["version"] for v in probe["versions"]}
    r = anna.post(f"{URL}/{s_out}/duplicate", json={"of": original, "expected_versions": seen})
    assert r.status_code == 200, r.text
    out = r.json()
    assert (
        out["dry_run"] is False and out["removed_entry_ids"] == [e_out] and out["partner_entry_ids"] == [e_in]
    )
    assert out["settle"] is not None and out["settle"]["error"] is None
    assert [p["id"] for p in out["partners"]] == [e_in]
    assert out["partners"][0]["version"] > seen[str(e_in)]  # unpaired: it moved
    assert [u["entry_ids"] for u in out["units"]] == [[e_in]]
    with api_engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT duplicate_of FROM source_transaction WHERE id = :i"), {"i": s_out}
            ).scalar_one()
            == original
        )
        assert (
            conn.execute(text("SELECT count(*) FROM ledger_entry WHERE id = :i"), {"i": e_out}).scalar_one()
            == 0
        )
    assert anna.get("/api/maintenance/check").json()["ok"] is True


def test_marking_reports_rows_it_repoints_and_derived_entries_that_move(
    anna: TestClient, api_engine: Engine, acct: int
) -> None:
    seed_manual(api_engine, acct, date(2026, 3, 31), 1000)
    original, _ = movement(api_engine, acct, amount=-30, on=date(2026, 3, 5))
    marked, marked_entry = movement(api_engine, acct, amount=-30, on=date(2026, 3, 6))
    with api_engine.begin() as conn:
        follower = make_source(conn, acct, amount=-30, booked_on=date(2026, 3, 7), duplicate_of=marked)
        recompute_derived(conn, acct)  # the rows above were inserted directly
    probe = anna.post(f"{URL}/{marked}/duplicate", json={"of": original, "dry_run": True}).json()
    assert probe["repointed_source_ids"] == [follower]
    (change,) = probe["derived_changes"]  # the opening absorbs what the duplicate no longer moves
    assert change["account_id"] == acct
    assert change["before"][0]["amount"] == {"amount": 1060, "currency": "EUR"}
    assert change["after"][0]["amount"] == {"amount": 1030, "currency": "EUR"}
    seen = {str(v["entry_id"]): v["version"] for v in probe["versions"]}
    done = anna.post(f"{URL}/{marked}/duplicate", json={"of": original, "expected_versions": seen}).json()
    assert done["repointed_source_ids"] == [follower] and done["removed_entry_ids"] == [marked_entry]
    with api_engine.connect() as conn:
        got = conn.execute(
            text("SELECT duplicate_of FROM source_transaction WHERE id = :i"), {"i": follower}
        ).scalar_one()
    assert got == original


def test_a_real_mark_without_the_versions_of_everything_it_writes_conflicts(
    anna: TestClient, api_engine: Engine, acct: int
) -> None:
    src, entry = movement(api_engine, acct)
    original, _ = movement(api_engine, acct)
    before = counts(api_engine)
    r = anna.post(f"{URL}/{src}/duplicate", json={"of": original, "expected_versions": {str(entry): 99}})
    err = assert_envelope(r, 409, "conflict")
    assert err["details"]["entry_ids"] == [entry]
    r = anna.post(f"{URL}/{src}/duplicate", json={"of": original, "expected_versions": {}})
    assert_envelope(r, 409, "conflict")
    assert counts(api_engine) == before


@pytest.mark.parametrize(
    ("case", "status", "code", "reason"),
    [
        ("self", 422, "invalid_duplicate", "of_self"),
        ("authored", 422, "invalid_duplicate", "user_authored"),
        ("authored_of", 422, "invalid_duplicate", "user_authored"),
        ("cross_account", 422, "invalid_duplicate", "cross_account"),
        ("already", 409, "conflict", "already_duplicate"),
        ("chain", 409, "conflict", "duplicate_chain"),
    ],
)
def test_marking_refusals(
    anna: TestClient, api_engine: Engine, acct: int, case: str, status: int, code: str, reason: str
) -> None:
    other = seed_account(api_engine, "Savings")
    src, _ = movement(api_engine, acct)
    twin, _ = movement(api_engine, acct)
    authored, _ = movement(api_engine, acct, importer=None)
    foreign, _ = movement(api_engine, other)
    marked_first, _ = movement(api_engine, acct)
    with api_engine.begin() as conn:
        dup = make_source(conn, acct, duplicate_of=marked_first)
    target = {
        "self": (src, src),
        "authored": (authored, twin),
        "authored_of": (src, authored),
        "cross_account": (src, foreign),
        "already": (dup, twin),
        "chain": (src, dup),
    }[case]
    err = assert_envelope(anna.post(f"{URL}/{target[0]}/duplicate", json={"of": target[1]}), status, code)
    assert err["details"]["reason"] == reason


def test_marking_a_missing_row_is_not_found(anna: TestClient, api_engine: Engine, acct: int) -> None:
    src, _ = movement(api_engine, acct)
    assert_envelope(anna.post(f"{URL}/999999/duplicate", json={"of": src}), 404, "not_found")
    assert_envelope(anna.post(f"{URL}/{src}/duplicate", json={"of": 999999}), 404, "not_found")


@pytest.mark.parametrize("bad", [{}, {"of": 0}, {"of": 1, "extra": 1}, {"of": 1, "dry_run": "maybe"}])
def test_the_body_is_strict(anna: TestClient, bad: dict[str, Any]) -> None:
    assert_envelope(anna.post(f"{URL}/1/duplicate", json=bad), 422, "validation_error")


# ---- clearing --------------------------------------------------------------------------------


def test_clearing_a_duplicate_gives_the_row_one_entry_and_answers_with_it(
    anna: TestClient, api_engine: Engine, acct: int
) -> None:
    original, _ = movement(api_engine, acct, amount=-40)
    with api_engine.begin() as conn:
        dup = make_source(conn, acct, amount=-40, booked_on=date(2026, 3, 11), duplicate_of=original)
    r = anna.post(f"{URL}/{dup}/not-duplicate")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["source_transaction_id"] == dup and out["removed_entry_ids"] == []
    (entry,) = out["entries"]
    assert entry["amount"] == {"amount": -40, "currency": "EUR"}
    assert out["anchor_entry_id"] == entry["id"] and [u["entry_ids"] for u in out["units"]] == [[entry["id"]]]
    assert out["settle"]["error"] is None
    assert anna.get(f"{URL}/{dup}").json()["duplicate_of"] is None
    assert anna.get("/api/maintenance/check").json()["ok"] is True


def test_clearing_refusals(anna: TestClient, api_engine: Engine, acct: int) -> None:
    src, _ = movement(api_engine, acct)
    authored, _ = movement(api_engine, acct, importer=None)
    assert assert_envelope(anna.post(f"{URL}/{src}/not-duplicate"), 409, "conflict")["details"] == {
        "reason": "not_a_duplicate"
    }
    assert_envelope(anna.post(f"{URL}/{authored}/not-duplicate"), 409, "conflict")  # never a duplicate
    assert_envelope(anna.post(f"{URL}/999999/not-duplicate"), 404, "not_found")
