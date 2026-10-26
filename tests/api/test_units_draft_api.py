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
        " description note source_text tag_ids counterpart_entry_id fields review_flags derivation"
        " stored".split()
        + ["transfer", "counter_leg_for", "booking", "booking_for"]
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
    assert r.json()["problems"] == [
        {"code": "residual_zero", "entry_id": e, "field": None, "detail": {}, "suggested_split": None}
    ]


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
    # the exact open offer is the proposal and the preview takes it as the pick: the leg shows the pair
    row = next(r for r in body["rows"] if r["id"] == e)
    assert {r["id"] for r in body["rows"]} == {e, untyped}
    t = row["transfer"]
    assert set(t) == {
        "state",
        "waiting_for",
        "needs_account",
        "partner",
        "offers",
        "proposal",
        "has_more",
        "proposed_pick",
        "proposed_counter_leg",
    }
    assert (t["state"], t["waiting_for"], t["needs_account"]) == ("paired", None, None)
    assert t["partner"]["entry_id"] == untyped and t["proposed_pick"] == {"entry_id": untyped}
    assert body["state"] == {"confirmed": True, "reasons": []}
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


# ---- picking a partner (spec §5.7) ----------------------------------------------------------------------


def test_a_pick_previews_and_commits_through_the_api(anna: TestClient, scene: Scene) -> None:
    e = _leg(scene, -1000, scene.checking)
    x = _leg(scene, 1000, scene.savings, day=2)
    _leg(scene, 1000, scene.savings, day=1)  # the nearer exact leg is the proposal; the pick overrides it
    draft = {"anchor_entry_id": e, "entries": [{"id": e, "pairing": {"mode": "pick", "partner_entry_id": x}}]}
    body = anna.post(PREVIEW, json=draft).json()
    assert body["problems"] == [] and {r["id"] for r in body["rows"]} == {e, x}
    row = next(r for r in body["rows"] if r["id"] == e)
    assert row["transfer"]["state"] == "paired" and row["transfer"]["proposed_pick"] is None
    assert row["transfer"]["partner"]["entry_id"] == x and row["counterpart_entry_id"] == x
    assert row["derivation"]["counterpart"] == {"pass": "user", "basis": {}}
    assert body["versions"] == {str(e): 1, str(x): 1}
    r = anna.post(COMMIT, json={**draft, "versions": body["versions"]})
    assert r.status_code == 200, r.text
    assert {u["state"]["confirmed"] for u in r.json()["units"]} == {True}
    assert {en["id"] for en in r.json()["entries"]} >= {e, x}
    assert scene.row(e).counterpart_entry_id == x


def test_the_proposal_is_in_the_preview_and_a_commit_accepts_it(anna: TestClient, scene: Scene) -> None:
    e = _leg(scene, -1000, scene.checking)
    x = _leg(scene, 1000, scene.savings)
    body = anna.post(PREVIEW, json={"anchor_entry_id": e}).json()
    row = next(r for r in body["rows"] if r["id"] == e)
    assert row["transfer"]["proposed_pick"] == {"entry_id": x} and row["transfer"]["state"] == "paired"
    assert body["state"]["confirmed"] is True
    assert anna.post(COMMIT, json={"anchor_entry_id": e, "versions": body["versions"]}).status_code == 200
    assert scene.row(e).counterpart_entry_id == x
    assert scene.row(e).derivation["counterpart"] == {"pass": "user", "basis": {}}


def test_an_unequal_pick_names_the_split_that_fixes_it(anna: TestClient, scene: Scene) -> None:
    e = _leg(scene, -1000, scene.checking)
    x = _leg(scene, 900, scene.savings)
    draft = {"anchor_entry_id": e, "entries": [{"id": e, "pairing": {"mode": "pick", "partner_entry_id": x}}]}
    body = anna.post(PREVIEW, json=draft).json()
    (problem,) = body["problems"]
    assert problem["code"] == "pair_unequal" and problem["detail"]["difference"] == -100
    assert problem["suggested_split"] == {"source_entry_id": e, "amount": {"amount": -100, "currency": "EUR"}}
    r = anna.post(COMMIT, json={**draft, "versions": body["versions"]})
    assert_envelope(r, 422, "pair_unequal")
    assert scene.row(e).counterpart_entry_id is None


