"""Settle steps 2 and 3: document matching and the resolution after a link (spec §5.8, §5.9; documents.md;
architecture §5.2; I20, I35, I37)."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, text

from app.core.importers.providers import reset_document_providers
from app.core.settle import settle
from tests.core.units.doc_helpers import make_doc_source, make_document, make_payee
from tests.fixtures import rule_seed as rs
from tests.invariants.helpers import make_category, make_entry, make_source

D = date(2026, 3, 10)
MakeAccount = Callable[..., int]
STANDING = {"type": {"pass": "user"}, "category": {"pass": "user"}, "payee": {"pass": "user"}}


@pytest.fixture(autouse=True)
def _registry() -> Iterator[None]:
    reset_document_providers()
    yield
    reset_document_providers()


class World:
    """A committed ledger with a document source covering the whole period, a provider payee and a rule that
    sets it on the card text `PAYPAL *`."""

    def __init__(self, engine: Engine, make_account: MakeAccount) -> None:
        self.engine = engine
        with engine.begin() as conn:
            self.account = make_account(conn)
            self.provider = make_payee(conn, "PayPal", "paypal")
            self.rule = rs.rule(
                conn,
                "paypal",
                "payee",
                self.provider,
                conditions=(rs.cond("counterparty_name", "starts_with", "PAYPAL"),),
            )
            make_doc_source(conn, covered_through=D + timedelta(days=60))

    def charge(
        self, *, amount: int = -1000, on: date = D, name: str = "PAYPAL *SEEEDDEVELO", **keys: Any
    ) -> int:
        """An unconfirmed charge, as ingest leaves it (no type, no keys)."""
        with self.engine.begin() as conn:
            src = make_source(
                conn, self.account, amount=amount, booked_on=on, columns={"counterparty_name": name}
            )
            return make_entry(conn, src, type=None, **keys)

    def document(self, **kw: Any) -> int:
        with self.engine.begin() as conn:
            return make_document(conn, **kw)

    def lines(self, doc: int, *lines: tuple[str, int]) -> None:
        with self.engine.begin() as conn:
            for n, (description, amount) in enumerate(lines, start=1):
                conn.execute(
                    text(
                        "INSERT INTO external_document_line (document_id, line_no, description, amount)"
                        " VALUES (:d, :n, :t, :a)"
                    ),
                    {"d": doc, "n": n, "t": description, "a": amount},
                )

    def merchant(self, doc: int, name: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text("UPDATE external_document SET merchant_name = :n WHERE id = :d"), {"n": name, "d": doc}
            )

    def row(self, entry: int) -> Any:
        with self.engine.connect() as conn:
            return conn.execute(
                text(
                    "SELECT type, payee_id, category_id, document_id, derivation, version, review_flags"
                    " FROM ledger_entry WHERE id = :i"
                ),
                {"i": entry},
            ).one()


@pytest.fixture
def world(isolated_engine: Engine, make_account: MakeAccount) -> World:
    return World(isolated_engine, make_account)


def test_an_exact_unique_match_is_linked_as_a_decision(world: World) -> None:
    entry, doc = world.charge(), world.document(total=-1000)
    world.lines(doc, ("USB cable", -1000))
    version = world.row(entry).version
    result = settle(world.engine)
    assert result.error is None
    row = world.row(entry)
    assert row.document_id == doc
    assert row.derivation["document"] == {"pass": "matcher_decision", "basis": {}}
    assert row.version == version + 1  # a link is structural: trg_le_version bumps it
    assert entry in result.touched_entry_ids


def test_a_document_of_several_lines_is_linked_as_a_proposal_for_review(world: World) -> None:
    entry, doc = world.charge(), world.document(total=-1000)
    world.lines(doc, ("USB cable", -400), ("Case", -600))
    settle(world.engine)
    row = world.row(entry)
    assert row.document_id == doc
    assert row.derivation["document"]["pass"] == "matcher_proposal"
    assert "unconfirmed" in row.review_flags  # the unit is reviewed once


def test_a_document_without_lines_is_a_decision(world: World) -> None:
    entry, doc = world.charge(), world.document(total=-1000)
    settle(world.engine)
    assert world.row(entry).derivation["document"]["pass"] == "matcher_decision"
    assert world.row(entry).document_id == doc


def test_two_charges_and_two_documents_write_nothing(world: World) -> None:
    a, b = world.charge(), world.charge(on=D + timedelta(days=1))
    world.document(total=-1000, external_id="x1")
    world.document(total=-1000, external_id="x2", on=D + timedelta(days=1))
    settle(world.engine)
    for e in (a, b):
        row = world.row(e)
        assert row.document_id is None and "document" not in row.derivation
        assert "document_suggested" in row.review_flags


def test_one_document_for_two_identical_charges_goes_to_neither(world: World) -> None:
    a, b = world.charge(), world.charge()
    world.document(total=-1000)
    settle(world.engine)
    assert world.row(a).document_id is None and world.row(b).document_id is None


def test_two_documents_for_one_charge_go_to_neither(world: World) -> None:
    entry = world.charge()
    world.document(total=-1000, external_id="x1")
    world.document(total=-1000, external_id="x2")
    settle(world.engine)
    assert world.row(entry).document_id is None


def test_a_confirmed_transaction_does_not_take_a_candidate_from_the_unconfirmed_one(world: World) -> None:
    """Uniqueness is judged among the transactions §1 considers: a confirmed one is not among them."""
    with world.engine.begin() as conn:
        cat = make_category(conn, "Shopping")
        src = make_source(conn, world.account, amount=-1000, booked_on=D)
        make_entry(
            conn,
            src,
            category_id=cat,
            payee_id=world.provider,
            derivation=json.dumps({**STANDING, "document": {"pass": "matcher_decision"}}),
        )
    entry, doc = world.charge(), world.document(total=-1000)
    settle(world.engine)
    assert world.row(entry).document_id == doc


@pytest.mark.parametrize(
    "decision",
    [
        pytest.param({"pass": "user"}, id="user none"),
        pytest.param({"pass": "matcher_decision"}, id="matcher none"),
    ],
)
def test_a_decided_none_is_not_touched(world: World, decision: dict[str, str]) -> None:
    entry = world.charge(derivation=json.dumps({"document": decision}))
    world.document(total=-1000)
    settle(world.engine)
    row = world.row(entry)
    assert row.document_id is None and row.derivation["document"] == decision


def test_a_users_pick_is_not_touched(world: World) -> None:
    picked, other = world.document(total=-77, external_id="p"), world.document(total=-1000, external_id="o")
    entry = world.charge(document_id=picked, derivation=json.dumps({"document": {"pass": "user"}}))
    settle(world.engine)
    row = world.row(entry)
    assert row.document_id == picked and row.derivation["document"] == {"pass": "user"}
    with world.engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM ledger_entry WHERE document_id = :d"), {"d": other}
            ).scalar_one()
            == 0
        )


def test_a_confirmed_unit_is_not_touched(world: World) -> None:
    with world.engine.begin() as conn:
        cat = make_category(conn, "Shopping")
        src = make_source(conn, world.account, amount=-1000, booked_on=D)
        entry = make_entry(
            conn,
            src,
            category_id=cat,
            payee_id=world.provider,
            derivation=json.dumps({**STANDING, "document": {"pass": "matcher_decision"}}),
        )
    world.document(total=-1000)
    before = world.row(entry)
    settle(world.engine)
    assert world.row(entry) == before


def test_a_standing_unit_whose_document_is_covered_is_linked_not_confirmed_with_none(world: World) -> None:
    """The rule decides everything and nothing awaits: the unique candidate still keeps the unit open until
    step 2 has linked it (else step 5, or the settle's first confirmation, would record "none" first)."""
    with world.engine.begin() as conn:
        cat = make_category(conn, "Shopping")
        rs.rule(conn, "shopping", "category", cat, conditions=(rs.payee_is(world.provider),))
    entry, doc = world.charge(), world.document(total=-1000)
    settle(world.engine)
    row = world.row(entry)
    assert row.document_id == doc and row.derivation["document"]["pass"] == "matcher_decision"
    assert row.category_id is not None  # and the unit is confirmed with the link, flags empty
    assert row.review_flags == []


def test_the_link_derives_every_later_value_again_on_the_enriched_input(world: World) -> None:
    """A rule on the card text gives way to rules on the merchant name and on a line's description."""
    with world.engine.begin() as conn:
        seeed, gadgets = make_payee(conn, "Seeed", None), make_category(conn, "Gadgets")
        rs.rule(conn, "seeed", "payee", seeed, conditions=(rs.name_is("Seeed Studio"),))
        rs.rule(
            conn, "cables", "category", gadgets, conditions=(rs.cond("purpose", "contains", "USB cable"),)
        )
    entry, doc = world.charge(), world.document(total=-1000)
    world.lines(doc, ("USB cable", -1000))
    world.merchant(doc, "Seeed Studio")
    settle(world.engine)
    row = world.row(entry)
    assert (row.type, row.payee_id, row.category_id) == ("flow", seeed, gadgets)
    assert row.payee_id != world.provider  # a linked payee change does not unlink
    assert row.document_id == doc and row.derivation["document"]["pass"] == "matcher_decision"
    assert row.derivation["payee"]["pass"] == "rule" and row.derivation["payee"]["basis"] != {
        "rule_id": world.rule
    }


def test_a_rule_on_the_merchant_beats_the_bank_text_and_the_card_rule_no_longer_matches(world: World) -> None:
    with world.engine.begin() as conn:
        seeed = make_payee(conn, "Seeed", None)
        rs.rule(conn, "seeed", "payee", seeed, conditions=(rs.name_is("Seeed Studio"),), priority=200)
    entry, doc = world.charge(), world.document(total=-1000)
    world.merchant(doc, "Seeed Studio")
    settle(world.engine)
    assert world.row(entry).payee_id == seeed
    # without a merchant name the bank's text stays the input: the card rule still decides the payee
    other, doc2 = world.charge(amount=-555), world.document(total=-555, external_id="n")
    settle(world.engine)
    assert world.row(other).document_id == doc2 and world.row(other).payee_id == world.provider


def test_history_does_not_run_for_a_documented_transaction(world: World) -> None:
    """A confirmed voter on the merchant's name would propose a payee and category by history: not for a
    transaction with a document; a control without one is proposed by history."""
    with world.engine.begin() as conn:
        seeed, gadgets = make_payee(conn, "Seeed", None), make_category(conn, "Gadgets")
        src = make_source(
            conn,
            world.account,
            amount=-4242,
            booked_on=D - timedelta(days=30),
            columns={"counterparty_name": "Seeed Studio"},
        )
        make_entry(
            conn,
            src,
            category_id=gadgets,
            payee_id=seeed,
            derivation=json.dumps({**STANDING, "document": {"pass": "matcher_decision"}}),
        )
        control_src = make_source(
            conn, world.account, amount=-999, booked_on=D, columns={"counterparty_name": "Seeed Studio"}
        )
        control = make_entry(conn, control_src, type=None)
    entry, doc = world.charge(), world.document(total=-1000)
    world.merchant(doc, "Seeed Studio")
    settle(world.engine)
    row = world.row(entry)
    assert row.document_id == doc
    assert (row.type, row.payee_id, row.category_id) == (None, None, None)
    assert (
        world.row(control).derivation["category"]["pass"] == "history"
    )  # history works, here it did not run


def test_a_second_settle_writes_nothing_and_moves_no_version(world: World) -> None:
    a, b, c = world.charge(), world.charge(amount=-500), world.charge(amount=-500, on=D + timedelta(days=1))
    world.document(total=-1000, external_id="a")
    d2 = world.document(total=-500, external_id="b")
    world.lines(d2, ("x", -250), ("y", -250))
    world.document(total=-500, external_id="c")
    first = settle(world.engine)
    assert first.error is None and a in first.touched_entry_ids
    before = [world.row(e) for e in (a, b, c)]
    second = settle(world.engine)
    assert second.error is None and second.touched_entry_ids == ()
    assert [world.row(e) for e in (a, b, c)] == before


def test_a_single_round_of_links_terminates_with_several_units(world: World) -> None:
    entries = [world.charge(amount=-100 * (i + 1), on=D + timedelta(days=i)) for i in range(6)]
    for i in range(6):
        world.document(total=-100 * (i + 1), external_id=f"d{i}", on=D + timedelta(days=i))
    result = settle(world.engine)
    assert result.error is None
    assert all(world.row(e).document_id is not None for e in entries)


def test_with_no_document_source_nothing_waits_and_step_two_is_a_cheap_no_op(
    isolated_engine: Engine, make_account: MakeAccount, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.settle import documents as step

    def boom(_conn: Connection) -> list[Any]:
        raise AssertionError("step 2 loaded transactions although no document exists")

    monkeypatch.setattr(step, "_considered", boom)
    with isolated_engine.begin() as conn:
        acct = make_account(conn)
        provider = make_payee(conn, "PayPal", "paypal")
        cat = make_category(conn, "Shopping")
        src = make_source(conn, acct, amount=-1000, booked_on=D)
        entry = make_entry(conn, src, category_id=cat, payee_id=provider, derivation=json.dumps(STANDING))
    result = settle(isolated_engine)
    assert result.error is None
    with isolated_engine.connect() as conn:
        row = conn.execute(
            text("SELECT review_flags, derivation FROM ledger_entry WHERE id = :i"), {"i": entry}
        ).one()
    assert row.review_flags == [] and row.derivation["document"] == {
        "pass": "matcher_decision"
    }  # confirmed at once


def test_a_charge_outside_the_window_or_another_provider_is_not_linked(world: World) -> None:
    far, other = world.charge(), world.charge(amount=-300)
    world.document(total=-1000, on=D + timedelta(days=60), external_id="far")
    world.document(total=-300, provider="amazon", external_id="am")
    settle(world.engine)
    assert world.row(far).document_id is None and world.row(other).document_id is None
