"""Clearance accounts in core (spec §3.3): creation with a start, the provider list, the link refusal."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.accounts import (
    InvalidProvider,
    NotClearance,
    ProviderTaken,
    StartRequired,
    create_account,
    create_account_result,
    list_accounts,
    set_clearance_providers,
    update_account,
)
from app.core.importers.instances import ClearanceAccount, link_account
from tests.core.accounts.conftest import Db
from tests.core.importers.conftest import make_instance

START = date(2026, 1, 31)


def clearance(db: Db, name: str = "Amazon.de", currency: str = "EUR", **kw: object) -> int:
    kw.setdefault("start_date", START)
    return create_account(db.engine, name=name, kind="clearance", currency=currency, **kw)  # type: ignore[arg-type]


def providers(db: Db, account_id: int) -> list[str]:
    return [
        r.provider
        for r in db.q(
            "SELECT provider FROM clearance_provider WHERE account_id = :a ORDER BY provider", a=account_id
        )
    ]


def test_create_writes_the_opening_record_of_zero_at_the_end_of_the_start(db: Db) -> None:
    aid = clearance(db, providers=["Amazon"])
    records = db.q(
        "SELECT import_run_id, balance, balance_on, currency FROM balance_record WHERE account_id = :a", a=aid
    )
    assert [tuple(r) for r in records] == [(None, 0, START, "EUR")]  # manual: no run
    assert db.q("SELECT 1 FROM ledger_entry WHERE account_id = :a", a=aid) == []  # zero derives no entry
    assert providers(db, aid) == ["Amazon"]
    assert db.one("SELECT kind FROM account WHERE id = :a", a=aid).kind == "clearance"


def test_create_settles_so_that_documents_it_takes_are_booked(db: Db) -> None:
    result = create_account_result(
        db.engine, name="Amazon.de", kind="clearance", currency="EUR", start_date=START, providers=["Amazon"]
    )
    assert result.settle.error is None


def test_a_clearance_account_needs_a_start_and_no_other_kind_takes_one(db: Db) -> None:
    with pytest.raises(StartRequired):
        create_account(db.engine, name="Amazon.de", kind="clearance", currency="EUR")
    with pytest.raises(NotClearance) as e:
        create_account(db.engine, name="Giro", kind="checking", currency="EUR", start_date=START)
    assert e.value.field == "start_date"
    with pytest.raises(NotClearance) as e:
        create_account(db.engine, name="Giro", kind="checking", currency="EUR", providers=["Amazon"])
    assert e.value.field == "providers"
    assert db.q("SELECT 1 FROM account") == []  # nothing was written


def test_providers_are_trimmed_not_blank_and_one_spelling_per_name(db: Db) -> None:
    aid = clearance(db, providers=["  Amazon ", "AMAZON", "Amazon EU"])
    assert providers(db, aid) == ["Amazon", "Amazon EU"]
    with pytest.raises(InvalidProvider):
        set_clearance_providers(db.engine, aid, ["Amazon", "   "])
    assert providers(db, aid) == ["Amazon", "Amazon EU"]  # the refused write changed nothing


def test_writing_the_list_replaces_it_whole(db: Db) -> None:
    aid = clearance(db, providers=["Amazon", "Amazon EU"])
    result = set_clearance_providers(db.engine, aid, ["Audible"])
    assert result.providers == ("Audible",) and result.settle.error is None
    assert providers(db, aid) == ["Audible"]
    set_clearance_providers(db.engine, aid, [])
    assert providers(db, aid) == []
    assert [a.providers for a in list_accounts_of(db, aid)] == [()]


def list_accounts_of(db: Db, aid: int) -> list:
    with db.engine.connect() as conn:
        return [a for a in list_accounts(conn) if a.id == aid]


def test_a_provider_taken_in_the_same_currency_names_the_other_account(db: Db) -> None:
    first = clearance(db, "Amazon.de", providers=["Amazon"])
    second = clearance(db, "Amazon 2")
    with pytest.raises(ProviderTaken) as e:
        set_clearance_providers(db.engine, second, ["Audible", "amazon"])
    assert (e.value.provider, e.value.currency, e.value.account_id, e.value.account_name) == (
        "amazon",
        "EUR",
        first,
        "Amazon.de",
    )
    assert providers(db, second) == []  # the whole write is refused
    with pytest.raises(ProviderTaken):
        clearance(db, "Amazon 3", providers=["AMAZON"])
    assert [r.name for r in db.q("SELECT name FROM account WHERE kind = 'clearance' ORDER BY id")] == [
        "Amazon.de",
        "Amazon 2",
    ]  # the refused create left no account behind


def test_the_same_name_on_accounts_of_two_currencies_is_accepted(db: Db) -> None:
    eur = clearance(db, "Amazon.de", providers=["Amazon"])
    usd = clearance(db, "Amazon.com", currency="USD", providers=["Amazon"])
    assert providers(db, eur) == providers(db, usd) == ["Amazon"]


def test_an_account_may_rewrite_its_own_list_with_other_spellings(db: Db) -> None:
    aid = clearance(db, providers=["Amazon"])
    set_clearance_providers(db.engine, aid, ["AMAZON", "Amazon EU"])
    assert providers(db, aid) == ["AMAZON", "Amazon EU"]


def test_another_kind_of_account_has_no_providers(db: Db) -> None:
    giro = create_account(db.engine, name="Giro", kind="checking", currency="EUR")
    with pytest.raises(NotClearance):
        set_clearance_providers(db.engine, giro, ["Amazon"])


def test_a_clearance_account_is_never_linked_to_an_importer(db: Db) -> None:
    aid = clearance(db)
    instance = make_instance(db)
    with pytest.raises(ClearanceAccount):
        link_account(db.engine, instance, aid, "ref")
    assert db.q("SELECT 1 FROM account_source") == []


def test_update_account_writes_providers_with_the_other_fields_or_not_at_all(db: Db) -> None:
    first = clearance(db, "Amazon.de", providers=["Amazon"])
    second = clearance(db, "Amazon 2")
    update_account(db.engine, second, name="Renamed", providers=["Audible"])
    assert providers(db, second) == ["Audible"]
    with pytest.raises(ProviderTaken):
        update_account(db.engine, second, name="Again", providers=["Amazon"])
    (view,) = list_accounts_of(db, second)
    assert (view.name, view.providers) == ("Renamed", ("Audible",))  # the whole write was refused
    assert providers(db, first) == ["Amazon"]
    update_account(db.engine, second, name="Kept")  # absent: the list stays
    assert providers(db, second) == ["Audible"]


def test_update_account_providers_refused_on_another_kind(db: Db) -> None:
    giro = create_account(db.engine, name="Giro", kind="checking", currency="EUR")
    with pytest.raises(NotClearance) as e:
        update_account(db.engine, giro, providers=["Amazon"])
    assert e.value.field == "providers"
