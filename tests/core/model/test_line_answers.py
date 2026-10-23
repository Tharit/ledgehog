"""A document line is asked, an entry with a line takes the line's answer (spec §5.9 pass 3, §5.5;
architecture §5.4): the line's payload, the answer stored on the line in an entry key's shape, the entries
with that line resolved again, ingest keeping answers across line replacement, the restart's refill."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from sqlalchemy import Engine, text

from app.core.ingest.documents import ingest_documents
from app.core.ingest.run import start_run
from app.core.model.queue import ENTRY, LINE
from app.core.plugins.classifier import EntryInput
from app.core.plugins.importer import IncomingDocument
from app.core.plugins.model import LineInput
from app.core.settle import settle
from app.plugins.classifiers.llm.payload import fingerprint_of, payload_fingerprint, payload_of
from tests.core.model.rig import Rig, entry_row, make_rig
from tests.core.units.doc_helpers import make_document
from tests.fixtures import rule_seed as rs
from tests.invariants.helpers import make_category, make_entry, make_source
from tests.plugins.importers.fakes import document, line

MakeAccount = Callable[..., int]
DAY = date(2026, 3, 10)


@pytest.fixture
def acct(isolated_engine: Engine, make_account: MakeAccount) -> int:
    with isolated_engine.begin() as conn:
        return make_account(conn)


def _order(
    engine: Engine, acct: int, *descriptions: str, merchant: str = "Seeed Studio"
) -> tuple[int, list[int], int]:
    """A document with these lines and an unconfirmed entry of its transaction that has line 1 (as a user's
    link leaves it): (document id, line ids, entry id). The bank's text says nothing of the purchase."""
    descriptions = descriptions or ("USB cable", "Case")
    with engine.begin() as conn:
        doc = make_document(conn, total=-1000, on=DAY)
        conn.execute(
            text("UPDATE external_document SET merchant_name = :m WHERE id = :d"), {"m": merchant, "d": doc}
        )
        ids = [
            int(
                conn.execute(
                    text(
                        "INSERT INTO external_document_line (document_id, line_no, description, amount)"
                        " VALUES (:d, :n, :t, -100) RETURNING id"
                    ),
                    {"d": doc, "n": n, "t": t},
                ).scalar_one()
            )
            for n, t in enumerate(descriptions, start=1)
        ]
        src = make_source(
            conn,
            acct,
            amount=-100,
            booked_on=DAY,
            columns={"counterparty_name": "PAYPAL *SEEED", "purpose": "7721"},
        )
        entry = make_entry(
            conn,
            src,
            type=None,
            document_id=doc,
            document_line_id=ids[0],
            derivation=json.dumps({"document": {"pass": "user"}}),
        )
    return doc, ids, entry


def _line(engine: Engine, line_id: int) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT category_id, category_key, description FROM external_document_line WHERE id = :i"),
            {"i": line_id},
        ).one()


def _lines_of(engine: Engine, doc: int) -> dict[str, Any]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT description, category_id, category_key FROM external_document_line"
                " WHERE document_id = :d ORDER BY line_no"
            ),
            {"d": doc},
        ).all()
    return {r.description: r for r in rows}


def _process_head(rig: Rig) -> None:
    item = rig.queue.head()
    assert item is not None
    asyncio.run(rig.worker.process(item))


def _fingerprint(merchant: str, description: str) -> str:
    fingerprint = payload_fingerprint(LineInput(0, merchant, description))
    assert fingerprint is not None
    return fingerprint


# ---- the list and the payload ------------------------------------------------------------------------


def test_settling_lists_every_line_and_never_an_entry_with_a_line(rig: Rig, acct: int) -> None:
    _, ids, entry = _order(rig.engine, acct)
    assert settle(rig.engine).error is None
    assert rig.queue.line_ids() == set(ids)
    assert rig.queue.entry_ids() == frozenset()  # the entry takes its line's answer: the line is asked
    assert rig.queue.pending() == 2 and rig.endpoint.requests == []
    assert entry_row(rig.engine, entry).category_id is None