def test_a_far_pick_commits_after_a_widened_preview(anna: TestClient, scene: Scene) -> None:
    e = _leg(scene, -1000, scene.checking, counter=scene.savings)
    far = _leg(scene, 1000, scene.savings, counter=scene.checking, day=20)
    draft = {
        "anchor_entry_id": e,
        "entries": [{"id": e, "pairing": {"mode": "pick", "partner_entry_id": far}}],
    }
    narrow = anna.post(PREVIEW, json=draft).json()
    assert [p["code"] for p in narrow["problems"]] == ["partner_not_offered"]
    wide = anna.post(PREVIEW + "?window_days=30", json=draft).json()
    assert wide["problems"] == []
    # the commit checks a pick against the cap (90 days), with or without the window
    r = anna.post(COMMIT, json={**draft, "versions": wide["versions"]})
    assert r.status_code == 200, r.text
    assert scene.row(e).counterpart_entry_id == far


def test_a_pick_beyond_ninety_days_is_refused_in_preview_and_commit(anna: TestClient, scene: Scene) -> None:
    e = _leg(scene, -1000, scene.checking, counter=scene.savings)
    far = _leg(scene, 1000, scene.savings, counter=scene.checking, day=91)
    draft = {
        "anchor_entry_id": e,
        "entries": [{"id": e, "pairing": {"mode": "pick", "partner_entry_id": far}}],
    }
    body = anna.post(PREVIEW + "?window_days=90", json=draft).json()
    assert [p["code"] for p in body["problems"]] == ["partner_not_offered"]
    r = anna.post(COMMIT + "?window_days=90", json={**draft, "versions": {str(e): 1, str(far): 1}})
    assert_envelope(r, 422, "partner_not_offered")
    assert scene.row(e).counterpart_entry_id is None


def test_a_malformed_pairing_is_a_422(anna: TestClient, scene: Scene) -> None:
    _s, (flow,) = scene.movement(-1000, type="flow", derivation=json.dumps({"type": {"pass": "user"}}))
    e = _leg(scene, -1000, scene.checking)
    x = _leg(scene, 1000, scene.savings)
    cases: list[tuple[dict[str, object], str]] = [
        (
            {
                "anchor_entry_id": flow,
                "entries": [{"id": flow, "pairing": {"mode": "pick", "partner_entry_id": x}}],
            },
            "pairing_not_transfer",
        ),
        (
            {
                "anchor_entry_id": e,
                "entries": [{"id": e, "pairing": {"mode": "pick", "partner_entry_id": -3}}],
            },
            "invalid_pairing",
        ),
        ({"anchor_entry_id": e, "entries": [{"id": e, "pairing": {"mode": "pick"}}]}, "invalid_pairing"),
        (
            {
                "anchor_entry_id": e,
                "entries": [{"id": e, "pairing": {"mode": "keep", "partner_entry_id": x}}],
            },
            "invalid_pairing",
        ),
        (
            {
                "anchor_entry_id": e,
                "entries": [{"id": -1, "amount": -5, "source_entry_id": e, "pairing": {"mode": "reresolve"}}],
            },
            "invalid_pairing",
        ),
    ]
    for body, code in cases:
        for url in (PREVIEW, COMMIT):
            r = anna.post(url, json=body)
            assert_envelope(r, 422, "invalid_draft")
            assert r.json()["error"]["details"]["code"] == code
    r = anna.post(PREVIEW, json={"anchor_entry_id": e, "entries": [{"id": e, "pairing": {"mode": "swap"}}]})
    assert r.status_code == 422
    r = anna.post(
        PREVIEW, json={"anchor_entry_id": e, "entries": [{"id": e, "pairing": {"is_proposal": True}}]}
    )
    assert r.status_code == 422  # a client cannot mark a pick as a proposal


# ---- counter-legs (spec §5.7) ---------------------------------------------------------------------------


def _counter_leg_draft(e: int, temp: int = -1, received: int | None = None) -> dict[str, object]:
    leg: dict[str, object] = {"temp_id": temp}
    if received is not None:
        leg["received_amount"] = received
    return {
        "anchor_entry_id": e,
        "entries": [{"id": e, "pairing": {"mode": "counter_leg", "counter_leg": leg}}],
    }


