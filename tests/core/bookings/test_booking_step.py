"""Settle's booking step for documents (spec §5.8, features/documents.md): booking, following, removing."""

from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import DBAPIError

from app.core.accounts import set_clearance_providers
from app.core.balance.records import set_manual_record, update_manual_record
from app.core.settle import settle
from app.utils.db.changes import install_change_hooks
from tests.core.bookings.scene import Scene, doc, line

BOOKING_KEY = {"pass": "booking", "basis": {}}


@pytest.fixture
def scene(isolated_engine: Engine) -> Scene:
    return Scene(isolated_engine)


def amounts(entries: list) -> list[int]:
    return [e.amount for e in entries]


def texts(entries: list) -> list[str | None]:
    return [e.source_text for e in entries]


# ---- the booking ------------------------------------------------------------------------------------


def test_a_document_is_booked_on_ingest_with_its_fields_from_the_document(scene: Scene) -> None:
    account = scene.clearance()
    result = scene.deliver(doc("A1", line("Cable", -1299), line("Book", -3499), total=-4997))
    assert result.settle.error is None
    b = scene.booking()
    assert b is not None
    assert (b.origin, b.account_id, b.currency) == ("booking", account, "EUR")
    assert (b.importer, b.import_run_id, b.source_format, b.importer_instance_id) == (None, None, None, None)
    assert (b.booked_on, b.amount) == (date(2026, 2, 1), -4997)
    assert (b.counterparty_name, b.purpose) == ("Amazon", "Order A1")
    assert b.source_id == f"document:{scene.document_id()}" and b.content_hash is None
    assert b.duplicate_of is None and isinstance(b.raw, dict) and b.raw
    entries = scene.entries()
    assert amounts(entries) == [-1353, -3644]
    assert texts(entries) == ["Cable", "Book"]
    assert [e.account_id for e in entries] == [account, account]
    assert all(e.booked_on == date(2026, 2, 1) and e.currency == "EUR" for e in entries)


def test_a_refund_is_booked_as_a_refund(scene: Scene) -> None:
    scene.clearance()
    scene.deliver(doc("R1", line("Cable", 500), line("Book", 500)))
    assert scene.booking("R1").purpose == "Refund R1"
    assert amounts(scene.entries("R1")) == [500, 500]


def test_entries_are_flows_under_the_booking_key(scene: Scene) -> None:
    scene.clearance()
    scene.deliver(doc("A1", line("A", -100), line("B", -200)))
    for e in scene.entries():
        assert e.type == "flow"
        assert e.derivation["type"] == BOOKING_KEY
        assert e.description is None and e.note is None


def test_the_entries_are_resolved_in_the_settle_that_books_them(scene: Scene) -> None:
    scene.clearance()
    books = scene.category("Books")
    scene.exec(
        "INSERT INTO rule (sets, category_id, conditions, name) VALUES ('category', :c,"
        " CAST(:cond AS jsonb), 'Amazon')",
        c=books,
        cond=json.dumps([{"field": "counterparty_name", "op": "equals", "value": "Amazon"}]),
    )
    scene.deliver(doc("A1", line("A", -100), line("B", -200)))
    for e in scene.entries():
        assert e.category_id == books
        assert e.derivation["category"]["pass"] == "rule"
        assert e.derivation["type"] == BOOKING_KEY
        assert e.review_flags == []  # a booking and a rule: standing keys, confirmed without review


def test_no_line_of_the_totals_sign_gives_one_entry_without_text(scene: Scene) -> None:
    scene.clearance()
    scene.deliver(doc("A1", line("Coupon", 200), total=-500), doc("A2", total=-700))
    assert (amounts(scene.entries("A1")), texts(scene.entries("A1"))) == ([-500], [None])
    assert (amounts(scene.entries("A2")), texts(scene.entries("A2"))) == ([-700], [None])


def test_zero_lines_get_no_entry_and_a_zero_total_no_booking(scene: Scene) -> None:
    scene.clearance()
    scene.deliver(doc("A1", line("A", -100), line("Free", 0), line("B", -100)), doc("Z", total=0))
    assert amounts(scene.entries()) == [-100, -100]
    assert texts(scene.entries()) == ["A", "B"]
    assert scene.booking("Z") is None