def test_the_request_for_a_line_carries_the_merchant_and_the_description_only(rig: Rig, acct: int) -> None:
    _order(rig.engine, acct)
    with rig.engine.begin() as conn:
        make_category(conn, "Gadgets")
    settle(rig.engine)
    _process_head(rig)
    body = rig.endpoint.requests[0].content.decode()
    assert "Seeed Studio" in body and "USB cable" in body
    for never in ("PAYPAL", "7721", "-100", "2026"):
        assert never not in body


# ---- storing a line's answer -------------------------------------------------------------------------


def test_a_line_answer_is_stored_on_the_line_in_the_shape_of_an_entry_key(rig: Rig, acct: int) -> None:
    _, ids, _ = _order(rig.engine, acct)
    with rig.engine.begin() as conn:
        cat = make_category(conn, "Gadgets")
    settle(rig.engine)
    rig.endpoint.category_id = cat
    assert rig.queue.head() == (LINE, ids[0], _fingerprint("Seeed Studio", "USB cable"))

    _process_head(rig)

    stored = _line(rig.engine, ids[0])
    basis = {
        "model": "m-1",
        "rationale": "a short reason",
        "fingerprint": _fingerprint("Seeed Studio", "USB cable"),
    }
    assert stored.category_id == cat and stored.category_key == {"pass": "llm", "basis": basis}
    assert _line(rig.engine, ids[1]).category_key is None  # the other line waits


def test_no_category_fits_is_stored_as_the_key_with_none_and_no_category(rig: Rig, acct: int) -> None:
    _, ids, entry = _order(rig.engine, acct)
    with rig.engine.begin() as conn:
        make_category(conn, "Gadgets")
    settle(rig.engine)
    rig.endpoint.category_id = None
    rig.endpoint.rationale = "a cable; there is no category for cables"

    _process_head(rig)

    stored = _line(rig.engine, ids[0])
    basis = {
        "model": "m-1",
        "rationale": "a cable; there is no category for cables",
        "fingerprint": _fingerprint("Seeed Studio", "USB cable"),
        "none": True,
    }
    assert stored.category_id is None and stored.category_key == {"pass": "llm", "basis": basis}
    # the entry takes the absence, explained, and is not asked for itself
    row = entry_row(rig.engine, entry)
    assert row.category_id is None and row.derivation["category"] == {"pass": "llm", "basis": basis}
    assert rig.queue.line_ids() == {ids[1]}


def test_the_answer_reaches_the_unconfirmed_entries_with_that_line(rig: Rig, acct: int) -> None:
    _, ids, entry = _order(rig.engine, acct)
    with rig.engine.begin() as conn:
        cat = make_category(conn, "Gadgets")
    settle(rig.engine)
    assert entry_row(rig.engine, entry).category_id is None
    rig.endpoint.category_id = cat

    _process_head(rig)

    row = entry_row(rig.engine, entry)
    assert row.category_id == cat and row.type == "flow"
    assert row.derivation["category"] == _line(rig.engine, ids[0]).category_key
    assert row.version == 1  # settling moves no version
    assert settle(rig.engine).touched_entry_ids == ()  # stable
    assert len(rig.endpoint.requests) == 1  # asked once for the line, never for the entry


def test_a_confirmed_entry_with_that_line_is_left_alone(rig: Rig, acct: int) -> None:
    _, ids, entry = _order(rig.engine, acct)
    with rig.engine.begin() as conn:
        cat, other = make_category(conn, "Gadgets"), make_category(conn, "Other")
        conn.execute(
            text(
                "UPDATE ledger_entry SET type = 'flow', category_id = :c,"
                " derivation = derivation || CAST(:k AS jsonb) WHERE id = :e"
            ),
            {
                "c": other,
                "e": entry,
                "k": json.dumps({k: {"pass": "user"} for k in ("type", "payee", "category")}),
            },
        )
    settle(rig.engine)
    rig.endpoint.category_id = cat
    _process_head(rig)
    assert entry_row(rig.engine, entry).category_id == other
    assert _line(rig.engine, ids[0]).category_id == cat


