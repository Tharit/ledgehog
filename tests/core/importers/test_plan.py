"""Where a fetch starts, what "sync everything" would do, and the validation of a start (spec §5.4, §5.11;
architecture §4.1)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

import pytest

from app.core.accounts import AccountMissing, close_account
from app.core.importers.instances import (
    AccountClosed,
    InstanceDisabled,
    InstanceMissing,
    NotAnAccountSource,
    link_account,
    update_instance,
)
from app.core.importers.plan import (
    OVERLAP_DAYS,
    ImporterUnavailable,
    InstanceForbidden,
    InvalidItem,
    ItemRequest,
    JobPlan,
    NotAFetchSource,
    NothingToSync,
    PlannedItem,
    StartNotEditable,
    documents_start,
    fetch_start,
    plan_discovery,
    plan_start,
    read_plan,
)
from app.core.importers.upload import AccountNotLinked
from app.core.plugins.errors import InvalidProfile
from app.plugins.importers.csv import CsvImporter
from tests.core.importers.conftest import Db, make_acct, make_instance
from tests.invariants.helpers import (
    make_balance_record,
    make_derived_entry,
    make_entry,
    make_run,
    make_source,
)

TODAY = date(2026, 6, 15)
DEFAULT = date(2026, 1, 1)


class StubFetch:
    """A registered fetch importer: only what planning reads."""

    emits = frozenset({"transactions", "documents"})
    providers = frozenset({"paypal"})

    def validate_settings(self, settings: Mapping[str, Any]) -> None:
        return None

    def default_fetch_start(self, settings: Mapping[str, Any], *, today: date) -> date:
        return date.fromisoformat(settings.get("default_start", DEFAULT.isoformat()))

    def open(self, *a: Any, **k: Any) -> Any:
        raise NotImplementedError


class TransactionsOnly(StubFetch):
    emits = frozenset({"transactions"})


IMPORTERS: dict[str, object] = {"bank": StubFetch(), "txonly": TransactionsOnly(), "csv": CsvImporter()}


def instance(db: Db, importer: str = "bank", **kw: Any) -> int:
    kw.setdefault("emits", ["transactions", "documents"] if importer == "bank" else ["transactions"])
    kw.setdefault("access", "shared")
    return make_instance(db, importer=importer, label=importer, **kw)


def linked(db: Db, iid: int, ref: str, name: str | None = None) -> int:
    acct = make_acct(db, name or ref)
    link_account(db.engine, iid, acct, ref)
    return acct


def user(db: Db, login: str) -> int:
    db.run("INSERT INTO app_user (login, pw_hash, display_name) VALUES (:l, 'x', :l)", l=login)
    return int(db.one("SELECT id FROM app_user WHERE login = :l", l=login)[0])


def start_of(db: Db, account: int, settings: Mapping[str, Any] | None = None) -> Any:
    with db.engine.connect() as conn:
        return fetch_start(conn, account, StubFetch(), settings or {}, TODAY)


# ---- the fetch start -------------------------------------------------------------------------------


def test_with_coverage_the_start_is_the_sync_position_less_the_overlap(db: Db) -> None:
    acct = make_acct(db)
    with db.engine.begin() as conn:
        make_run(conn, acct, covered_through=date(2026, 6, 1))
        make_run(conn, acct, covered_through=date(2026, 5, 1))  # an older one: the latest wins
    got = start_of(db, acct)
    assert (got.since, got.source) == (date(2026, 6, 1) - timedelta(days=OVERLAP_DAYS), "coverage")
    assert OVERLAP_DAYS == 7


def test_the_overlap_never_reaches_before_the_day_after_the_latest_user_authored_row(db: Db) -> None:
    acct = make_acct(db)
    with db.engine.begin() as conn:
        make_run(conn, acct, covered_through=date(2026, 6, 1))
        make_entry(conn, make_source(conn, acct, importer=None, booked_on=date(2026, 5, 29)))
    assert start_of(db, acct).since == date(2026, 5, 30)


def test_a_user_authored_row_older_than_the_overlap_changes_nothing(db: Db) -> None:
    acct = make_acct(db)
    with db.engine.begin() as conn:
        make_run(conn, acct, covered_through=date(2026, 6, 1))
        make_entry(conn, make_source(conn, acct, importer=None, booked_on=date(2026, 3, 1)))
    assert start_of(db, acct).since == date(2026, 5, 25)


def test_an_imported_row_never_raises_the_floor(db: Db) -> None:
    acct = make_acct(db)
    with db.engine.begin() as conn:
        make_run(conn, acct, covered_through=date(2026, 6, 1))
        make_entry(conn, make_source(conn, acct, importer="test", booked_on=date(2026, 5, 31)))
    assert start_of(db, acct).since == date(2026, 5, 25)


def test_without_coverage_the_start_is_the_day_after_the_latest_entry(db: Db) -> None:
    acct = make_acct(db)
    with db.engine.begin() as conn:
        make_entry(conn, make_source(conn, acct, importer=None, booked_on=date(2026, 2, 10)))
        make_entry(conn, make_source(conn, acct, importer=None, booked_on=date(2026, 2, 3)))
    got = start_of(db, acct)
    assert (got.since, got.source) == (date(2026, 2, 11), "latest_entry")


def test_derived_entries_count_as_entries(db: Db) -> None:
    acct = make_acct(db)
    with db.engine.begin() as conn:
        make_entry(conn, make_source(conn, acct, importer=None, booked_on=date(2026, 2, 10)))
        record = make_balance_record(conn, acct, balance_on=date(2026, 3, 20))
        make_derived_entry(conn, acct, record, type="reconciliation", booked_on=date(2026, 3, 20))
    assert start_of(db, acct).since == date(2026, 3, 21)


def test_a_reverted_run_gives_no_coverage(db: Db) -> None:
    acct = make_acct(db)
    with db.engine.begin() as conn:
        make_run(conn, acct, status="reverted", covered_through=date(2026, 6, 1))
        make_entry(conn, make_source(conn, acct, importer=None, booked_on=date(2026, 2, 10)))
    got = start_of(db, acct)
    assert (got.since, got.source) == (date(2026, 2, 11), "latest_entry")


def test_with_neither_the_start_is_the_importers_default(db: Db) -> None:
    acct = make_acct(db)
    got = start_of(db, acct, {"default_start": "2025-11-30"})
    assert (got.since, got.source) == (date(2025, 11, 30), "importer_default")


def test_a_start_is_never_after_today(db: Db) -> None:
    acct = make_acct(db)
    with db.engine.begin() as conn:
        make_entry(conn, make_source(conn, acct, importer=None, booked_on=date(2026, 7, 1)))
    assert start_of(db, acct).since == TODAY
    other = make_acct(db, "Other")
    assert start_of(db, other, {"default_start": "2027-01-01"}).since == TODAY


def test_the_document_start_is_the_instances_start_date_else_the_default() -> None:
    assert documents_start(StubFetch(), {"start_date": "2026-02-02"}, TODAY) == date(2026, 2, 2)
    assert documents_start(StubFetch(), {}, TODAY) == DEFAULT
    with pytest.raises(InvalidProfile):
        documents_start(StubFetch(), {"start_date": "soon"}, TODAY)


# ---- the plan read ---------------------------------------------------------------------------------


def test_the_plan_lists_what_everything_would_do(db: Db) -> None:
    me, other = user(db, "me"), user(db, "other")
    shared = instance(db, "bank", settings={"start_date": "2026-03-03"})
    mine = instance(db, "txonly", access="owner", owner_id=me)
    theirs = instance(db, "txonly", access="owner", owner_id=other)
    a1, a2 = linked(db, shared, "A1"), linked(db, shared, "A2")
    a3 = linked(db, mine, "B1")
    linked(db, theirs, "C1")
    with db.engine.begin() as conn:
        make_run(conn, a1, covered_through=date(2026, 6, 10))
    with db.engine.connect() as conn:
        plan = read_plan(conn, me, IMPORTERS, TODAY, busy={mine})
    assert [p.instance_id for p in plan] == [shared, mine]  # the other user's instance is absent
    first, second = plan
    assert first.busy is False and second.busy is True
    assert first.documents_since == date(2026, 3, 3) and second.documents_since is None
    assert [(a.account_id, a.external_ref, a.since_source, a.editable) for a in first.accounts] == [
        (a1, "A1", "coverage", False),
        (a2, "A2", "importer_default", True),
    ]
    assert first.accounts[0].since == date(2026, 6, 3)
    assert [(a.account_id, a.since) for a in second.accounts] == [(a3, DEFAULT)]


def test_the_plan_leaves_out_disabled_file_unregistered_closed_and_empty(db: Db) -> None:
    me = user(db, "me")
    ok = instance(db, "txonly")
    acct = linked(db, ok, "A")
    closed = linked(db, ok, "Z")
    close_account(db.engine, closed, date(2026, 5, 1))
    disabled = instance(db, "txonly")
    linked(db, disabled, "D")
    update_instance(db.engine, disabled, disabled=True)
    filey = instance(db, "csv")
    linked(db, filey, "acct-1")
    gone = instance(db, "ghost")
    linked(db, gone, "G")
    instance(db, "txonly")  # nothing linked: nothing to run
    with db.engine.connect() as conn:
        plan = read_plan(conn, me, IMPORTERS, TODAY)
    assert [(p.instance_id, [a.account_id for a in p.accounts]) for p in plan] == [(ok, [acct])]


# ---- starting: everything ----------------------------------------------------------------------------


def test_everything_is_a_job_per_instance_accounts_by_id_then_documents(db: Db) -> None:
    me = user(db, "me")
    shared = instance(db, "bank")
    mine = instance(db, "txonly", access="owner", owner_id=me)
    a2, a1 = linked(db, shared, "A2"), linked(db, shared, "A1")
    b = linked(db, mine, "B")
    with db.engine.connect() as conn:
        jobs = plan_start(conn, me, None, IMPORTERS, TODAY)
    assert jobs == (
        JobPlan(
            shared,
            (
                PlannedItem("transactions", a2),
                PlannedItem("transactions", a1),
                PlannedItem("documents", None),
            ),
        ),
        JobPlan(mine, (PlannedItem("transactions", b),)),
    )
    assert a2 < a1  # ids ascend: A2 was created first


def test_everything_with_nothing_to_run_is_refused(db: Db) -> None:
    me = user(db, "me")
    instance(db, "txonly")  # no account linked
    with db.engine.connect() as conn, pytest.raises(NothingToSync):
        plan_start(conn, me, None, IMPORTERS, TODAY)


# ---- starting: explicit items --------------------------------------------------------------------------


def start(db: Db, user_id: int, *items: ItemRequest) -> tuple[JobPlan, ...]:
    with db.engine.connect() as conn:
        return plan_start(conn, user_id, list(items), IMPORTERS, TODAY)


def test_an_instance_item_expands_to_its_open_accounts_and_documents(db: Db) -> None:
    me = user(db, "me")
    iid = instance(db, "bank")
    a1 = linked(db, iid, "A1")
    closed = linked(db, iid, "Z")
    close_account(db.engine, closed, date(2026, 5, 1))
    assert start(db, me, ItemRequest(iid)) == (
        JobPlan(iid, (PlannedItem("transactions", a1), PlannedItem("documents", None))),
    )


def test_one_account_or_one_kind(db: Db) -> None:
    me = user(db, "me")
    iid = instance(db, "bank")
    a1, a2 = linked(db, iid, "A1"), linked(db, iid, "A2")
    assert start(db, me, ItemRequest(iid, account_id=a2)) == (
        JobPlan(iid, (PlannedItem("transactions", a2),)),
    )
    assert start(db, me, ItemRequest(iid, kind="documents")) == (
        JobPlan(iid, (PlannedItem("documents", None),)),
    )
    assert start(db, me, ItemRequest(iid, kind="transactions")) == (
        JobPlan(iid, (PlannedItem("transactions", a1), PlannedItem("transactions", a2))),
    )


def test_items_merge_per_instance_and_instances_come_in_id_order(db: Db) -> None:
    me = user(db, "me")
    first, second = instance(db, "bank"), instance(db, "txonly")
    a1 = linked(db, first, "A1")
    b = linked(db, second, "B")
    got = start(
        db,
        me,
        ItemRequest(second, account_id=b),
        ItemRequest(first, account_id=a1),
        ItemRequest(first, account_id=a1),
    )
    assert got == (
        JobPlan(first, (PlannedItem("transactions", a1),)),
        JobPlan(second, (PlannedItem("transactions", b),)),
    )


def test_a_since_is_carried_for_an_account_without_coverage(db: Db) -> None:
    me = user(db, "me")
    iid = instance(db, "bank")
    acct = linked(db, iid, "A")
    got = start(db, me, ItemRequest(iid, account_id=acct, since=date(2026, 1, 15)))
    assert got[0].items == (PlannedItem("transactions", acct, date(2026, 1, 15)),)
    assert start(db, me, ItemRequest(iid, account_id=acct, since=TODAY))  # today is allowed


def test_refusals_of_a_start(db: Db) -> None:
    me, other = user(db, "me"), user(db, "other")
    bank = instance(db, "bank")
    acct = linked(db, bank, "A")
    covered = linked(db, bank, "B")
    with db.engine.begin() as conn:
        make_run(conn, covered, covered_through=date(2026, 6, 1))
    elsewhere = make_acct(db, "Elsewhere")
    closed = linked(db, bank, "C")
    close_account(db.engine, closed, date(2026, 5, 1))
    theirs = instance(db, "txonly", access="owner", owner_id=other)
    off = instance(db, "txonly")
    update_instance(db.engine, off, disabled=True)
    filey = instance(db, "csv")
    ghost = instance(db, "ghost")
    plain = instance(db, "txonly")
    docs_only = instance(db, "bank", emits=["documents"])

    cases: list[tuple[type[Exception], ItemRequest]] = [
        (InstanceMissing, ItemRequest(9999)),
        (InstanceForbidden, ItemRequest(theirs)),
        (InstanceDisabled, ItemRequest(off)),
        (NotAFetchSource, ItemRequest(filey)),
        (ImporterUnavailable, ItemRequest(ghost)),
        (AccountMissing, ItemRequest(bank, account_id=9999)),
        (AccountNotLinked, ItemRequest(bank, account_id=elsewhere)),
        (AccountClosed, ItemRequest(bank, account_id=closed)),
        (StartNotEditable, ItemRequest(bank, account_id=covered, since=date(2026, 1, 1))),
        (InvalidItem, ItemRequest(bank, account_id=acct, since=TODAY + timedelta(days=1))),
        (InvalidItem, ItemRequest(bank, since=date(2026, 1, 1))),  # a start goes with an account
        (InvalidItem, ItemRequest(bank, account_id=acct, kind="documents")),
        (InvalidItem, ItemRequest(plain, kind="documents")),  # it delivers none
        (NotAnAccountSource, ItemRequest(docs_only, kind="transactions")),
    ]
    for expected, item in cases:
        with pytest.raises(expected):
            start(db, me, item)
    # one bad item refuses the whole start: nothing is half-planned
    with pytest.raises(InstanceForbidden):
        start(db, me, ItemRequest(bank, account_id=acct), ItemRequest(theirs))
    # an instance with nothing to run, named explicitly, leaves nothing to sync
    with pytest.raises(NothingToSync):
        start(db, me, ItemRequest(plain))


def test_the_invalid_item_names_its_field(db: Db) -> None:
    me = user(db, "me")
    iid = instance(db, "bank")
    with pytest.raises(InvalidItem) as err:
        start(db, me, ItemRequest(iid, since=date(2026, 1, 1)))
    assert err.value.field == "since"


# ---- discovery -------------------------------------------------------------------------------------------


def test_a_discovery_is_planned_with_no_items(db: Db) -> None:
    me = user(db, "me")
    iid = instance(db, "bank")
    with db.engine.connect() as conn:
        assert plan_discovery(conn, me, iid, IMPORTERS) == JobPlan(iid)


def test_a_discovery_is_refused_like_a_start_and_for_an_instance_without_transactions(db: Db) -> None:
    me, other = user(db, "me"), user(db, "other")
    docs_only = instance(db, "bank", emits=["documents"])
    theirs = instance(db, "txonly", access="owner", owner_id=other)
    off = instance(db, "txonly")
    update_instance(db.engine, off, disabled=True)
    refusals: list[tuple[type[Exception], int]] = [
        (InstanceMissing, 9999),
        (InstanceForbidden, theirs),
        (InstanceDisabled, off),
        (NotAFetchSource, instance(db, "csv")),
        (ImporterUnavailable, instance(db, "ghost")),
        (NotAnAccountSource, docs_only),
    ]
    for expected, iid in refusals:
        with db.engine.connect() as conn, pytest.raises(expected):
            plan_discovery(conn, me, iid, IMPORTERS)