def test_the_booking_step_is_idempotent(scene: Scene) -> None:
    scene.clearance()
    scene.deliver(doc("A1", line("A", -100), line("B", -200)), doc("A2", line("C", -50)))
    before = scene.q("SELECT id, version, derivation, review_flags FROM ledger_entry ORDER BY id")
    sources = scene.q("SELECT id FROM source_transaction ORDER BY id")
    again = settle(scene.engine)
    assert again.error is None and again.touched_entry_ids == ()
    assert scene.q("SELECT id, version, derivation, review_flags FROM ledger_entry ORDER BY id") == before
    assert scene.q("SELECT id FROM source_transaction ORDER BY id") == sources


def test_the_booking_is_on_the_clearance_account_of_the_documents_currency(scene: Scene) -> None:
    eur = scene.clearance("Amazon.de")
    usd = scene.clearance("Amazon.com", currency="USD")
    scene.deliver(doc("E", provider="AMAZON"), doc("U", provider="amazon", currency="USD"))
    assert scene.booking("E").account_id == eur
    assert scene.booking("U").account_id == usd


def test_only_a_document_after_the_start_is_booked(scene: Scene) -> None:
    scene.clearance()
    scene.deliver(
        doc("ON", occurred_on=date(2026, 1, 31)),
        doc("BEFORE", occurred_on=date(2026, 1, 1)),
        doc("AFTER", occurred_on=date(2026, 2, 1)),
    )
    assert [scene.booking(e) is not None for e in ("ON", "BEFORE", "AFTER")] == [False, False, True]


def test_no_account_and_no_start_book_nothing(scene: Scene) -> None:
    scene.deliver(doc("A1"))
    assert scene.bookings() == []
    scene.clearance(providers=("Amazon",))
    assert scene.booking("A1") is not None  # a provider added books what it covers
    other = scene.clearance("Ebay.de", providers=("Ebay",))
    scene.exec("DELETE FROM balance_record WHERE account_id = :a", a=other)  # no start
    scene.deliver(doc("E1", provider="Ebay"))
    assert scene.booking("E1") is None


def test_the_database_refuses_a_booking_on_another_kind_of_account(scene: Scene) -> None:
    with scene.engine.begin() as conn, pytest.raises(DBAPIError):
        conn.exec_driver_sql(
            "INSERT INTO account (name, kind, currency) VALUES ('Checking', 'checking', 'EUR')"
        )
        conn.exec_driver_sql(
            "INSERT INTO source_transaction (origin, account_id, source_id, amount, currency, booked_on, raw)"
            " SELECT 'booking', id, 'document:1', -1, 'EUR', '2026-02-01', '{}' FROM account"
        )


@pytest.mark.parametrize(
    "columns, values",
    [
        ("source_id, importer", "'document:9', 'x'"),  # an importer without run and format
        ("content_hash", "'h'"),  # no source_id
        ("source_id, duplicate_of", "'document:9', 1"),  # never a duplicate
    ],
)
def test_the_origin_constraint_holds_for_bookings(scene: Scene, columns: str, values: str) -> None:
    account = scene.clearance()
    with scene.engine.connect() as conn, pytest.raises(DBAPIError):
        conn.exec_driver_sql(
            f"INSERT INTO source_transaction (origin, account_id, {columns}, amount, currency,"
            " booked_on, raw)"
            f" VALUES ('booking', {account}, {values}, -1, 'EUR', '2026-02-01', '{{}}')"
        )


# ---- derived entries, locks, change values -----------------------------------------------------------


def test_the_accounts_derived_entries_follow_its_bookings(scene: Scene) -> None:
    account = scene.clearance()
    scene.deliver(doc("A1", line("A", -1000)))
    assert scene.balance(account) == -1000
    # the user states that the account is at 0 on March 1st: the reconciliation says what is missing
    set_manual_record(scene.engine, account, date(2026, 3, 1), 0)
    recon = "SELECT amount FROM ledger_entry WHERE account_id = :a AND type = 'reconciliation'"
    assert [r.amount for r in scene.q(recon, a=account)] == [1000]
    scene.deliver(doc("A1", line("A", -1500)))  # the booking follows; its account's derived entries with it
    assert [r.amount for r in scene.q(recon, a=account)] == [1500]
    assert scene.balance(account) == 0


