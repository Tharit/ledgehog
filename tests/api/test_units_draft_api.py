"""`POST /api/units/preview` and `POST /api/units/commit`: shapes, errors and auth (architecture §4.1)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.api.accounts_helpers import assert_envelope
from tests.api.conftest import login
from tests.core.units.conftest import build_scene
from tests.core.units.scene import Scene

D = date(2026, 3, 10)
PREVIEW = "/api/units/preview"
COMMIT = "/api/units/commit"


@pytest.fixture
def anna(client: TestClient) -> TestClient:
    login(client)
    return client


@pytest.fixture
def scene(api_engine: Engine, make_account: Callable[..., int]) -> Scene:
    return build_scene(api_engine, make_account)


def test_both_need_a_session(client: TestClient) -> None:
    for url in (PREVIEW, COMMIT):
        assert_envelope(client.post(url, json={"anchor_entry_id": 1}), 401, "unauthenticated")


def test_preview_shape(anna: TestClient, scene: Scene) -> None:
    scene.confirmed("REWE", "Food")
    _s, (e,) = scene.movement(-700, counterparty="REWE", description="weekly")
    scene.settle()
    r = anna.post(PREVIEW, json={"anchor_entry_id": e})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"state", "units", "rows", "splits", "problems", "consequences", "versions"}
    assert body["state"] == {"confirmed": True, "reasons": []}
    assert body["problems"] == [] and body["consequences"] == []
    assert body["versions"] == {str(e): 1}
    (row,) = body["rows"]
    assert set(row) == set(
        "id version source_transaction_id unit_key in_unit original account_id booked_on value_on amount"
        " description note tag_ids counterpart_entry_id fields review_flags derivation stored".split()
        + ["transfer"]
    )
    assert row["amount"] == {"amount": -700, "currency": "EUR"} and row["in_unit"] and row["original"]
    cat = row["fields"]["category"]
    assert cat["value"] == scene.cats["Food"] and cat["is_proposal"] is True
    assert cat["key"]["pass"] == "history" and cat["key"]["basis"]
    assert cat["commit_key"]["pass"] == "user" and cat["commit_key"]["basis"]["pass"] == "history"
    assert cat["stored"]["value"] == scene.cats["Food"] and cat["stored"]["key"]["pass"] == "history"
    assert row["fields"]["type"]["is_proposal"] is True
    assert body["splits"] == [
        {
            "source_transaction_id": row["source_transaction_id"],
            "source_amount": {"amount": -700, "currency": "EUR"},
            "residual_entry_id": e,
            "residual_amount": {"amount": -700, "currency": "EUR"},
            "entry_ids": [e],
        }
    ]
    assert body["units"][0]["entry_ids"] == [e]


def test_preview_of_a_split_echoes_temporary_ids_and_lists_consequences(
    anna: TestClient, scene: Scene
) -> None:
    _s, (e,) = scene.movement(-1000)
    before = scene.fingerprint()
    r = anna.post(
        PREVIEW,
        json={
            "anchor_entry_id": e,
            "entries": [{"id": -7, "amount": -300, "source_entry_id": e}],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [x["id"] for x in body["rows"]] == [e, -7]
    new = body["rows"][1]
    assert new["version"] is None and new["stored"] is None and new["fields"]["type"]["value"] == "flow"
    assert body["units"][0]["entry_ids"] == [e, -7]
    assert {(c["entry_id"], c["kind"]) for c in body["consequences"]} == {(-7, "created"), (e, "changed")}
    created = next(c for c in body["consequences"] if c["kind"] == "created")
    assert created["version"] is None and created["row"]["id"] == -7
    assert body["splits"][0]["residual_amount"] == {"amount": -700, "currency": "EUR"}
    assert scene.fingerprint() == before  # a preview writes nothing


def test_preview_reports_problems_as_codes(anna: TestClient, scene: Scene) -> None:
    _s, (e,) = scene.movement(-1000)
    r = anna.post(
        PREVIEW, json={"anchor_entry_id": e, "entries": [{"id": -1, "amount": -1000, "source_entry_id": e}]}
    )
    assert r.status_code == 200
    assert r.json()["problems"] == [{"code": "residual_zero", "entry_id": e, "field": None, "detail": {}}]


def test_preview_of_a_deleted_entry_carries_the_row_as_it_was(anna: TestClient, scene: Scene) -> None:
    _s, (a, b) = scene.movement(-600, -400)
    r = anna.post(PREVIEW, json={"anchor_entry_id": a, "removed_entry_ids": [b]})
    deleted = next(c for c in r.json()["consequences"] if c["kind"] == "deleted")
    assert deleted["entry_id"] == b and deleted["row"]["amount"] == {"amount": -400, "currency": "EUR"}
    assert deleted["version"] == 1


def test_a_draft_that_is_nonsense_is_a_422_with_its_code(anna: TestClient, scene: Scene) -> None:
    _s, (e,) = scene.movement(-1000)
    forged = {
        "id": e,
        "category": {"mode": "fixed", "value": 1, "shown_basis": {"pass": "rule", "basis": {}}},
    }
    r = anna.post(PREVIEW, json={"anchor_entry_id": e, "entries": [forged]})
    assert_envelope(r, 422, "invalid_draft")
    assert r.json()["error"]["details"]["code"] == "invalid_basis"
    r = anna.post(PREVIEW, json={"anchor_entry_id": e, "removed_entry_ids": [e]})
    assert r.json()["error"]["details"] == {"code": "anchor_removed", "entry_id": e, "field": None}
    r = anna.post(PREVIEW, json={"anchor_entry_id": e, "entries": [{"id": 4242}]})
    assert r.json()["error"]["details"]["code"] == "unknown_entry"


def test_unknown_fields_and_bad_ids_are_validation_errors(anna: TestClient) -> None:
    assert_envelope(anna.post(PREVIEW, json={"anchor_entry_id": 1, "surprise": 1}), 422, "validation_error")
    assert_envelope(anna.post(PREVIEW, json={"anchor_entry_id": 0}), 422, "validation_error")
    bad = {"anchor_entry_id": 1, "entries": [{"id": 1, "type": {"mode": "fixed", "value": "flow", "x": 1}}]}
    assert_envelope(anna.post(PREVIEW, json=bad), 422, "validation_error")
    mode = {"anchor_entry_id": 1, "entries": [{"id": 1, "type": {"mode": "maybe"}}]}
    assert_envelope(anna.post(PREVIEW, json=mode), 422, "validation_error")


def test_preview_of_a_missing_or_derived_entry_is_404(anna: TestClient) -> None:
    assert_envelope(anna.post(PREVIEW, json={"anchor_entry_id": 31337}), 404, "not_found")
    assert_envelope(anna.post(COMMIT, json={"anchor_entry_id": 31337}), 404, "not_found")


def test_commit_shape_for_a_split(anna: TestClient, scene: Scene) -> None:
    food = scene.category("Food")
    _s, (e,) = scene.movement(-1000)
    versions = scene.versions(e)
    r = anna.post(
        COMMIT,
        json={
            "anchor_entry_id": e,
            "entries": [
                {"id": e, "category": {"mode": "fixed", "value": food}},
                {
                    "id": -3,
                    "amount": -250,
                    "source_entry_id": e,
                    "category": {"mode": "fixed", "value": food},
                },
            ],
            "versions": {str(k): v for k, v in versions.items()},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {
        "created", "removed_entry_ids", "entries", "other_entry_ids", "truncated", "units", "consequences",
        "settle",
    }  # fmt: skip
    new = body["created"]["-3"]
    assert new > e and body["removed_entry_ids"] == []
    assert sorted(x["id"] for x in body["entries"]) == [e, new]
    by_id = {x["id"]: x for x in body["entries"]}
    assert by_id[e]["amount"]["amount"] == -750 and by_id[new]["amount"]["amount"] == -250
    assert by_id[e]["derivation"]["category"] == {"pass": "user"}
    assert body["units"] == [
        {"anchor_entry_id": e, "entry_ids": [e, new], "state": {"confirmed": True, "reasons": []}}
    ]
    assert {(c["entry_id"], c["kind"]) for c in body["consequences"]} == {(new, "created"), (e, "changed")}
    assert body["settle"]["error"] is None and body["truncated"] is False


def test_commit_errors(anna: TestClient, scene: Scene) -> None:
    _s, (e,) = scene.movement(-1000)
    versions = {str(k): v for k, v in scene.versions(e).items()}
    # an invalid result: the code of the problem, and all of them in the details
    r = anna.post(
        COMMIT,
        json={
            "anchor_entry_id": e,
            "entries": [{"id": -1, "amount": -1000, "source_entry_id": e}],
            "versions": versions,
        },
    )
    assert_envelope(r, 422, "residual_zero")
    assert r.json()["error"]["details"]["problems"][0]["entry_id"] == e
    # a version that moved, and one that is missing: 409 conflict naming the entries
    assert_envelope(anna.post(COMMIT, json={"anchor_entry_id": e, "versions": {str(e): 9}}), 409, "conflict")
    r = anna.post(COMMIT, json={"anchor_entry_id": e})
    assert_envelope(r, 409, "conflict")
    assert r.json()["error"]["details"] == {"entry_ids": [e]}
    # a category that does not exist any more
    r = anna.post(
        COMMIT,
        json={
            "anchor_entry_id": e,
            "entries": [{"id": e, "category": {"mode": "fixed", "value": 4040}}],
            "versions": versions,
        },
    )
    assert_envelope(r, 409, "stale_reference")
    assert r.json()["error"]["details"] == {"field": "category_id", "entity": "category", "id": 4040}
    assert scene.row(e).category_id is None and scene.row(e).version == 1


def test_commit_accepts_a_proposal_and_the_unit_is_confirmed_by_settling(
    anna: TestClient, scene: Scene
) -> None:
    scene.confirmed("REWE", "Food")
    _s, (e,) = scene.movement(-700, counterparty="REWE")
    scene.settle()
    r = anna.post(COMMIT, json={"anchor_entry_id": e, "versions": {str(e): 1}})
    assert r.status_code == 200, r.text
    (row,) = r.json()["entries"]
    assert row["review_flags"] == [] and row["derivation"]["category"]["basis"]["pass"] == "history"
    assert r.json()["units"][0]["state"]["confirmed"] is True


# ---- tags are part of the draft -----------------------------------------------------------------


def test_a_tag_change_previews_and_commits_without_bumping_the_version(
    anna: TestClient, scene: Scene
) -> None:
    scene.confirmed("REWE", "Food")
    _s, (e,) = scene.movement(-700, counterparty="REWE")
    t1, t2 = scene.tag("a"), scene.tag("b")
    scene.tag_entry(e, t1)
    scene.settle()
    anna.post(COMMIT, json={"anchor_entry_id": e, "versions": {str(e): 1}})  # settled into its final state
    v = scene.row(e).version
    body = {
        "anchor_entry_id": e,
        "entries": [{"id": e, "tags": {"add": [t2, t2], "remove": [t1]}}],
        "versions": {str(e): v},
    }
    p = anna.post(PREVIEW, json=body)
    assert p.status_code == 200, p.text
    assert p.json()["rows"][0]["tag_ids"] == [t2]
    r = anna.post(COMMIT, json=body)
    assert r.status_code == 200, r.text
    (row,) = [x for x in r.json()["entries"] if x["id"] == e]
    assert row["tag_ids"] == [t2] and row["version"] == v
    assert scene.row(e).version == v and scene.tags_of(e) == (t2,)


def test_a_tag_in_both_lists_is_invalid_draft_and_an_unknown_tag_is_stale(
    anna: TestClient, scene: Scene
) -> None:
    _s, (e,) = scene.movement(-700)
    t = scene.tag("a")
    for url in (PREVIEW, COMMIT):
        r = anna.post(
            url,
            json={"anchor_entry_id": e, "entries": [{"id": e, "tags": {"add": [t], "remove": [t]}}]},
        )
        assert_envelope(r, 422, "invalid_draft")
        assert r.json()["error"]["details"]["code"] == "tag_conflict"
    for url in (PREVIEW, COMMIT):
        r = anna.post(
            url,
            json={
                "anchor_entry_id": e,
                "entries": [{"id": e, "tags": {"add": [9999]}}],
                "versions": {str(e): 1},
            },
        )
        assert_envelope(r, 409, "stale_reference")
        assert r.json()["error"]["details"] == {"field": "entries[0].tags.add", "entity": "tag", "id": 9999}
    assert scene.tags_of(e) == ()
    r = anna.post(PREVIEW, json={"anchor_entry_id": e, "entries": [{"id": e, "tags": {"x": []}}]})
    assert r.status_code == 422


# ---- transfer legs: state, partner, offers (spec §5.7) ----------------------------------------------------


def _leg(scene: Scene, amount: int, account: int, *, counter: int | None = None, day: int = 0) -> int:
    from datetime import timedelta

    keys = {"type": {"pass": "user"}, **({"counter_account": {"pass": "user"}} if counter else {})}
    _s, (e,) = scene.movement(
        amount,
        account=account,
        on=D + timedelta(days=day),
        type="transfer",
        counter_account_id=counter,
        derivation=json.dumps(keys),
        authored=True,
    )
    return e


def test_a_transfer_row_carries_its_state_partner_and_offers(anna: TestClient, scene: Scene) -> None:
    e = _leg(scene, -1000, scene.checking)
    untyped = scene.movement(1000, account=scene.savings, authored=True)[1][0]
    other = _leg(scene, 900, scene.cash)
    body = anna.post(PREVIEW, json={"anchor_entry_id": e}).json()
    (row,) = body["rows"]
    t = row["transfer"]
    assert set(t) == {"state", "waiting_for", "needs_account", "partner", "offers", "proposal", "has_more"}
    assert (t["state"], t["waiting_for"], t["needs_account"], t["partner"]) == ("unmatched", None, None, None)
    assert body["state"] == {"confirmed": False, "reasons": ["unmatched_transfer"]}
    assert t["proposal"] == {"kind": "entry", "entry_id": untyped} and t["has_more"] is False
    first, second = t["offers"]
    assert set(first) == set(
        "kind entry_id account_id booked_on amount description exact proposed paired_with".split()
        + ["effect", "counter_leg"]
    )
    assert first["kind"] == "untyped_entry" and first["exact"] and first["proposed"]
    assert first["amount"] == {"amount": 1000, "currency": "EUR"}
    assert first["effect"] == {"types_as_transfer": True, "fee": None, "breaks_pair_with": []}
    assert second["entry_id"] == other and second["kind"] == "open_leg" and not second["exact"]
    assert second["effect"]["fee"] == {
        "larger_entry_id": e,
        "difference": {"amount": 100, "currency": "EUR"},
    }
    assert second["paired_with"] is None and second["counter_leg"] is None


def test_the_counter_leg_offer_and_a_partner_shape(anna: TestClient, scene: Scene) -> None:
    e = _leg(scene, -1000, scene.checking, counter=scene.cash)
    (offer,) = anna.post(PREVIEW, json={"anchor_entry_id": e}).json()["rows"][0]["transfer"]["offers"]
    assert offer["kind"] == "counter_leg" and offer["entry_id"] is None and offer["proposed"]
    assert offer["counter_leg"]["amount"] == {"amount": 1000, "currency": "EUR"}
    assert offer["counter_leg"]["needs_received_amount"] is False
    cross = _leg(scene, -1000, scene.checking, counter=scene.usd)
    (offer,) = anna.post(PREVIEW, json={"anchor_entry_id": cross}).json()["rows"][0]["transfer"]["offers"]
    assert offer["amount"] is None and offer["counter_leg"]["amount"] is None
    assert offer["counter_leg"]["needs_received_amount"] is True
    # a paired leg shows its partner
    x = _leg(scene, 1000, scene.cash, counter=scene.checking)
    body = anna.post(PREVIEW, json={"anchor_entry_id": e}).json()
    assert {r["id"] for r in body["rows"]} == {e, x}
    row = next(r for r in body["rows"] if r["id"] == e)
    assert row["transfer"]["state"] == "paired"
    assert row["transfer"]["partner"]["entry_id"] == x
    assert row["transfer"]["partner"]["amount"] == {"amount": 1000, "currency": "EUR"}
    assert set(body["versions"]) == {str(e), str(x)}


def test_window_days_is_bounded_one_to_ninety(anna: TestClient, scene: Scene) -> None:
    e = _leg(scene, -1000, scene.checking, counter=scene.savings)
    far = _leg(scene, 900, scene.savings, day=30)
    for bad in (0, -1, 91, 1000):
        r = anna.post(f"{PREVIEW}?window_days={bad}", json={"anchor_entry_id": e})
        assert_envelope(r, 422, "validation_error")
    r = anna.post(f"{PREVIEW}?window_days=abc", json={"anchor_entry_id": e})
    assert_envelope(r, 422, "validation_error")
    ids = lambda r: [o["entry_id"] for o in r.json()["rows"][0]["transfer"]["offers"]]  # noqa: E731
    assert far not in ids(anna.post(PREVIEW, json={"anchor_entry_id": e}))
    assert far not in ids(anna.post(f"{PREVIEW}?window_days=29", json={"anchor_entry_id": e}))
    for ok in (30, 90):
        r = anna.post(f"{PREVIEW}?window_days={ok}", json={"anchor_entry_id": e})
        assert r.status_code == 200 and far in ids(r)
    assert anna.post(f"{PREVIEW}?window_days=1", json={"anchor_entry_id": e}).status_code == 200


def test_waiting_and_needs_account_shapes(anna: TestClient, scene: Scene) -> None:
    from tests.invariants.helpers import link_account, make_instance

    scene.tx(lambda c: link_account(c, scene.savings, make_instance(c)))
    waiting = _leg(scene, -1000, scene.checking, counter=scene.savings)
    body = anna.post(PREVIEW, json={"anchor_entry_id": waiting}).json()
    t = body["rows"][0]["transfer"]
    assert t["state"] == "waiting" and t["waiting_for"] == {
        "account_id": scene.savings,
        "synced_through": None,
    }
    assert body["state"] == {"confirmed": False, "reasons": ["waiting_for_partner"]}
    _s, (needs,) = scene.movement(
        -500,
        type="transfer",
        derivation=json.dumps({"type": {"pass": "user"}}),
        instructed=(-600, "GBP"),
        authored=True,
    )
    t = anna.post(PREVIEW, json={"anchor_entry_id": needs}).json()["rows"][0]["transfer"]
    assert t["state"] == "needs_account" and t["needs_account"] == {"currency": "GBP"}