def test_a_higher_pass_decides_the_category_the_line_answer_is_still_stored(rig: Rig, acct: int) -> None:
    _, ids, entry = _order(rig.engine, acct)
    with rig.engine.begin() as conn:
        cat, rule_cat = make_category(conn, "Gadgets"), make_category(conn, "Hardware")
        rs.rule(
            conn,
            "seeed",
            "category",
            rule_cat,
            conditions=(rs.cond("document_merchant", "equals", "Seeed Studio"),),
        )
    settle(rig.engine)
    rig.endpoint.category_id = cat
    _process_head(rig)
    row = entry_row(rig.engine, entry)
    assert row.category_id == rule_cat and row.derivation["category"]["pass"] == "rule"
    assert _line(rig.engine, ids[0]).category_id == cat


def test_an_answer_for_a_line_whose_payload_changed_is_dropped(rig: Rig, acct: int) -> None:
    _, ids, _ = _order(rig.engine, acct)
    with rig.engine.begin() as conn:
        cat = make_category(conn, "Gadgets")
    settle(rig.engine)
    rig.endpoint.category_id = cat
    rig.endpoint.during = lambda: _edit_line(rig.engine, ids[0], "USB-C cable")
    _process_head(rig)
    assert _line(rig.engine, ids[0]).category_key is None
    assert rig.queue.pending() == 1  # the item is gone; settling lists the line anew for its new payload
    settle(rig.engine)
    assert rig.queue.line_ids() == set(ids)  # listed anew, for its new payload
    assert (LINE, ids[0], _fingerprint("Seeed Studio", "USB-C cable")) in _items(rig)


def _items(rig: Rig) -> list[Any]:
    out = []
    while (item := rig.queue.head()) is not None:
        out.append(item)
        rig.queue.finish(item, answered=True)
    return out


def _edit_line(engine: Engine, line_id: int, description: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE external_document_line SET description = :t WHERE id = :i"),
            {"t": description, "i": line_id},
        )


def test_the_documents_detail_shows_the_answer_the_worker_wrote(rig: Rig, acct: int) -> None:
    from app.core.documents.read import get_document

    doc, ids, _ = _order(rig.engine, acct)
    with rig.engine.begin() as conn:
        cat = make_category(conn, "Gadgets")
    settle(rig.engine)
    rig.endpoint.category_id = cat
    rig.endpoint.rationale = "a cable"
    _process_head(rig)
    rig.endpoint.category_id = None
    rig.endpoint.rationale = "a case; no category for cases"
    _process_head(rig)
    with rig.engine.connect() as conn:
        detail = get_document(conn, doc)
    assert detail is not None
    first, second = detail.lines
    assert (first.category_id, first.category_name, first.rationale) == (cat, "Gadgets", "a cable")
    assert (second.category_id, second.rationale) == (None, "a case; no category for cases")


# ---- a deleted category is no answer ----------------------------------------------------------------


def test_a_line_answer_whose_category_was_deleted_is_no_answer_and_the_line_is_asked_again(
    rig: Rig, acct: int
) -> None:
    _, ids, entry = _order(rig.engine, acct)
    with rig.engine.begin() as conn:
        cat = make_category(conn, "Gadgets")
    settle(rig.engine)
    rig.endpoint.category_id = cat
    _process_head(rig)
    assert entry_row(rig.engine, entry).category_id == cat

    with (
        rig.engine.begin() as conn
    ):  # an unreferenced entry key is not enough: free the entry's reference first
        conn.execute(text("UPDATE ledger_entry SET category_id = NULL WHERE id = :e"), {"e": entry})
        conn.execute(text("DELETE FROM category WHERE id = :c"), {"c": cat})
    assert _line(rig.engine, ids[0]).category_id is None  # ON DELETE SET NULL; the key stays
    assert _line(rig.engine, ids[0]).category_key is not None

    assert settle(rig.engine).error is None
    row = entry_row(rig.engine, entry)
    assert row.category_id is None and "category" not in row.derivation  # no answer: nothing proposed
    assert ids[0] in rig.queue.line_ids()  # and the line is asked again


# ---- the restart ---------------------------------------------------------------------------------------


def test_a_restart_refills_the_list_with_every_line_that_has_no_answer(rig: Rig, acct: int) -> None:
    _, ids, _ = _order(rig.engine, acct)
    with rig.engine.begin() as conn:
        cat = make_category(conn, "Gadgets")
    settle(rig.engine)
    rig.endpoint.category_id = cat
    _process_head(rig)  # the first line is answered, the second waits

    restarted = make_rig(rig.engine)  # the list is in memory only: a new process starts empty
    assert restarted.queue.pending() == 0
    assert settle(rig.engine).error is None  # the start's settling
    assert restarted.queue.line_ids() == {ids[1]}