def test_the_step_moves_the_change_values_of_the_accounts_it_wrote_on(scene: Scene) -> None:
    account = scene.clearance(providers=())
    scene.deliver(doc("A1"))  # no account takes it yet
    assert scene.bookings() == []
    seen: list[frozenset[str]] = []
    install_change_hooks(scene.engine, seen.append)
    scene.exec(
        "INSERT INTO clearance_provider (account_id, currency, provider) VALUES (:a, 'EUR', 'Amazon')",
        a=account,
    )
    assert settle(scene.engine).error is None
    assert scene.booking() is not None
    keys = frozenset().union(*seen)
    assert {"ledger", "documents", f"account:{account}"} <= keys
    seen.clear()
    assert settle(scene.engine).touched_entry_ids == ()
    assert f"account:{account}" not in frozenset().union(*seen)  # a settle that writes nothing locks nothing


# ---- a booking follows its document ------------------------------------------------------------------


def confirm(scene: Scene, entries: list, category: int) -> None:
    """The user's decisions on every entry: a category and a payee-free flow, under user keys."""
    for e in entries:
        scene.exec(
            "UPDATE ledger_entry SET category_id = :c, derivation = CAST(:d AS jsonb) WHERE id = :i",
            c=category,
            d=json.dumps({"type": BOOKING_KEY, "category": {"pass": "user"}}),
            i=e.id,
        )
    settle(scene.engine)


def test_an_amount_only_change_keeps_values_keys_and_ids(scene: Scene) -> None:
    scene.clearance()
    scene.deliver(doc("A1", line("A", -500), line("B", -500)))
    before = scene.entries()
    books = scene.category()
    confirm(scene, before, books)
    before = scene.entries()
    scene.deliver(doc("A1", line("A", -600), line("B", -500)))
    after = scene.entries()
    assert [e.id for e in after] == [e.id for e in before]
    assert amounts(after) == [-600, -500]
    assert [e.category_id for e in after] == [books, books]
    assert [e.derivation for e in after] == [e.derivation for e in before]
    assert [e.review_flags for e in after] == [[], []]  # still confirmed: an amount is not an input
    assert scene.booking().amount == -1100
    assert sum(amounts(after)) == -1100


def test_a_changed_line_text_resolves_that_entry_afresh_confirmed_or_not(scene: Scene) -> None:
    scene.clearance()
    scene.deliver(doc("A1", line("USB-C cable", -500), line("Paperback", -500)))
    books = scene.category()
    confirm(scene, scene.entries(), books)
    first, second = scene.entries()
    assert (first.derivation["category"], second.derivation["category"]) == ({"pass": "user"},) * 2
    scene.deliver(doc("A1", line("HDMI cable", -500), line("Paperback", -500)))
    new_first, new_second = scene.entries()
    assert new_first.id == first.id and texts([new_first]) == ["HDMI cable"]
    # resolved afresh: the user's decision is not kept, whatever the passes now make of it
    assert new_first.derivation.get("category") != {"pass": "user"}
    assert new_first.derivation["type"] == BOOKING_KEY
    assert "unconfirmed" in new_first.review_flags or "unclassified" in new_first.review_flags
    # the entry whose text is unchanged is as it was
    assert (new_second.id, new_second.category_id, new_second.derivation) == (
        second.id,
        second.category_id,
        second.derivation,
    )