def test_a_counter_leg_previews_as_a_row_and_commits_through_the_api(anna: TestClient, scene: Scene) -> None:
    e = _leg(scene, -1000, scene.checking, counter=scene.cash)
    draft = _counter_leg_draft(e, -5)
    body = anna.post(PREVIEW, json=draft).json()
    assert body["problems"] == [] and body["state"]["confirmed"] is True
    ghost = next(r for r in body["rows"] if r["id"] == -5)
    assert ghost["counter_leg_for"] == e and ghost["version"] is None and ghost["in_unit"]
    assert ghost["account_id"] == scene.cash and ghost["amount"] == {"amount": 1000, "currency": "EUR"}
    assert ghost["counterpart_entry_id"] == e and ghost["transfer"]["state"] == "paired"
    assert ghost["fields"]["type"]["value"] == "transfer"
    leg = next(r for r in body["rows"] if r["id"] == e)
    assert leg["transfer"]["partner"]["entry_id"] == -5 and leg["transfer"]["proposed_counter_leg"] is False
    assert any(c["entry_id"] == -5 and c["kind"] == "created" for c in body["consequences"])
    r = anna.post(COMMIT, json={**draft, "versions": body["versions"]})
    assert r.status_code == 200, r.text
    out = r.json()
    real = out["created"]["-5"]
    assert scene.row(real).counterpart_entry_id == e and scene.row(e).counterpart_entry_id == real
    assert real in {en["id"] for en in out["entries"]}
    assert {"entry_id": real, "kind": "created"} in out["consequences"]


def test_the_proposed_counter_leg_is_flagged_and_a_commit_accepts_it(anna: TestClient, scene: Scene) -> None:
    e = _leg(scene, -1000, scene.checking, counter=scene.cash)
    body = anna.post(PREVIEW, json={"anchor_entry_id": e}).json()
    t = next(r for r in body["rows"] if r["id"] == e)["transfer"]
    assert t["proposed_counter_leg"] is True and t["proposed_pick"] is None
    assert t["proposal"] == {"kind": "counter_leg", "entry_id": None} and t["state"] == "paired"
    ghost = t["partner"]["entry_id"]
    assert ghost < 0 and any(r["id"] == ghost and r["counter_leg_for"] == e for r in body["rows"])
    r = anna.post(COMMIT, json={"anchor_entry_id": e, "versions": body["versions"]})
    assert r.status_code == 200, r.text
    assert str(ghost) in r.json()["created"]


def test_a_counter_leg_problem_is_listed_and_refuses_the_commit(anna: TestClient, scene: Scene) -> None:
    e = _leg(scene, -1000, scene.checking, counter=scene.usd)
    body = anna.post(PREVIEW, json=_counter_leg_draft(e)).json()
    assert [p["code"] for p in body["problems"]] == ["received_amount_required"]
    assert body["problems"][0]["entry_id"] == e
    r = anna.post(COMMIT, json={**_counter_leg_draft(e), "versions": body["versions"]})
    assert_envelope(r, 422, "received_amount_required")
    ok = anna.post(PREVIEW, json=_counter_leg_draft(e, -1, 1234)).json()
    assert ok["problems"] == []
    row = next(r for r in ok["rows"] if r["id"] == -1)
    assert row["amount"] == {"amount": 1234, "currency": "USD"}
    assert (
        anna.post(COMMIT, json={**_counter_leg_draft(e, -1, 1234), "versions": ok["versions"]}).status_code
        == 200
    )
    scene.sync(scene.cash)
    other = _leg(scene, -500, scene.checking, counter=scene.cash)
    synced = anna.post(PREVIEW, json=_counter_leg_draft(other)).json()
    assert [p["code"] for p in synced["problems"]] == ["counter_leg_account_synced"]


def test_a_malformed_counter_leg_is_a_422(anna: TestClient, scene: Scene) -> None:
    e = _leg(scene, -1000, scene.checking, counter=scene.cash)
    for received in (0, -5):
        r = anna.post(PREVIEW, json=_counter_leg_draft(e, -1, received))
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    for temp in (0, 3):
        assert anna.post(PREVIEW, json=_counter_leg_draft(e, temp)).status_code == 422
    r = anna.post(
        PREVIEW, json={"anchor_entry_id": e, "entries": [{"id": e, "pairing": {"mode": "counter_leg"}}]}
    )
    assert_envelope(r, 422, "invalid_draft")
    r = anna.post(
        PREVIEW,
        json={
            "anchor_entry_id": e,
            "entries": [{"id": e, "pairing": {"mode": "keep", "counter_leg": {"temp_id": -1}}}],
        },
    )
    assert_envelope(r, 422, "invalid_draft")
    r = anna.post(
        PREVIEW,
        json={
            "anchor_entry_id": e,
            "entries": [
                {"id": e, "pairing": {"mode": "counter_leg", "counter_leg": {"temp_id": -1, "extra": 1}}}
            ],
        },
    )
    assert r.status_code == 422
    clash = {
        "anchor_entry_id": e,
        "entries": [
            {"id": e, "pairing": {"mode": "counter_leg", "counter_leg": {"temp_id": -1}}},
            {"id": -1, "amount": -5, "source_entry_id": e},
        ],
    }
    assert_envelope(anna.post(PREVIEW, json=clash), 422, "invalid_draft")