# ---- ingest --------------------------------------------------------------------------------------------


def _deliver(engine: Engine, doc: IncomingDocument) -> Any:
    run_id = start_run(engine, None, "documents", importer="fake")
    result = ingest_documents(engine, run_id, [doc], covered_through=date(2026, 6, 30))
    assert result.settle.error is None
    return result


def _answer_all(rig: Rig, category: int) -> None:
    rig.endpoint.category_id = category
    while rig.queue.head() is not None:
        _process_head(rig)


def test_a_new_documents_every_line_is_listed(rig: Rig) -> None:
    _deliver(rig.engine, document(lines=(line("USB cable", -400), line("Case", 300), line("Refund", 100))))
    assert rig.queue.pending() == 3 and rig.queue.entry_ids() == frozenset()  # all signs
    assert rig.endpoint.requests == []


def test_a_refetched_line_with_an_unchanged_payload_keeps_its_answer_across_the_replacement(rig: Rig) -> None:
    with rig.engine.begin() as conn:
        cat = make_category(conn, "Gadgets")
    _deliver(rig.engine, document(lines=(line("USB cable", -400), line("Case", -600))))
    _answer_all(rig, cat)
    before = _lines_of(rig.engine, _doc_id(rig.engine))
    assert all(r.category_id == cat for r in before.values())
    asked = len(rig.endpoint.requests)

    # the order changed: the case is gone, a charger is new, the cable moved to the second place
    _deliver(rig.engine, document(lines=(line("Charger", -300), line("USB cable", -400))))
    after = _lines_of(rig.engine, _doc_id(rig.engine))
    assert after["USB cable"].category_id == cat
    assert after["USB cable"].category_key == before["USB cable"].category_key  # the same answer
    assert after["Charger"].category_key is None
    assert rig.queue.line_ids() == {_line_id(rig.engine, "Charger")}  # only the unanswered line is listed
    assert len(rig.endpoint.requests) == asked


def test_a_document_delivered_again_unchanged_keeps_every_answer(rig: Rig) -> None:
    with rig.engine.begin() as conn:
        cat = make_category(conn, "Gadgets")
    doc = document(lines=(line("USB cable", -400), line("Case", -600)))
    _deliver(rig.engine, doc)
    _answer_all(rig, cat)
    _deliver(rig.engine, doc)
    assert all(r.category_id == cat for r in _lines_of(rig.engine, _doc_id(rig.engine)).values())
    assert rig.queue.pending() == 0


def test_a_changed_merchant_makes_the_answers_stale_and_the_lines_are_asked_again(rig: Rig) -> None:
    with rig.engine.begin() as conn:
        cat = make_category(conn, "Gadgets")
    _deliver(rig.engine, document(lines=(line("USB cable", -400),)))
    _answer_all(rig, cat)
    _deliver(rig.engine, document(merchant_name="Other Shop", lines=(line("USB cable", -400),)))
    row = _lines_of(rig.engine, _doc_id(rig.engine))["USB cable"]
    assert row.category_id is None and row.category_key is None
    assert rig.queue.line_ids() == {_line_id(rig.engine, "USB cable")}


def _doc_id(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text("SELECT id FROM external_document ORDER BY id LIMIT 1")).scalar_one())


def _line_id(engine: Engine, description: str) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text("SELECT id FROM external_document_line WHERE description = :t"), {"t": description}
            ).scalar_one()
        )


def test_the_entry_item_kind_is_still_an_entry_without_a_line(rig: Rig, acct: int) -> None:
    with rig.engine.begin() as conn:
        make_entry(conn, make_source(conn, acct, columns={"counterparty_name": "AUCAT BAR"}), type=None)
    settle(rig.engine)
    head = rig.queue.head()
    assert head is not None and head[0] == ENTRY
    entry = EntryInput(head[1], acct, "EUR", DAY, 0, counterparty_name="AUCAT BAR")
    payload = payload_of(entry)
    assert payload is not None and head[2] == fingerprint_of(payload)