def test_a_removed_line_deletes_its_entry_with_its_tags_the_original_stays(scene: Scene) -> None:
    scene.clearance()
    scene.deliver(doc("A1", line("A", -100), line("B", -200), line("C", -300)))
    first, second, third = scene.entries()
    tag = scene.exec_returning("INSERT INTO tag (name) VALUES ('gift') RETURNING id")
    for e in (first, third):
        scene.exec("INSERT INTO ledger_entry_tag (ledger_entry_id, tag_id) VALUES (:e, :t)", e=e.id, t=tag)
    scene.deliver(doc("A1", line("A", -100), line("B", -200)))
    entries = scene.entries()
    assert [e.id for e in entries] == [first.id, second.id]
    assert amounts(entries) == [-100, -200] and scene.booking().amount == -300
    assert [r.ledger_entry_id for r in scene.q("SELECT ledger_entry_id FROM ledger_entry_tag")] == [first.id]


def test_removing_a_line_before_the_last_shifts_the_later_entries_by_position(scene: Scene) -> None:
    scene.clearance()
    scene.deliver(doc("A1", line("A", -100), line("B", -200), line("C", -300)))
    first, second, third = scene.entries()
    scene.deliver(doc("A1", line("B", -200), line("C", -300)))
    entries = scene.entries()
    assert [e.id for e in entries] == [first.id, second.id]  # the third position is gone, the first stays
    assert (texts(entries), amounts(entries)) == (["B", "C"], [-200, -300])
    assert third.id not in [e.id for e in entries]


def test_a_new_line_gets_a_new_entry_resolved_like_any(scene: Scene) -> None:
    scene.clearance()
    books = scene.category("Books")
    scene.exec(
        "INSERT INTO rule (sets, category_id, conditions, name) VALUES ('category', :c,"
        " CAST(:cond AS jsonb), 'Amazon')",
        c=books,
        cond=json.dumps([{"field": "counterparty_name", "op": "equals", "value": "Amazon"}]),
    )
    scene.deliver(doc("A1", line("A", -100)))
    (first,) = scene.entries()
    scene.deliver(doc("A1", line("A", -100), line("B", -200)))
    entries = scene.entries()
    assert [e.id for e in entries][0] == first.id and len(entries) == 2
    assert entries[1].id > first.id and entries[1].source_text == "B"
    assert entries[1].category_id == books and entries[1].derivation["type"] == BOOKING_KEY
    assert sum(amounts(entries)) == scene.booking().amount == -300


def test_a_changed_date_and_a_flipped_sign_follow_on_the_row_and_its_entries(scene: Scene) -> None:
    scene.clearance()
    scene.deliver(doc("A1", line("A", -100)))
    scene.deliver(doc("A1", line("A", 100), occurred_on=date(2026, 3, 5)))
    b = scene.booking()
    assert (b.booked_on, b.amount, b.purpose) == (date(2026, 3, 5), 100, "Refund A1")
    (e,) = scene.entries()
    assert (e.booked_on, e.amount) == (date(2026, 3, 5), 100)


def test_the_booking_never_drops_its_original_entry(scene: Scene) -> None:
    scene.clearance()
    scene.deliver(doc("A1", line("A", -100), line("B", -200)))
    first = scene.entries()[0]
    scene.deliver(doc("A1", line("Coupon", 50), total=-300))  # no line of the total's sign any more
    (only,) = scene.entries()
    assert only.id == first.id and only.source_text is None and only.amount == -300


def test_a_total_that_becomes_zero_removes_the_booking_with_its_entries_and_tags(scene: Scene) -> None:
    account = scene.clearance()
    scene.deliver(doc("A1", line("A", -100)))
    (e,) = scene.entries()
    tag = scene.exec_returning("INSERT INTO tag (name) VALUES ('gift') RETURNING id")
    scene.exec("INSERT INTO ledger_entry_tag (ledger_entry_id, tag_id) VALUES (:e, :t)", e=e.id, t=tag)
    scene.deliver(doc("A1", line("A", 0), total=0))
    assert scene.booking() is None and scene.bookings() == []
    assert scene.q("SELECT id FROM ledger_entry WHERE source_transaction_id IS NOT NULL") == []
    assert scene.q("SELECT 1 FROM ledger_entry_tag") == []
    assert scene.balance(account) == 0


