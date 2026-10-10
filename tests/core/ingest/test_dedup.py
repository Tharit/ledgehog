"""The two-step check of spec §5.2: identity first, then amount."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import text

from tests.core.ingest.conftest import DAY, Env, row
from tests.invariants.helpers import make_balance_record, make_derived_entry, make_movement


def _sources(env: Env) -> list[tuple[str | None, int | None, int]]:
    """(source_id, duplicate_of, id) of every source row, by id."""
    return [
        (r.source_id, r.duplicate_of, r.id) for r in env.q("SELECT * FROM source_transaction ORDER BY id")
    ]


def _id(env: Env, source_id: str) -> int:
    return int(env.q("SELECT id FROM source_transaction WHERE source_id = :s", s=source_id)[0][0])


def test_identity_hit_skips(env: Env) -> None:
    env.deliver([row(-500, source_id="a")])
    res = env.deliver([row(-500, source_id="a")])
    assert (res.inserted, res.skipped_by_identity, res.duplicates) == (0, 1, ())
    assert env.count("source_transaction") == 1 and env.count("ledger_entry") == 1


def test_identity_hit_on_duplicate_uses_up_its_original(env: Env) -> None:
    env.deliver([row(-500, source_id="a1")], importer="A")
    first = env.deliver([row(-500, source_id="b1")], importer="B")
    assert first.duplicates == ((_id(env, "b1"), _id(env, "a1")),)
    # B re-delivers b1 (hits a duplicate, so a1 is accounted for) plus a genuine second booking
    res = env.deliver([row(-500, source_id="b1"), row(-500, source_id="b2")], importer="B")
    assert (res.skipped_by_identity, res.inserted, res.duplicates) == (1, 1, ())
    assert dict((s, d) for s, d, _ in _sources(env))["b2"] is None
    assert env.count("ledger_entry") == 2


def test_amount_step_across_importers(env: Env) -> None:
    env.deliver([row(-500, purpose="Coffee Shop", source_id="a1")], importer="A")
    res = env.deliver([row(-500, purpose="coffee shop 17", source_id="b1")], importer="B")
    assert (res.inserted, res.duplicates) == (0, ((_id(env, "b1"), _id(env, "a1")),))
    assert env.count("ledger_entry") == 1
    # the existing row is never changed; the duplicate keeps its raw payload and has no entry
    assert env.q("SELECT duplicate_of FROM source_transaction WHERE source_id = 'a1'")[0][0] is None
    assert (
        env.q("SELECT count(*) FROM ledger_entry WHERE source_transaction_id = :i", i=_id(env, "b1"))[0][0]
        == 0
    )


def test_amount_step_across_changed_source_id(env: Env) -> None:
    env.deliver([row(-500, source_id="old")])
    res = env.deliver([row(-500, source_id="new")])
    assert res.duplicates == ((_id(env, "new"), _id(env, "old")),) and res.inserted == 0


def test_amount_step_never_matches_user_authored(env: Env) -> None:
    with env.engine.begin() as conn:
        make_movement(conn, env.account, amount=-500, booked_on=DAY, importer=None, source_id="form-1")
    res = env.deliver([row(-500, source_id="a")])
    assert (res.inserted, res.duplicates) == (1, ())


def test_amount_step_never_matches_derived_entries(env: Env) -> None:
    with env.engine.begin() as conn:
        rec = make_balance_record(conn, env.account, balance_on=DAY, balance=-500)
        make_derived_entry(conn, env.account, rec, type="opening", booked_on=DAY, amount=-500)
    res = env.deliver([row(-500, source_id="a")])
    assert (res.inserted, res.duplicates) == (1, ())


def test_amount_step_never_matches_same_delivery_rows(env: Env) -> None:
    res = env.deliver([row(-500, source_id="a"), row(-500, source_id="b")])
    assert (res.inserted, res.duplicates) == (2, ())


def test_amount_step_never_matches_row_used_up_by_identity(env: Env) -> None:
    env.deliver([row(-500, source_id="a")])
    res = env.deliver([row(-500, source_id="a"), row(-500, source_id="b")])
    assert (res.skipped_by_identity, res.inserted, res.duplicates) == (1, 1, ())


def test_amount_step_never_matches_an_existing_duplicate(env: Env) -> None:
    env.deliver([row(-500, source_id="a")], importer="A")
    env.deliver([row(-500, source_id="b")], importer="B")  # b duplicates a
    # a third rendering: a is unaccounted for by identity, so it pairs with a, never with b
    res = env.deliver([row(-500, source_id="c")], importer="C")
    assert res.duplicates == ((_id(env, "c"), _id(env, "a")),)


def test_different_booking_date_both_stay(env: Env) -> None:
    env.deliver([row(-500, source_id="a")], importer="A")
    res = env.deliver([row(-500, day=DAY + timedelta(days=1), source_id="b")], importer="B")
    assert (res.inserted, res.duplicates) == (1, ()) and env.count("ledger_entry") == 2


def test_purpose_preferred_then_lowest_id(env: Env) -> None:
    env.deliver(
        [
            row(-500, purpose="foo", source_id="e1"),
            row(-500, purpose="bar", source_id="e2"),
            row(-500, purpose="Bar!", source_id="e3"),
        ],
        importer="A",
    )
    res = env.deliver(
        [row(-500, purpose="BAR", source_id="n1"), row(-500, purpose="zzz", source_id="n2")], importer="B"
    )
    assert res.duplicates == (
        (_id(env, "n1"), _id(env, "e2")),  # equal canonical purpose, lowest id of those
        (_id(env, "n2"), _id(env, "e1")),  # no purpose match: lowest remaining id
    )


def test_two_incoming_one_existing_one_pairs_other_inserted(env: Env) -> None:
    env.deliver([row(-500, source_id="e1")], importer="A")
    res = env.deliver([row(-500, source_id="n1"), row(-500, source_id="n2")], importer="B")
    assert res.duplicates == ((_id(env, "n1"), _id(env, "e1")),) and res.inserted == 1
    assert env.count("ledger_entry") == 2


def test_incoming_rows_pick_in_delivery_order(env: Env) -> None:
    env.deliver(
        [row(-500, purpose="b", source_id="e1"), row(-500, purpose="c", source_id="e2")], importer="A"
    )
    res = env.deliver(
        [row(-500, purpose="x", source_id="n1"), row(-500, purpose="b", source_id="n2")], importer="B"
    )
    # n1 has no purpose match and takes the lowest id (e1); n2 would have preferred e1, gets e2
    assert res.duplicates == ((_id(env, "n1"), _id(env, "e1")), (_id(env, "n2"), _id(env, "e2")))


def test_shared_account_two_credentials(env: Env) -> None:
    anna = [row(-500, purpose="rent", source_id="r1"), row(-70, purpose="gas", source_id="g1")]
    env.deliver(anna, importer="fints-anna")
    same = env.deliver(anna, importer="fints-ben")  # same ids: identity skips
    assert (same.skipped_by_identity, same.inserted, same.duplicates) == (2, 0, ())
    other = env.deliver(  # rendered differently: amount step
        [row(-500, purpose="RENT 03/26", source_id="x9"), row(-70, purpose="Gas", source_id="x8")],
        importer="fints-ben",
    )
    assert len(other.duplicates) == 2 and other.inserted == 0
    assert env.count("ledger_entry") == 2


def test_ordinals_three_identical_rows_three_entries_redelivery_nothing_new(env: Env) -> None:
    same = [row(-500, purpose="bakery", counterparty_ref="DE02") for _ in range(3)]
    first = env.deliver(same)
    assert first.inserted == 3 and env.count("ledger_entry") == 3
    again = env.deliver(same)
    assert (again.inserted, again.skipped_by_identity, again.duplicates) == (0, 3, ())
    assert env.count("ledger_entry") == 3


def test_second_row_dropped_by_currency_does_not_shift_ordinals(env: Env) -> None:
    """Ordinals are assigned over the whole delivery before any filtering."""
    env.deliver([row(-500, purpose="p"), row(-500, purpose="p")])
    res = env.deliver([row(-500, purpose="p"), row(-500, purpose="p"), row(-500, purpose="p")])
    assert (res.skipped_by_identity, res.inserted) == (2, 1)


def test_two_run_overlapping_windows_add_nothing(env: Env) -> None:
    d = date(2026, 3, 1)
    window1 = [
        row(-500 - i, day=d + timedelta(days=i % 5), purpose=f"p{i % 3}", counterparty_ref="DE02")
        for i in range(8)
    ] + [row(-500, day=d, purpose="p0", counterparty_ref="DE02")]  # identical to row 0 in every hashed field
    window2 = window1[3:] + [row(-999, day=d + timedelta(days=6), purpose="new")]
    first = env.deliver(window1)
    entries_after_first = env.count("ledger_entry")
    second = env.deliver(window2)
    assert first.inserted == len(window1)
    assert second.inserted == 1 and second.duplicates == ()
    assert second.skipped_by_identity == len(window2) - 1
    assert env.count("ledger_entry") == entries_after_first + 1
    assert env.count("source_transaction") == len(window1) + 1
    with env.engine.connect() as conn:
        views = (
            conn.execute(
                text("SELECT table_name FROM information_schema.views WHERE table_name LIKE 'v\\_check\\_%'")
            )
            .scalars()
            .all()
        )
        assert views
        for view in views:
            assert conn.execute(text(f"SELECT count(*) FROM {view}")).scalar_one() == 0, view  # noqa: S608
