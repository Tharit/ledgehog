"""A transaction waits for the rest of its document's order (spec §5.8, §6; documents.md §7).

It carries a document with a matcher key, the amounts of the document's carriers fall short of its total in
magnitude, and some synced account has not reached the document's date plus `back`. The wait sets `waiting`,
puts the unit in the queue's waiting section with the order's line, and holds no confirmation of its own.
The SQL (`doc_rest` of the unit CTE) is pinned to its Python twin (`rest_awaited`).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Connection, text

from app.core.importers.providers import reset_document_providers
from app.core.matching.documents import DocInput, DocWindow
from app.core.resolution.confirmed import units_binds, units_sql
from app.core.resolution.doc_load import load_carriers
from app.core.settle.flags import recompute_review_flags
from app.core.settle.window import document_window
from app.core.units.documents import OrderWait, rest_awaited
from app.core.units.read import review_queue
from tests.core.units.doc_helpers import Docs, make_document, make_payee
from tests.core.units.equality import preview_then_commit
from tests.core.units.helpers import Bench, D
from tests.core.units.scene import Scene, no_document
from tests.invariants.helpers import link_account, make_instance, make_run

PROPOSAL = json.dumps({"document": {"pass": "matcher_proposal"}})
DECISION = json.dumps({"document": {"pass": "matcher_decision"}})
USER = json.dumps({"document": {"pass": "user"}})


@pytest.fixture(autouse=True)
def _registry() -> Iterator[None]:
    reset_document_providers()
    yield
    reset_document_providers()


@pytest.fixture
def bench(db_conn: Connection, make_account: Any) -> Bench:
    return Bench(db_conn, make_account)


def _sync(bench: Bench, through: Any, account: int | None = None) -> None:
    """Make an account synced (an importer linked), fetched through `through` (None: never)."""
    instance = make_instance(bench.conn)
    link_account(bench.conn, account or bench.a, instance)
    if through is not None:
        make_run(bench.conn, account or bench.a, covered_through=through, instance_id=instance)


def _carry(
    bench: Bench, doc: int, amount: int, derivation: str = PROPOSAL, *, on: Any = D, **cols: Any
) -> int:
    """A charge of `amount` linked to `doc`, the link under `derivation`."""
    payee = make_payee(bench.conn, f"PayPal {amount}{on}", "paypal")
    entry = bench.flow(bench.source(amount=amount, on=on), payee_id=payee, derivation=derivation, **cols)
    bench.conn.execute(text("UPDATE ledger_entry SET document_id = :d WHERE id = :e"), {"d": doc, "e": entry})
    return entry


def _order(bench: Bench, total: int = -5000, **kw: Any) -> int:
    return make_document(bench.conn, total=total, external_id="302-1", **kw)


def _rows(conn: Connection) -> dict[int, Any]:
    result = conn.execute(text(f"WITH units AS ({units_sql()}) SELECT * FROM units"), units_binds(conn))
    return {r.id: r for r in result}


def _flags(conn: Connection, entry: int) -> list[str]:
    recompute_review_flags(conn)
    return list(
        conn.execute(text("SELECT review_flags FROM ledger_entry WHERE id = :i"), {"i": entry}).scalar_one()
    )


def _queue(conn: Connection) -> dict[str, Any]:
    recompute_review_flags(conn)
    return {s.kind: s for s in review_queue(conn).sections}


def _behind(conn: Connection) -> Any:
    """A `synced_through` that has not reached the order's date plus `back`."""
    return D + timedelta(days=document_window(conn).back - 1)


def test_an_order_not_all_charged_waits_and_the_queue_says_what_is_left(bench: Bench) -> None:
    conn = bench.conn
    _sync(bench, _behind(conn))
    doc = _order(bench)
    entry = _carry(bench, doc, -3000)
    assert _flags(conn, entry) == ["unconfirmed", "waiting"]
    queue = _queue(conn)
    assert [u.anchor_entry_id for u in queue["waiting"].units] == [entry]
    assert not queue["pending_review"].units
    wait = queue["waiting"].units[0].waiting_order
    assert wait == OrderWait("302-1", "paypal", -3000, -5000, "EUR")
    assert (wait.remainder, queue["waiting"].units[0].waiting_document) == (2000, None)
    assert queue["waiting"].units[0].waiting is None


def test_the_second_charge_ends_the_wait(bench: Bench) -> None:
    conn = bench.conn
    _sync(bench, _behind(conn))
    doc = _order(bench)
    first = _carry(bench, doc, -3000)
    second = _carry(bench, doc, -2000, on=D + timedelta(days=1))
    assert _flags(conn, first) == ["unconfirmed"] and _flags(conn, second) == ["unconfirmed"]
    queue = _queue(conn)
    assert not queue["waiting"].units
    # the carriers of a document are one unit
    assert [u.anchor_entry_id for u in queue["pending_review"].units] == [min(first, second)]