def test_a_currency_change_removes_the_booking_and_books_it_where_the_new_currency_goes(scene: Scene) -> None:
    eur = scene.clearance("Amazon.de")
    scene.deliver(doc("A1", line("A", -100)))
    assert scene.booking().account_id == eur
    scene.deliver(doc("A1", line("A", -100), currency="USD"))
    assert scene.booking() is None  # no account takes Amazon in USD
    assert scene.balance(eur) == 0
    usd = scene.clearance("Amazon.com", currency="USD")  # now one does: booked by the settle that follows
    b = scene.booking()
    assert b is not None and (b.account_id, b.currency) == (usd, "USD")
    assert settle(scene.engine).touched_entry_ids == ()


def test_a_currency_change_with_a_usd_account_moves_the_booking_in_one_settle(scene: Scene) -> None:
    eur = scene.clearance("Amazon.de")
    usd = scene.clearance("Amazon.com", currency="USD")
    scene.deliver(doc("A1", line("A", -100)))
    assert scene.booking().account_id == eur
    scene.deliver(doc("A1", line("A", -100), currency="USD"))
    assert scene.booking().account_id == usd
    assert scene.balance(eur) == 0 and scene.balance(usd) == -100
    assert settle(scene.engine).touched_entry_ids == ()


# ---- providers and the start steer only what is not booked yet --------------------------------------


def test_removing_or_moving_a_provider_leaves_bookings_where_they_are(scene: Scene) -> None:
    a = scene.clearance("Amazon.de")
    b = scene.clearance("Amazon 2", providers=())
    scene.deliver(doc("A1", line("A", -100)))
    set_clearance_providers(scene.engine, a, [])
    assert scene.booking().account_id == a
    set_clearance_providers(scene.engine, b, ["Amazon"])
    assert scene.booking().account_id == a  # the booked document stays
    scene.deliver(doc("A2", line("B", -50)))  # a document not yet booked follows the new lists
    assert scene.booking("A2").account_id == b


def test_an_earlier_start_books_what_it_now_covers_and_a_later_one_removes_nothing(scene: Scene) -> None:
    account = scene.clearance()
    scene.deliver(doc("OLD", occurred_on=date(2026, 1, 15)), doc("NEW", occurred_on=date(2026, 2, 15)))
    assert (scene.booking("OLD"), scene.booking("NEW") is not None) == (None, True)
    record = scene.q("SELECT id FROM balance_record WHERE account_id = :a", a=account)[0].id
    update_manual_record(scene.engine, record, balance=0, balance_on=date(2026, 1, 1))
    assert scene.booking("OLD") is not None
    update_manual_record(scene.engine, record, balance=0, balance_on=date(2026, 6, 1))
    assert scene.booking("OLD") is not None and scene.booking("NEW") is not None
    scene.deliver(doc("LATER", occurred_on=date(2026, 3, 1)))  # but it steers what is not booked yet
    assert scene.booking("LATER") is None


# ---- re-delivery ---------------------------------------------------------------------------------------


def test_keep_leaves_the_stored_document_and_its_booking_and_counts_it(scene: Scene) -> None:
    scene.clearance()
    scene.deliver(doc("A1", line("A", -100)))
    result = scene.deliver(doc("A1", line("A", -999)), doc("A2", line("B", -50)), redelivery="keep")
    assert (result.inserted, result.updated, result.kept, result.changed) == (1, 0, 1, ())
    assert scene.q("SELECT total, version FROM external_document WHERE external_id = 'A1'")[0] == (-100, 1)
    assert scene.booking().amount == -100
    stats = scene.q("SELECT stats FROM import_run WHERE id = :i", i=result.run_id)[0].stats
    assert (stats["inserted"], stats["updated"], stats["kept"]) == (1, 0, 1)


def test_replace_updates_the_document_and_its_booking(scene: Scene) -> None:
    scene.clearance()
    scene.deliver(doc("A1", line("A", -100)))
    result = scene.deliver(doc("A1", line("A", -999)), redelivery="replace")
    assert (result.updated, result.kept) == (1, 0) and len(result.changed) == 1
    assert scene.q("SELECT total, version FROM external_document WHERE external_id = 'A1'")[0] == (-999, 2)
    assert scene.booking().amount == -999