# ---- bookings (spec §5.7, §5.8, §6) -------------------------------------------------------------------


def _booked_charge(scene: Scene) -> tuple[int, int, int]:
    from tests.core.bookings.charges import booking_entries, charge, clearance, rule_to

    account = clearance(scene)
    rule_to(scene, account)
    e = charge(scene)
    scene.settle()
    (leg,) = booking_entries(scene, e)
    return e, leg.id, account


def test_a_charge_decided_to_a_clearance_account_previews_the_booking_row_and_a_commit_leaves_it_to_settling(
    anna: TestClient, scene: Scene
) -> None:
    from tests.core.bookings.charges import booking_entries, charge, clearance

    account = clearance(scene)
    e = charge(scene, -4997)
    draft = {
        "anchor_entry_id": e,
        "entries": [{"id": e, "counter_account": {"mode": "fixed", "value": account}}],
    }
    body = anna.post(PREVIEW, json=draft).json()
    assert body["problems"] == [] and body["state"]["confirmed"] is True
    ghost = next(r for r in body["rows"] if r["booking_for"] == e)
    assert ghost["id"] < 0 and ghost["version"] is None and ghost["account_id"] == account
    assert ghost["amount"] == {"amount": 4997, "currency": "EUR"} and ghost["counterpart_entry_id"] == e
    assert ghost["booking"] == {"kind": "transfer", "id": e} and ghost["counter_leg_for"] is None
    assert ghost["transfer"]["offers"] == [] and ghost["fields"]["type"]["key"]["pass"] == "booking"
    charge_row = next(r for r in body["rows"] if r["id"] == e)
    assert charge_row["counterpart_entry_id"] == ghost["id"] and charge_row["booking_for"] is None
    assert charge_row["transfer"]["state"] == "paired"
    r = anna.post(COMMIT, json={**draft, "versions": body["versions"]})
    assert r.status_code == 200, r.text
    assert r.json()["created"] == {}
    (leg,) = booking_entries(scene, e)
    assert leg.amount == 4997 and r.json()["settle"]["error"] is None


def test_a_draft_that_changes_a_bookings_structure_is_invalid_draft_booking_fixed(
    anna: TestClient, scene: Scene
) -> None:
    e, leg, _account = _booked_charge(scene)
    drafts = [
        {"anchor_entry_id": e, "entries": [{"id": leg, "type": {"mode": "fixed", "value": "flow"}}]},
        {"anchor_entry_id": e, "entries": [{"id": leg, "amount": 5}]},
        {"anchor_entry_id": e, "entries": [{"id": -3, "amount": -5, "source_entry_id": leg}]},
        {"anchor_entry_id": e, "entries": [{"id": leg, "pairing": {"mode": "reresolve"}}]},
        {"anchor_entry_id": e, "removed_entry_ids": [leg]},
    ]
    for draft in drafts:
        for url in (PREVIEW, COMMIT):
            r = anna.post(url, json=draft)
            assert_envelope(r, 422, "invalid_draft")
            assert r.json()["error"]["details"]["code"] == "booking_fixed"


def test_the_unit_of_a_booking_is_marked_with_its_source_kind(anna: TestClient, scene: Scene) -> None:
    e, leg, _account = _booked_charge(scene)
    unit = anna.get(f"/api/units/{leg}").json()
    assert unit["booking"] == {"kind": "transfer"} and unit["state"]["confirmed"] is True
    body = anna.post(PREVIEW, json={"anchor_entry_id": leg}).json()
    row = next(r for r in body["rows"] if r["id"] == leg)
    assert row["booking"] == {"kind": "transfer", "id": e} and row["booking_for"] is None


def test_removing_a_booking_by_re_typing_its_charge_shows_it_as_a_deleted_consequence(
    anna: TestClient, scene: Scene
) -> None:
    e, leg, _account = _booked_charge(scene)
    cat = scene.category("Books")
    draft = {
        "anchor_entry_id": e,
        "entries": [
            {
                "id": e,
                "type": {"mode": "fixed", "value": "flow"},
                "category": {"mode": "fixed", "value": cat},
            }
        ],
    }
    body = anna.post(PREVIEW, json=draft).json()
    assert body["problems"] == [] and all(r["id"] != leg for r in body["rows"])
    deleted = next(c for c in body["consequences"] if c["kind"] == "deleted")
    assert deleted["entry_id"] == leg and deleted["row"]["booking"] == {"kind": "transfer", "id": e}
    r = anna.post(COMMIT, json={**draft, "versions": body["versions"]})
    assert r.status_code == 200, r.text
    assert scene.q("SELECT id FROM ledger_entry WHERE id = :i", i=leg) == []