def test_every_synced_account_past_the_window_ends_the_wait(bench: Bench) -> None:
    conn = bench.conn
    back = document_window(conn).back
    _sync(bench, D + timedelta(days=back))  # reached occurred_on + back exactly
    _sync(bench, D + timedelta(days=back + 5), bench.b)
    entry = _carry(bench, _order(bench), -3000)
    assert _flags(conn, entry) == ["unconfirmed"]


def test_one_account_behind_still_holds_it(bench: Bench) -> None:
    conn = bench.conn
    back = document_window(conn).back
    _sync(bench, D + timedelta(days=back))
    _sync(bench, D + timedelta(days=back - 1), bench.b)
    entry = _carry(bench, _order(bench), -3000)
    assert _flags(conn, entry) == ["unconfirmed", "waiting"]


def test_a_synced_account_never_fetched_holds_it(bench: Bench) -> None:
    conn = bench.conn
    _sync(bench, D + timedelta(days=document_window(conn).back + 5))
    _sync(bench, None, bench.b)  # synced, never run
    entry = _carry(bench, _order(bench), -3000)
    assert _flags(conn, entry) == ["unconfirmed", "waiting"]


def test_without_a_synced_account_nothing_holds_it(bench: Bench) -> None:
    entry = _carry(bench, _order(bench), -3000)
    assert _flags(bench.conn, entry) == ["unconfirmed"]


def test_a_user_committed_carrier_does_not_wait_beside_a_matcher_linked_one(bench: Bench) -> None:
    conn = bench.conn
    _sync(bench, _behind(conn))
    doc = _order(bench)
    committed = _carry(bench, doc, -3000, USER)
    linked = _carry(bench, doc, -1000, PROPOSAL, on=D + timedelta(days=1))  # 40 of 50
    assert "waiting" not in _flags(conn, committed)
    assert _flags(conn, linked) == ["unconfirmed", "waiting"]
    wait = _queue(conn)["waiting"].units[0].waiting_order
    assert wait == OrderWait("302-1", "paypal", -4000, -5000, "EUR")  # the committed charge counts


def test_a_refund_document_is_compared_by_magnitude(bench: Bench) -> None:
    conn = bench.conn
    _sync(bench, _behind(conn))
    doc = _order(bench, 5000)
    short = _carry(bench, doc, 3000)
    assert _flags(conn, short) == ["unconfirmed", "waiting"]
    assert _queue(conn)["waiting"].units[0].waiting_order == OrderWait("302-1", "paypal", 3000, 5000, "EUR")
    _carry(bench, doc, 2000, on=D + timedelta(days=1))
    assert _flags(conn, short) == ["unconfirmed"]


def test_charged_beyond_the_total_does_not_wait(bench: Bench) -> None:
    conn = bench.conn
    _sync(bench, _behind(conn))
    entry = _carry(bench, _order(bench), -6000)
    assert _flags(conn, entry) == ["unconfirmed"]


def test_it_holds_no_confirmation_of_its_own(bench: Bench) -> None:
    conn = bench.conn
    _sync(bench, _behind(conn))
    entry = _carry(bench, _order(bench), -3000, DECISION)  # a standing key: nothing else keeps the unit open
    row = _rows(conn)[entry]
    assert (row.doc_rest, row.doc_awaited, row.doc_suggested, row.unit_ok) == (True, False, False, True)
    # a unit that is confirmed is in no queue section, whatever it waits for
    assert not any(u.anchor_entry_id == entry for s in _queue(conn).values() for u in s.units)


def test_a_user_key_or_no_key_never_waits(bench: Bench) -> None:
    conn = bench.conn
    _sync(bench, _behind(conn))
    doc = _order(bench)
    entry = _carry(bench, doc, -3000, USER)
    assert _rows(conn)[entry].doc_rest is False


# ---- the SQL equals the Python twin ---------------------------------------------------------------


