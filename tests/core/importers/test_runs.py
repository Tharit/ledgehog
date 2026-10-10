"""The run list (spec §5.3/§5.4): newest first, filtered, with what each run can still do."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.core.importers.runs import RunView, get_run, list_runs
from tests.core.importers.conftest import Db, make_acct, make_instance
from tests.core.importers.conftest import db as db  # noqa: F401  (fixture)
from tests.core.importers.conftest import user_id as user_id  # noqa: F401  (fixture)


def _at(day: int, hour: int = 12) -> str:
    return datetime(2026, 8, day, hour).isoformat() + "+00:00"


def _run(
    db: Db,
    account: int,
    *,
    instance: int | None = None,
    status: str = "ok",
    started: str,
    finished: str | None = None,
    **extra: Any,
) -> int:
    cols: dict[str, Any] = {
        "importer": "csv",
        "importer_instance_id": instance,
        "emits": "transactions",
        "account_id": account,
        "status": status,
        "started_at": started,
        "finished_at": finished if finished is not None else (None if status == "running" else started),
    }
    if status in ("ok", "reverted"):
        cols["covered_through"] = date(2026, 8, 10)
        cols["covered_from"] = date(2026, 8, 1)
    if status == "reverted":
        cols["reverted_at"] = started
    cols.update(extra)
    names = ", ".join(cols)
    marks = ", ".join(f":{k}" for k in cols)
    with db.engine.begin() as conn:
        from sqlalchemy import text

        return int(
            conn.execute(
                text(f"INSERT INTO import_run ({names}) VALUES ({marks}) RETURNING id"), cols
            ).scalar_one()  # noqa: S608
        )


def _ids(views: list[RunView]) -> list[int]:
    return [v.id for v in views]


def test_newest_first_by_finish_then_id(db: Db) -> None:
    a = make_acct(db)
    r1 = _run(db, a, started=_at(1))
    r2 = _run(db, a, started=_at(3))
    r3 = _run(db, a, started=_at(3))  # same time: the higher id first
    r4 = _run(db, a, started=_at(2))
    with db.engine.connect() as conn:
        assert _ids(list_runs(conn)) == [r3, r2, r4, r1]
        assert _ids(list_runs(conn, limit=2)) == [r3, r2]


def test_a_running_run_sorts_by_its_start(db: Db) -> None:
    a = make_acct(db)
    done = _run(db, a, started=_at(1))
    running = _run(db, a, status="running", started=_at(5))
    with db.engine.connect() as conn:
        assert _ids(list_runs(conn)) == [running, done]


def test_filters(db: Db) -> None:
    a, b = make_acct(db, "A"), make_acct(db, "B")
    i1, i2 = make_instance(db, label="one"), make_instance(db, label="two")
    ra = _run(db, a, instance=i1, started=_at(1))
    rb = _run(db, b, instance=i2, started=_at(2))
    rf = _run(db, b, instance=i2, status="failed", started=_at(3), error_text="ParseFailed: no header")
    with db.engine.connect() as conn:
        assert _ids(list_runs(conn, account_id=b)) == [rf, rb]
        assert _ids(list_runs(conn, instance_id=i1)) == [ra]
        assert _ids(list_runs(conn, status="failed")) == [rf]
        assert _ids(list_runs(conn, account_id=b, status="ok")) == [rb]
        assert list_runs(conn, account_id=99_999) == []


def test_failed_runs_are_listed_with_their_error(db: Db) -> None:
    a = make_acct(db)
    rf = _run(db, a, status="failed", started=_at(1), error_text="ParseFailed: no header row")
    with db.engine.connect() as conn:
        (view,) = list_runs(conn)
    assert view.id == rf and view.status == "failed"
    assert view.error_text == "ParseFailed: no header row"
    assert view.covered_through is None and view.revertible is False


def test_only_the_latest_ok_run_of_an_account_is_revertible(db: Db, user_id: int) -> None:
    a, b = make_acct(db, "A"), make_acct(db, "B")
    a1 = _run(db, a, started=_at(1))
    a2 = _run(db, a, started=_at(2))
    a3 = _run(db, a, status="failed", started=_at(3))  # a failed run is never the latest
    b1 = _run(db, b, started=_at(1))
    b2 = _run(db, b, status="reverted", started=_at(2), reverted_by=user_id)
    with db.engine.connect() as conn:
        flags = {v.id: v.revertible for v in list_runs(conn)}
    assert flags == {a1: False, a2: True, a3: False, b1: True, b2: False}


def test_revertible_is_judged_against_the_whole_account_not_the_filter(db: Db) -> None:
    a = make_acct(db)
    i1 = make_instance(db, label="one")
    i2 = make_instance(db, label="two")
    old = _run(db, a, instance=i1, started=_at(1))
    new = _run(db, a, instance=i2, started=_at(2))
    with db.engine.connect() as conn:
        (view,) = list_runs(conn, instance_id=i1)
        assert view.id == old and view.revertible is False
        assert get_run(conn, new) is not None and get_run(conn, new).revertible is True  # type: ignore[union-attr]


def test_a_view_carries_the_run(db: Db, user_id: int) -> None:
    a = make_acct(db)
    i = make_instance(db)
    rid = _run(
        db,
        a,
        instance=i,
        status="reverted",
        started=_at(4),
        started_by=user_id,
        reverted_by=user_id,
        stats='{"inserted": 3, "importer": {"filtered": 1}}',
    )
    with db.engine.connect() as conn:
        view = get_run(conn, rid)
    assert view is not None
    assert (view.importer, view.instance_id, view.account_id, view.kind, view.status) == (
        "csv",
        i,
        a,
        "transactions",
        "reverted",
    )
    assert view.started_by == user_id and view.reverted_by == user_id and view.reverted_at is not None
    assert view.covered_from == date(2026, 8, 1) and view.covered_through == date(2026, 8, 10)
    assert view.stats == {"inserted": 3, "importer": {"filtered": 1}}
    assert view.started_at is not None and view.finished_at is not None


def test_get_run_of_an_unknown_id_is_none(db: Db) -> None:
    with db.engine.connect() as conn:
        assert get_run(conn, 424_242) is None


def test_a_documents_run_is_never_revertible(db: Db) -> None:
    from sqlalchemy import text

    with db.engine.begin() as conn:
        rid = int(
            conn.execute(
                text(
                    "INSERT INTO import_run (importer, emits, status, finished_at, covered_through)"
                    " VALUES ('docs', 'documents', 'ok', now(), '2026-08-01') RETURNING id"
                )
            ).scalar_one()
        )
    with db.engine.connect() as conn:
        view = get_run(conn, rid)
    assert view is not None and view.account_id is None and view.revertible is False
