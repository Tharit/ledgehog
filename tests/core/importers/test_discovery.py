"""Matching a discovered list to the accounts, computed on read (spec §5.4, architecture §4.1), and the
write-back of an importer's state."""

from __future__ import annotations

from datetime import date

from app.core.accounts import close_account, create_account
from app.core.importers.discovery import AccountMatch, DiscoveryEntry, match_discovered
from app.core.importers.instances import link_account, save_state
from app.core.plugins.fetch import DiscoveredAccount
from tests.core.importers.conftest import Db, make_acct, make_instance


def found(ref: str) -> DiscoveredAccount:
    return DiscoveredAccount(ref, f"Account {ref}", "EUR", "checking", frozenset({"transactions"}))


def match(db: Db, iid: int, *accounts: DiscoveredAccount) -> list[DiscoveryEntry]:
    with db.engine.connect() as conn:
        return match_discovered(conn, iid, list(accounts))


def test_a_discovered_account_linked_to_this_instance_is_reported_as_linked(db: Db) -> None:
    iid = make_instance(db, importer="bank")
    acct = make_acct(db)
    link_account(db.engine, iid, acct, "DE01")
    [entry] = match(db, iid, found("DE01"))
    assert (entry.linked_account_id, entry.matches_account) == (acct, None)


def test_a_link_on_another_instance_does_not_count_as_linked_here(db: Db) -> None:
    mine, other = make_instance(db, importer="bank"), make_instance(db, importer="bank", label="Other")
    acct = make_acct(db)
    link_account(db.engine, other, acct, "DE01")
    [entry] = match(db, mine, found("DE01"))
    assert (entry.linked_account_id, entry.matches_account) == (None, None)


def test_an_account_with_the_same_external_reference_matches_under_the_canonicalisation(db: Db) -> None:
    iid = make_instance(db, importer="bank")
    acct = create_account(db.engine, name="Giro", kind="checking", currency="EUR", external_ref="DE 01-abc")
    [entry] = match(db, iid, found("de01ABC"))
    assert (entry.linked_account_id, entry.matches_account) == (None, AccountMatch(acct, False))


def test_a_match_to_a_closed_account_is_flagged_closed(db: Db) -> None:
    iid = make_instance(db, importer="bank")
    acct = create_account(db.engine, name="Old", kind="checking", currency="EUR", external_ref="OLD1")
    close_account(db.engine, acct, date(2026, 1, 31))
    [entry] = match(db, iid, found("OLD1"))
    assert entry.matches_account == AccountMatch(acct, True)


def test_an_unknown_account_has_neither_and_the_order_and_pockets_are_kept(db: Db) -> None:
    iid = make_instance(db, importer="bank")
    acct = create_account(db.engine, name="Main", kind="checking", currency="EUR", external_ref="MAIN-EUR")
    pocket = DiscoveredAccount("MAIN-USD", "Main USD", "USD", "checking", frozenset({"transactions"}))
    nothing = DiscoveredAccount("DEPOT", "Depot", None, "depot", frozenset())
    entries = match(db, iid, found("MAIN-EUR"), pocket, nothing)
    assert [e.account.external_ref for e in entries] == ["MAIN-EUR", "MAIN-USD", "DEPOT"]
    assert entries[0].matches_account == AccountMatch(acct, False)
    assert entries[1].linked_account_id is None and entries[1].matches_account is None  # an offer
    assert entries[2].account.capabilities == frozenset()  # listed, not offered for linking


def test_an_empty_list_matches_nothing(db: Db) -> None:
    assert match(db, make_instance(db, importer="bank")) == []


# ---- save_state ------------------------------------------------------------------------------------------


def test_save_state_writes_a_changed_state_and_only_then(db: Db) -> None:
    iid = make_instance(db, importer="bank")
    assert save_state(db.engine, iid, {"tan_medium": "2"}) is True
    assert db.one("SELECT state FROM importer_instance WHERE id = :i", i=iid)[0] == {"tan_medium": "2"}
    assert save_state(db.engine, iid, {"tan_medium": "2"}) is False  # unchanged: no write
    assert save_state(db.engine, iid, {}) is True  # cleared


def test_save_state_of_a_deleted_instance_is_no_error(db: Db) -> None:
    assert save_state(db.engine, 9999, {"a": 1}) is False
