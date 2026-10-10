"""Importer instances: create, update, reset, delete, list (spec §5.4, architecture §4.1)."""

from __future__ import annotations

from typing import Any

import pytest

from app.core.importers import instances
from app.core.importers.instances import (
    InstanceHasRuns,
    InstanceMissing,
    InvalidInstance,
    create_instance,
    delete_instance,
    link_account,
    list_instances,
    reset_instance,
    update_instance,
)
from app.core.settle.settle import SettleResult
from tests.core.importers.conftest import Db, make_acct, make_instance
from tests.invariants.helpers import make_run


def _row(db: Db, iid: int) -> Any:
    return db.one("SELECT * FROM importer_instance WHERE id = :i", i=iid)


def test_create_a_csv_instance(db: Db) -> None:
    iid = create_instance(
        db.engine, importer="csv", label="Giro", settings={"a": 1}, emits=["transactions"], access="shared"
    )
    r = _row(db, iid)
    assert (r.importer, r.label, r.settings, r.state, r.disabled) == ("csv", "Giro", {"a": 1}, {}, False)
    assert (r.emits, r.access, r.owner_id) == (["transactions"], "shared", None)
    db.assert_checks_clean()


def test_create_an_owned_instance(db: Db, user_id: int) -> None:
    iid = create_instance(
        db.engine,
        importer="fints",
        label="Bank",
        settings={},
        emits=["transactions"],
        access="owner",
        owner_id=user_id,
    )
    assert (_row(db, iid).access, _row(db, iid).owner_id) == ("owner", user_id)


def test_create_runs_the_injected_validator_before_writing(db: Db) -> None:
    seen: list[Any] = []

    def refuse(settings: Any) -> None:
        seen.append(dict(settings))
        raise ValueError("bad profile")

    with pytest.raises(ValueError, match="bad profile"):
        make_instance(db, settings={"x": 1}, validate=refuse)
    assert seen == [{"x": 1}]
    assert db.one("SELECT count(*) FROM importer_instance")[0] == 0


@pytest.mark.parametrize(
    "kw",
    [
        {"emits": []},
        {"emits": ["bogus"]},
        {"access": "owner"},  # owner access needs an owner
        {"access": "shared", "owner_id": 1},  # shared has none
        {"access": "owner", "owner_id": 999},  # no such user
        {"access": "nobody"},
        {"label": " "},
    ],
    ids=[
        "no-emits",
        "bad-emits",
        "owner-missing",
        "shared-owned",
        "unknown-owner",
        "bad-access",
        "blank-label",
    ],
)
def test_create_refuses_invalid_instances(db: Db, kw: dict[str, Any]) -> None:
    with pytest.raises(InvalidInstance):
        make_instance(db, **kw)
    assert db.one("SELECT count(*) FROM importer_instance")[0] == 0


def test_update_changes_label_settings_and_disabled(db: Db, settle_spy: Any) -> None:
    calls = settle_spy(instances)
    iid = make_instance(db)
    update_instance(db.engine, iid, label="New", settings={"k": "v"}, disabled=True)
    r = _row(db, iid)
    assert (r.label, r.settings, r.disabled) == ("New", {"k": "v"}, True)
    update_instance(db.engine, iid, disabled=False)
    assert (_row(db, iid).label, _row(db, iid).disabled) == ("New", False)
    assert calls == []  # nothing settling reads


def test_update_validates_settings_and_refuses_the_unknown(db: Db) -> None:
    iid = make_instance(db, settings={"a": 1})

    def refuse(s: Any) -> None:
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        update_instance(db.engine, iid, settings={"a": 2}, validate=refuse)
    assert _row(db, iid).settings == {"a": 1}
    with pytest.raises(InstanceMissing):
        update_instance(db.engine, 999, label="x")
    with pytest.raises(InvalidInstance):
        update_instance(db.engine, iid, label="")


def test_reset_clears_state_and_keeps_settings(db: Db) -> None:
    iid = make_instance(db, settings={"keep": True})
    db.run('UPDATE importer_instance SET state = \'{"system_id": "abc"}\' WHERE id = :i', i=iid)
    reset_instance(db.engine, iid)
    r = _row(db, iid)
    assert r.state == {} and r.settings == {"keep": True}
    with pytest.raises(InstanceMissing):
        reset_instance(db.engine, 999)


def test_delete_without_runs_removes_it_and_its_links_and_settles(db: Db, settle_spy: Any) -> None:
    iid = make_instance(db)
    acct = make_acct(db)
    link_account(db.engine, iid, acct, "r1")
    calls = settle_spy(instances)
    delete_instance(db.engine, iid)
    assert db.one("SELECT count(*) FROM importer_instance")[0] == 0
    assert db.one("SELECT count(*) FROM account_source")[0] == 0
    assert db.one("SELECT synced FROM v_account_synced WHERE account_id = :a", a=acct)[0] is False
    assert calls == [1]
    db.assert_checks_clean()


@pytest.mark.parametrize("status", ["ok", "failed", "running", "reverted"])
def test_delete_is_refused_while_it_has_runs(db: Db, status: str, settle_spy: Any) -> None:
    calls = settle_spy(instances)
    iid = make_instance(db)
    acct = make_acct(db)
    with db.engine.begin() as c:
        make_run(c, acct, status=status, instance_id=iid)
    with pytest.raises(InstanceHasRuns, match="disable"):
        delete_instance(db.engine, iid)
    assert db.one("SELECT count(*) FROM importer_instance")[0] == 1
    assert calls == []


def test_delete_missing_instance(db: Db) -> None:
    with pytest.raises(InstanceMissing):
        delete_instance(db.engine, 999)


def test_list_instances(db: Db) -> None:
    a = make_instance(db, label="A")
    b = make_instance(db, label="B")
    one, two = make_acct(db, "One"), make_acct(db, "Two")
    link_account(db.engine, a, one, "x1")
    link_account(db.engine, a, two, "x2")
    update_instance(db.engine, b, disabled=True)
    db.run("UPDATE importer_instance SET state = '{\"secret\": 1}' WHERE id = :i", i=a)
    with db.engine.begin() as c:
        make_run(c, one, instance_id=a)
    with db.engine.connect() as conn:
        views = {v.id: v for v in list_instances(conn)}
    va, vb = views[a], views[b]
    assert (va.label, va.importer, va.emits, va.access, va.owner_id, va.disabled) == (
        "A",
        "csv",
        ("transactions",),
        "shared",
        None,
        False,
    )
    assert [(x.account_id, x.external_ref) for x in va.accounts] == [(one, "x1"), (two, "x2")]
    assert va.last_run_at is not None and va.settings == {}
    assert vb.disabled is True and vb.accounts == () and vb.last_run_at is None
    assert not hasattr(va, "state")  # credential state is never listed


def test_a_settle_result_type_is_returned_by_delete(db: Db, monkeypatch: pytest.MonkeyPatch) -> None:
    iid = make_instance(db)
    result = SettleResult(touched_entry_ids=(1,))
    monkeypatch.setattr(instances, "settle", lambda e: result)
    assert delete_instance(db.engine, iid) is result