@pytest.mark.parametrize("through", ["behind", "reached", "never", "none"])
@pytest.mark.parametrize("charged", [[-3000], [-3000, -2000], [-3000, -2500], []])
@pytest.mark.parametrize("passname", ["matcher_proposal", "matcher_decision", "user"])
def test_sql_equals_the_twin(bench: Bench, through: str, charged: list[int], passname: str) -> None:
    conn = bench.conn
    window = document_window(conn)
    if through != "none":
        _sync(
            bench,
            {
                "behind": D + timedelta(days=window.back - 1),
                "reached": D + timedelta(days=window.back),
                "never": None,
            }[through],
        )
    doc = _order(bench)
    derivation = json.dumps({"document": {"pass": passname}})
    entries = [
        _carry(bench, doc, amount, derivation, on=D + timedelta(days=i)) for i, amount in enumerate(charged)
    ]
    if not entries:
        return
    synced = [
        r.synced_through
        for r in conn.execute(
            text(
                "SELECT c.synced_through FROM v_account_synced s JOIN v_account_coverage c"
                " ON c.account_id = s.account_id WHERE s.synced"
            )
        )
    ]
    row = conn.execute(
        text("SELECT provider, occurred_on, total, currency FROM external_document WHERE id = :d"),
        {"d": doc},
    ).one()
    carriers = load_carriers(conn, [doc])[doc]
    expected = passname != "user" and rest_awaited(
        DocInput(doc, row.provider, row.occurred_on, row.total, row.currency, carriers=carriers),
        synced,
        DocWindow(*window),
    )
    sql = _rows(conn)
    assert {sql[e].doc_rest for e in entries} == {expected}, (through, charged, passname)


def test_the_twin_on_its_own() -> None:
    doc = DocInput(1, "paypal", D, -5000, "EUR")
    window = DocWindow(60, 7)
    from app.core.matching.documents import DocTxn

    def txn(amount: int, **kw: Any) -> DocTxn:
        return DocTxn(1, 1, D, amount, "EUR", **kw)

    short = DocInput(1, "paypal", D, -5000, "EUR", carriers=(txn(-3000),))
    full = DocInput(1, "paypal", D, -5000, "EUR", carriers=(txn(-3000), txn(-2000)))
    behind, reached = D + timedelta(days=59), D + timedelta(days=60)
    assert rest_awaited(short, [behind], window) is True
    assert rest_awaited(short, [reached], window) is False
    assert rest_awaited(short, [reached, None], window) is True  # never fetched holds it
    assert rest_awaited(short, [], window) is False  # no synced account
    assert rest_awaited(full, [behind], window) is False
    instructed = DocInput(
        1,
        "paypal",
        D,
        -5000,
        "USD",
        carriers=(txn(-3000, instructed_amount=-4000, instructed_currency="USD"),),
    )
    assert rest_awaited(instructed, [behind], window) is True
    assert rest_awaited(doc, [behind], window) is True  # nothing charged at all


# ---- the preview ---------------------------------------------------------------------------------


def test_the_preview_says_what_the_order_waits_for(scene: Scene) -> None:
    docs = Docs(scene)
    scene.sync(scene.checking)  # fetched through 2026-03-01: short of the order's date plus back
    doc = docs.document(total=-5000, external_id="302-1")
    docs.lines(doc, ("a", -3000), ("b", -2000))
    entry = docs.charge(-3000)
    scene.settle()
    assert scene.row(entry).document_id == doc
    plan = scene.preview(entry)
    view = plan.row(entry).document_view
    assert view is not None
    assert view.waiting == OrderWait("302-1", "paypal", -3000, -5000, "EUR")
    assert "waiting" not in plan.row(entry).flags  # the flags are those after the commit, which ends the wait
    assert not plan.problems  # the wait adds no refusal
    assert (
        not plan.anchor_unit.state.confirmed and "waiting_for_document" not in plan.anchor_unit.state.reasons
    )
    # a commit makes the link the user's, which ends the wait and keeps the link
    preview_then_commit(scene, scene.draft(entry))
    assert scene.row(entry).document_id == doc
    assert scene.row(entry).derivation["document"] == {"pass": "user"}
    assert "waiting" not in scene.row(entry).review_flags


def test_without_a_synced_account_the_preview_has_no_wait(scene: Scene) -> None:
    docs = Docs(scene)
    doc = docs.document(total=-5000, external_id="302-1")
    docs.lines(doc, ("a", -3000), ("b", -2000))
    entry = docs.charge(-3000)
    scene.settle()
    view = scene.preview(entry).row(entry).document_view
    assert view is None or view.waiting is None


def test_a_document_wait_is_still_told_apart(scene: Scene) -> None:
    waiting = Docs(scene, covered=False)
    entry = waiting.charge()
    waiting.document(total=-1000, external_id="a")
    waiting.document(total=-1000, external_id="b")
    view = scene.preview(entry).row(entry).document_view
    assert view is not None and view.waiting is not None and not isinstance(view.waiting, OrderWait)
    preview_then_commit(scene, scene.draft(entry, no_document(entry)))
