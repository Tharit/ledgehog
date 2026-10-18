"""The entry form's writes: create, edit and delete a user-authored source (spec §3.9, §5.6, §5.7, §5.9).

Real commits (`isolated_engine`): the deferred triggers and the locks are part of what is tested.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest
from sqlalchemy import Engine, text

from app.core.balance.records import set_manual_record
from app.core.domain.errors import VersionConflict
from app.core.ledger import sources as src
from app.core.ledger.sources import (
    AccountSynced,
    NotUserAuthored,
    SourceMissing,
    create_source,
    delete_source,
    plan_amounts,
    update_source,
)
from app.core.settle.settle import SettleResult
from app.core.stale import StaleReference
from tests.fixtures import ledger_seed as seed
from tests.invariants.helpers import link_account, make_entry, make_instance, make_source

DAY = date(2026, 3, 10)


@pytest.fixture
def acct(isolated_engine: Engine) -> int:
    with isolated_engine.begin() as conn:
        return seed.account(conn, "Cash", kind="cash")


@pytest.fixture
def world(isolated_engine: Engine, acct: int) -> dict[str, int]:
    """Cash (A, EUR), a second account (B, EUR), a USD account (U), the category Food and a REWE rule."""
    with isolated_engine.begin() as conn:
        b = seed.account(conn, "Giro")
        u = seed.account(conn, "Dollar", currency="USD")
        food = seed.category(conn, "Food")
        conn.execute(
            text(
                "INSERT INTO rule (name, sets, category_id, conditions) VALUES ('rewe', 'category', :c,"
                " CAST(:cond AS jsonb))"
            ),
            {"c": food, "cond": json.dumps([{"field": "purpose", "op": "contains", "value": "REWE"}])},
        )
    return {"a": acct, "b": b, "u": u, "food": food}


def q(engine: Engine, sql: str, **p: Any) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(text(sql), p).all())


def entries_of(engine: Engine, source_id: int) -> list[Any]:
    return q(
        engine,
        "SELECT id, amount, booked_on, type, category_id, payee_id, counter_account_id, counterpart_entry_id,"
        " derivation, version, review_flags FROM ledger_entry WHERE source_transaction_id = :s ORDER BY id",
        s=source_id,
    )


def enter(
    engine: Engine,
    account: int,
    *,
    amount: int = -2500,
    on: date = DAY,
    purpose: str | None = "x",
    cid: str | None = None,
):
    import uuid

    return create_source(
        engine,
        client_id=cid or uuid.uuid4().hex,
        account_id=account,
        amount=amount,
        booked_on=on,
        purpose=purpose,
    )


def fingerprint(engine: Engine) -> list[Any]:
    """Everything an entry-form write could touch."""
    return [
        q(engine, "SELECT * FROM source_transaction ORDER BY id"),
        q(engine, "SELECT * FROM ledger_entry ORDER BY id"),
        q(engine, "SELECT * FROM ledger_entry_tag ORDER BY 1, 2"),
    ]


def versions(engine: Engine, *ids: int) -> dict[int, int]:
    rows = q(engine, "SELECT id, version FROM ledger_entry WHERE id = ANY(:i)", i=list(ids))
    return {int(r.id): int(r.version) for r in rows}


def split(engine: Engine, source_id: int, amounts: list[int]) -> list[int]:
    """Re-cut the single entry of a user-authored row into entries of these amounts (original first)."""
    (first,) = [r.id for r in entries_of(engine, source_id)]
    with engine.begin() as conn:
        conn.execute(text("UPDATE ledger_entry SET amount = :a WHERE id = :i"), {"a": amounts[0], "i": first})
        ids = [first]
        for a in amounts[1:]:
            ids.append(make_entry(conn, source_id, amount=a, type="flow"))
    return ids


def make_pair(
    engine: Engine, entry_id: int, partner_account: int, *, partner_amount: int | None = None
) -> int:
    """Pair `entry_id` (made a transfer) with a new imported leg on `partner_account`."""
    with engine.begin() as conn:
        mine = conn.execute(
            text(
                "SELECT account_id, amount, booked_on, source_transaction_id FROM ledger_entry WHERE id = :i"
            ),
            {"i": entry_id},
        ).one()
        cur = conn.execute(
            text("SELECT currency FROM account WHERE id = :a"), {"a": partner_account}
        ).scalar_one()
        amount = -mine.amount if partner_amount is None else partner_amount
        s = make_source(conn, partner_account, amount=amount, currency=cur, booked_on=mine.booked_on)
        leg = make_entry(
            conn,
            s,
            type="transfer",
            counter_account_id=mine.account_id,
            derivation=json.dumps(
                {"counter_account": {"pass": "matcher_decision", "basis": {"from": "counterpart"}}}
            ),
        )
        conn.execute(
            text(
                "UPDATE ledger_entry SET type = 'transfer', counter_account_id = :c, category_id = NULL,"
                ' derivation = derivation || \'{"counter_account": {"pass": "matcher_decision",'
                ' "basis": {"from": "counterpart"}}}\'::jsonb WHERE id = :i'
            ),
            {"c": partner_account, "i": entry_id},
        )
        conn.execute(
            text(
                "UPDATE ledger_entry SET counterpart_entry_id = CASE id WHEN :a THEN :b ELSE :a END"
                " WHERE id IN (:a, :b)"
            ),
            {"a": entry_id, "b": leg},
        )
    return leg


def confirm(engine: Engine, entry_id: int, category: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE ledger_entry SET type = 'flow', category_id = :c,"
                ' derivation = \'{"category": {"pass": "user"}, "type": {"pass": "user"}}\'::jsonb'
                " WHERE id = :i"
            ),
            {"c": category, "i": entry_id},
        )


# ---- create -------------------------------------------------------------------------------------


def test_create_writes_the_row_and_its_one_entry(isolated_engine: Engine, acct: int):
    done = enter(isolated_engine, acct, amount=-4731, purpose="  groceries at REWE  ", cid="abc-123")
    assert done.created and isinstance(done.settle, SettleResult) and done.settle.error is None
    (row,) = q(isolated_engine, "SELECT * FROM source_transaction")
    assert (row.importer, row.import_run_id, row.source_format, row.content_hash) == (None, None, None, None)
    assert (row.source_id, row.account_id, row.currency) == ("abc-123", acct, "EUR")
    assert (row.amount, row.booked_on, row.purpose, row.value_on) == (-4731, DAY, "groceries at REWE", None)
    assert row.counterparty_name is None and row.counterparty_ref is None and row.end_to_end_id is None
    assert row.raw == {
        "id": "abc-123",
        "account_id": acct,
        "amount": -4731,
        "booked_on": "2026-03-10",
        "purpose": "groceries at REWE",
    }
    (entry,) = entries_of(isolated_engine, done.source_id)
    assert (entry.amount, entry.booked_on) == (-4731, DAY)
    (view,) = done.units.views
    assert view.anchor_entry_id == entry.id and [e.id for e in view.entries] == [entry.id]


def test_signed_amounts_are_kept(isolated_engine: Engine, acct: int):
    out = enter(isolated_engine, acct, amount=-100)
    inc = enter(isolated_engine, acct, amount=900)
    assert [r.amount for r in entries_of(isolated_engine, out.source_id)] == [-100]
    assert [r.amount for r in entries_of(isolated_engine, inc.source_id)] == [900]


def test_purpose_may_be_empty(isolated_engine: Engine, acct: int):
    done = enter(isolated_engine, acct, purpose="   ")
    assert (
        q(isolated_engine, "SELECT purpose FROM source_transaction WHERE id = :i", i=done.source_id)[
            0
        ].purpose
        is None
    )


def test_the_entry_is_resolved_from_the_purpose_alone_and_confirmed_by_a_rule(
    isolated_engine: Engine, acct: int, world: dict[str, int]
):
    done = enter(isolated_engine, acct, purpose="REWE Markt")
    (e,) = entries_of(isolated_engine, done.source_id)
    assert (e.type, e.category_id) == ("flow", world["food"])
    assert e.derivation["category"]["pass"] == "rule"
    (view,) = done.units.views  # the answer is read after settling: the rule's unit is confirmed
    assert view.state.confirmed is True and view.entries[0].review_flags == ()


def test_an_unclassified_entry_waits_in_the_queue(isolated_engine: Engine, acct: int):
    from app.core.units.read import review_queue

    done = enter(isolated_engine, acct, purpose="mystery")
    (view,) = done.units.views
    assert view.state.confirmed is False
    assert set(view.entries[0].review_flags) == {"unclassified"}
    with isolated_engine.connect() as conn:
        queue = review_queue(conn)
    pending = queue.sections[0]
    assert [u.anchor_entry_id for u in pending.units] == [view.anchor_entry_id]


def test_history_proposes_from_the_purpose(isolated_engine: Engine, acct: int, world: dict[str, int]):
    first = enter(isolated_engine, acct, purpose="Bakery Mueller")
    (e,) = entries_of(isolated_engine, first.source_id)
    confirm(isolated_engine, e.id, world["food"])
    second = enter(isolated_engine, acct, purpose="Bakery Mueller")
    (e2,) = entries_of(isolated_engine, second.source_id)
    assert (e2.type, e2.category_id) == ("flow", world["food"])
    assert e2.derivation["category"]["pass"] == "history"


def test_a_repeated_id_returns_the_row_and_writes_nothing(isolated_engine: Engine, acct: int):
    first = enter(isolated_engine, acct, cid="same-id", amount=-100)
    before = fingerprint(isolated_engine)
    again = enter(isolated_engine, acct, cid="same-id", amount=-999, purpose="other")
    assert not again.created and again.source_id == first.source_id
    assert fingerprint(isolated_engine) == before
    assert [e.id for e in again.units.entries] == [e.id for e in first.units.entries]


def test_a_repeated_id_is_per_account(isolated_engine: Engine, acct: int, world: dict[str, int]):
    a = enter(isolated_engine, acct, cid="k")
    b = enter(isolated_engine, world["b"], cid="k")
    assert a.created and b.created and a.source_id != b.source_id


def test_a_synced_account_is_refused(isolated_engine: Engine, world: dict[str, int]):
    with isolated_engine.begin() as conn:
        link_account(conn, world["b"], make_instance(conn))
    with pytest.raises(AccountSynced):
        enter(isolated_engine, world["b"])
    assert q(isolated_engine, "SELECT 1 FROM source_transaction") == []


def test_a_closed_synced_account_is_allowed_like_imports(isolated_engine: Engine, world: dict[str, int]):
    with isolated_engine.begin() as conn:
        link_account(conn, world["b"], make_instance(conn))
        conn.execute(
            text("UPDATE account SET closed_on = DATE '2026-01-31' WHERE id = :a"), {"a": world["b"]}
        )
    assert enter(isolated_engine, world["b"], on=date(2026, 3, 1)).created


def test_a_date_after_the_close_is_allowed(isolated_engine: Engine, acct: int):
    with isolated_engine.begin() as conn:
        conn.execute(text("UPDATE account SET closed_on = DATE '2026-01-31' WHERE id = :a"), {"a": acct})
    done = enter(isolated_engine, acct, on=date(2026, 5, 1))
    assert entries_of(isolated_engine, done.source_id)[0].booked_on == date(2026, 5, 1)


def test_an_unknown_account_is_a_stale_reference(isolated_engine: Engine):
    with pytest.raises(StaleReference) as exc:
        enter(isolated_engine, 987654)
    assert exc.value.field == "account_id"


def test_the_account_currency_is_used(isolated_engine: Engine, world: dict[str, int]):
    done = enter(isolated_engine, world["u"])
    assert q(isolated_engine, "SELECT currency FROM ledger_entry")[0].currency == "USD"
    assert done.units.entries[0].currency == "USD"


def test_create_recomputes_the_derived_entries(isolated_engine: Engine, acct: int):
    set_manual_record(isolated_engine, acct, date(2026, 3, 1), 10_000)
    enter(isolated_engine, acct, amount=-1_000, on=date(2026, 2, 20))
    opening = q(isolated_engine, "SELECT amount, booked_on FROM ledger_entry WHERE type = 'opening'")
    assert [(r.amount, r.booked_on) for r in opening] == [(11_000, date(2026, 2, 19))]


def test_create_settles_once(isolated_engine: Engine, acct: int, monkeypatch: pytest.MonkeyPatch):
    calls: list[int] = []
    real = src.settle
    monkeypatch.setattr(src, "settle", lambda engine: calls.append(1) or real(engine))
    enter(isolated_engine, acct)
    assert calls == [1]


# ---- the plan (pure) ------------------------------------------------------------------------------


def test_plan_single_entry_takes_the_amount():
    plan = plan_amounts(-100, -250, [(1, -100)], {}, "EUR")
    assert (plan.amounts, plan.collapse, plan.unpair) == ({1: -250}, (), ())


def test_plan_residual_absorbs():
    plan = plan_amounts(-100, -130, [(1, -70), (2, -30)], {}, "EUR")
    assert (plan.amounts, plan.collapse) == ({1: -100}, ())


def test_plan_collapses_when_the_residual_would_reach_zero_or_flip():
    zero = plan_amounts(-100, -30, [(1, -70), (2, -30)], {}, "EUR")
    assert (zero.amounts, zero.collapse) == ({1: -30}, (2,))
    flip = plan_amounts(-100, -20, [(1, -70), (2, -30)], {}, "EUR")
    assert (flip.amounts, flip.collapse) == ({1: -20}, (2,))


def test_plan_pairs():
    same = plan_amounts(-100, -120, [(1, -100)], {1: "EUR"}, "EUR")
    cross = plan_amounts(-100, -120, [(1, -100)], {1: "USD"}, "EUR")
    sign = plan_amounts(-100, 120, [(1, -100)], {1: "USD"}, "EUR")
    assert (same.unpair, cross.unpair, sign.unpair) == ((1,), (), (1,))
    date_only = plan_amounts(-100, -100, [(1, -100)], {1: "EUR"}, "EUR")
    assert date_only.unpair == () and date_only.amounts == {}


def test_plan_a_following_partner_keeps_the_pair_through_an_amount_change():
    follow = plan_amounts(-100, -120, [(1, -100)], {1: "EUR"}, "EUR", following={1})
    assert (follow.amounts, follow.unpair) == ({1: -120}, ())
    sign = plan_amounts(-100, 120, [(1, -100)], {1: "EUR"}, "EUR", following={1})
    assert sign.unpair == (1,)  # a changed sign breaks any pair, followers included
    cross = plan_amounts(-100, -120, [(1, -100)], {1: "USD"}, "EUR", following={1})
    assert cross.unpair == ()


# ---- edit ---------------------------------------------------------------------------------------


def edit(engine: Engine, source_id: int, **kw: Any):
    """A real edit carrying the current versions of the row's entries and of any partners."""
    kw.setdefault("dry_run", False)
    if "expected_versions" not in kw:
        probe = update_source(engine, source_id, **{**kw, "dry_run": True})
        kw["expected_versions"] = dict(probe.effects.versions)
    return update_source(engine, source_id, **kw)


def test_date_only_edit_moves_every_entry(isolated_engine: Engine, acct: int):
    done = enter(isolated_engine, acct, purpose="mystery")
    ids = split(isolated_engine, done.source_id, [-1000, -1500])
    with isolated_engine.begin() as conn:
        conn.execute(
            text("UPDATE source_transaction SET amount = -2500 WHERE id = :s"), {"s": done.source_id}
        )
    out = edit(isolated_engine, done.source_id, booked_on=date(2026, 3, 20))
    assert {r.booked_on for r in entries_of(isolated_engine, done.source_id)} == {date(2026, 3, 20)}
    assert q(isolated_engine, "SELECT booked_on FROM source_transaction")[0].booked_on == date(2026, 3, 20)
    assert out.effects.collapsed_entry_ids == () and out.effects.unpaired_entry_ids == ()
    assert [e.id for e in out.units.entries] == ids


def test_amount_edit_on_a_single_entry(isolated_engine: Engine, acct: int):
    done = enter(isolated_engine, acct, amount=-100)
    edit(isolated_engine, done.source_id, amount=-250)
    (e,) = entries_of(isolated_engine, done.source_id)
    assert e.amount == -250
    assert q(isolated_engine, "SELECT amount FROM source_transaction")[0].amount == -250
    assert q(isolated_engine, "SELECT raw FROM source_transaction")[0].raw["amount"] == -250


def test_split_residual_absorbs_the_change(isolated_engine: Engine, acct: int):
    done = enter(isolated_engine, acct, amount=-100)
    first, second = split(isolated_engine, done.source_id, [-70, -30])
    out = edit(isolated_engine, done.source_id, amount=-130)
    assert [(r.id, r.amount) for r in entries_of(isolated_engine, done.source_id)] == [
        (first, -100),
        (second, -30),
    ]
    assert out.effects.collapsed_entry_ids == ()


def test_split_collapses_when_the_residual_would_reach_zero(isolated_engine: Engine, acct: int):
    done = enter(isolated_engine, acct, amount=-100)
    first, second = split(isolated_engine, done.source_id, [-70, -30])
    out = edit(isolated_engine, done.source_id, amount=-30)
    assert [(r.id, r.amount) for r in entries_of(isolated_engine, done.source_id)] == [(first, -30)]
    assert out.effects.collapsed_entry_ids == (second,) and out.effects.deleted_entry_ids == (second,)
    assert out.settle is not None and out.units.entries[0].id == first
    assert list(out.effects.versions) and (second in [i for i, _ in out.effects.versions])


def test_split_collapses_when_the_residual_would_flip_sign(isolated_engine: Engine, acct: int):
    done = enter(isolated_engine, acct, amount=-100)
    first, _ = split(isolated_engine, done.source_id, [-70, -30])
    edit(isolated_engine, done.source_id, amount=-20)
    assert [(r.id, r.amount) for r in entries_of(isolated_engine, done.source_id)] == [(first, -20)]


def test_sign_flip_on_a_single_entry(isolated_engine: Engine, acct: int):
    done = enter(isolated_engine, acct, amount=-100)
    edit(isolated_engine, done.source_id, amount=400)
    assert [r.amount for r in entries_of(isolated_engine, done.source_id)] == [400]


def test_collapse_removes_tags_with_the_entry_and_keeps_the_originals(isolated_engine: Engine, acct: int):
    done = enter(isolated_engine, acct, amount=-100)
    first, second = split(isolated_engine, done.source_id, [-70, -30])
    with isolated_engine.begin() as conn:
        tag = seed.tag(conn, "t")
        conn.execute(
            text("INSERT INTO ledger_entry_tag (ledger_entry_id, tag_id) VALUES (:a, :t), (:b, :t)"),
            {"a": first, "b": second, "t": tag},
        )
    edit(isolated_engine, done.source_id, amount=-10)
    assert [
        r.ledger_entry_id for r in q(isolated_engine, "SELECT ledger_entry_id FROM ledger_entry_tag")
    ] == [first]


def test_same_currency_pair_is_broken_by_an_amount_change(
    isolated_engine: Engine, acct: int, world: dict[str, int]
):
    done = enter(isolated_engine, acct, amount=-100, purpose="to bank")
    (entry,) = [r.id for r in entries_of(isolated_engine, done.source_id)]
    leg = make_pair(isolated_engine, entry, world["b"])
    out = edit(isolated_engine, done.source_id, amount=-150)
    mine = entries_of(isolated_engine, done.source_id)[0]
    assert mine.counterpart_entry_id is None and mine.amount == -150
    partner = q(isolated_engine, "SELECT * FROM ledger_entry WHERE id = :i", i=leg)[0]
    assert (
        partner.counterpart_entry_id is None
        and partner.type == "transfer"
        and partner.counter_account_id is None
    )
    assert partner.amount == 100  # the partner is left behind, as it was
    assert set(out.effects.unpaired_entry_ids) == {entry, leg}
    # the partner is a unit of its own now, back in review
    assert leg in {e.id for e in out.units.entries}
    assert any(v.state.confirmed is False and leg in [e.id for e in v.entries] for v in out.units.views)
    assert {i for i, _ in out.effects.versions} >= {entry, leg}


def test_an_amount_change_leaves_a_cross_currency_pair_standing(
    isolated_engine: Engine, acct: int, world: dict[str, int]
):
    done = enter(isolated_engine, acct, amount=-100)
    (entry,) = [r.id for r in entries_of(isolated_engine, done.source_id)]
    leg = make_pair(isolated_engine, entry, world["u"], partner_amount=110)
    out = edit(isolated_engine, done.source_id, amount=-150)
    assert entries_of(isolated_engine, done.source_id)[0].counterpart_entry_id == leg
    assert out.effects.unpaired_entry_ids == ()


def test_a_sign_change_breaks_any_pair(isolated_engine: Engine, acct: int, world: dict[str, int]):
    done = enter(isolated_engine, acct, amount=-100)
    (entry,) = [r.id for r in entries_of(isolated_engine, done.source_id)]
    leg = make_pair(isolated_engine, entry, world["u"], partner_amount=110)
    out = edit(isolated_engine, done.source_id, amount=100)
    assert entries_of(isolated_engine, done.source_id)[0].counterpart_entry_id is None
    assert set(out.effects.unpaired_entry_ids) == {entry, leg}


def test_a_date_change_leaves_a_pair_standing(isolated_engine: Engine, acct: int, world: dict[str, int]):
    done = enter(isolated_engine, acct, amount=-100)
    (entry,) = [r.id for r in entries_of(isolated_engine, done.source_id)]
    leg = make_pair(isolated_engine, entry, world["b"])
    out = edit(isolated_engine, done.source_id, booked_on=date(2026, 3, 12))
    mine = entries_of(isolated_engine, done.source_id)[0]
    assert (mine.counterpart_entry_id, mine.booked_on, mine.type) == (leg, date(2026, 3, 12), "transfer")
    assert q(isolated_engine, "SELECT booked_on FROM ledger_entry WHERE id = :i", i=leg)[0].booked_on == DAY
    assert out.effects.unpaired_entry_ids == ()


def test_afresh_resolution_rewrites_a_users_values_and_keys(
    isolated_engine: Engine, acct: int, world: dict[str, int]
):
    done = enter(isolated_engine, acct, purpose="mystery")
    (e,) = entries_of(isolated_engine, done.source_id)
    with isolated_engine.begin() as conn:
        other = seed.category(conn, "Other")
    confirm(isolated_engine, e.id, other)
    settle_state = q(isolated_engine, "SELECT review_flags FROM ledger_entry WHERE id = :i", i=e.id)
    assert settle_state is not None
    out = edit(isolated_engine, done.source_id, purpose="REWE again")
    (after,) = entries_of(isolated_engine, done.source_id)
    assert (after.type, after.category_id) == ("flow", world["food"])
    assert after.derivation["category"]["pass"] == "rule"
    assert out.effects.rederived_entry_ids == (e.id,)
    assert q(isolated_engine, "SELECT purpose FROM source_transaction")[0].purpose == "REWE again"


def test_afresh_resolution_drops_values_the_new_input_no_longer_supports(
    isolated_engine: Engine, acct: int, world: dict[str, int]
):
    done = enter(isolated_engine, acct, purpose="REWE")
    (e,) = entries_of(isolated_engine, done.source_id)
    assert e.category_id == world["food"]
    edit(isolated_engine, done.source_id, purpose="nothing known")
    (after,) = entries_of(isolated_engine, done.source_id)
    assert (after.type, after.category_id) == (None, None)
    assert "category" not in after.derivation


def test_a_confirmed_unit_returns_to_review_when_nothing_supports_its_values(
    isolated_engine: Engine, acct: int, world: dict[str, int]
):
    done = enter(isolated_engine, acct, purpose="Bakery Mueller")
    (e,) = entries_of(isolated_engine, done.source_id)
    confirm(isolated_engine, e.id, world["food"])
    # a confirmed unit: an edit resolves it afresh; with no rule or history behind it, it is back in review
    dry = update_source(isolated_engine, done.source_id, amount=-9, dry_run=True)
    assert dry.effects.returned_to_review_ids == (e.id,)
    assert dry.effects.rederived_entry_ids == (e.id,)


def test_a_dry_run_writes_nothing(isolated_engine: Engine, acct: int, world: dict[str, int]):
    done = enter(isolated_engine, acct, amount=-100)
    first, second = split(isolated_engine, done.source_id, [-70, -30])
    leg = make_pair(isolated_engine, first, world["b"], partner_amount=70)
    before = fingerprint(isolated_engine)
    out = update_source(
        isolated_engine, done.source_id, amount=-20, booked_on=date(2026, 4, 1), purpose="REWE", dry_run=True
    )
    assert fingerprint(isolated_engine) == before
    assert out.dry_run and out.settle is None and out.units.views == ()
    assert out.effects.collapsed_entry_ids == (second,)
    assert set(out.effects.unpaired_entry_ids) == {first, leg}
    assert first in out.effects.rederived_entry_ids
    assert {i for i, _ in out.effects.versions} == {first, second, leg}


def test_a_real_edit_needs_the_versions_of_everything_it_writes(
    isolated_engine: Engine, acct: int, world: dict[str, int]
):
    done = enter(isolated_engine, acct, amount=-100)
    (entry,) = [r.id for r in entries_of(isolated_engine, done.source_id)]
    leg = make_pair(isolated_engine, entry, world["b"])
    v = versions(isolated_engine, entry, leg)
    before = fingerprint(isolated_engine)
    with pytest.raises(VersionConflict) as exc:
        update_source(isolated_engine, done.source_id, amount=-150, expected_versions={entry: v[entry]})
    assert exc.value.entry_ids == (leg,)  # the partner it would unpair was not carried
    with pytest.raises(VersionConflict) as exc2:
        update_source(
            isolated_engine, done.source_id, amount=-150, expected_versions={entry: v[entry] + 1, leg: v[leg]}
        )
    assert exc2.value.entry_ids == (entry,)
    with pytest.raises(VersionConflict):
        update_source(isolated_engine, done.source_id, amount=-150, expected_versions=None)
    assert fingerprint(isolated_engine) == before


def test_a_stale_version_is_a_conflict_and_nothing_is_written(isolated_engine: Engine, acct: int):
    done = enter(isolated_engine, acct, amount=-100)
    (e,) = entries_of(isolated_engine, done.source_id)
    edit(isolated_engine, done.source_id, amount=-200)  # moves the version
    before = fingerprint(isolated_engine)
    with pytest.raises(VersionConflict) as exc:
        update_source(isolated_engine, done.source_id, amount=-300, expected_versions={e.id: e.version})
    assert exc.value.entry_ids == (e.id,)
    assert fingerprint(isolated_engine) == before


def test_an_edit_that_changes_nothing_writes_nothing(isolated_engine: Engine, acct: int):
    done = enter(isolated_engine, acct, amount=-100, purpose="same")
    (e,) = entries_of(isolated_engine, done.source_id)
    before = fingerprint(isolated_engine)
    out = update_source(
        isolated_engine, done.source_id, amount=-100, purpose="same", expected_versions={e.id: e.version}
    )
    assert fingerprint(isolated_engine) == before
    assert out.effects.rederived_entry_ids == ()


def test_an_empty_edit_is_refused(isolated_engine: Engine, acct: int):
    done = enter(isolated_engine, acct)
    with pytest.raises(src.EmptyEdit):
        update_source(isolated_engine, done.source_id)


def test_edit_refuses_an_imported_row_and_a_missing_one(isolated_engine: Engine, acct: int):
    with isolated_engine.begin() as conn:
        s = make_source(conn, acct)
        make_entry(conn, s)
    with pytest.raises(NotUserAuthored):
        update_source(isolated_engine, s, amount=-5, dry_run=True)
    with pytest.raises(SourceMissing):
        update_source(isolated_engine, 99999, amount=-5, dry_run=True)


def test_edit_recomputes_the_derived_entries(isolated_engine: Engine, acct: int):
    set_manual_record(isolated_engine, acct, date(2026, 3, 1), 10_000)
    done = enter(isolated_engine, acct, amount=-1_000, on=date(2026, 2, 20))
    edit(isolated_engine, done.source_id, amount=-2_000)
    assert q(isolated_engine, "SELECT amount FROM ledger_entry WHERE type = 'opening'")[0].amount == 12_000


def test_edit_settles_once_and_a_dry_run_not_at_all(
    isolated_engine: Engine, acct: int, monkeypatch: pytest.MonkeyPatch
):
    done = enter(isolated_engine, acct)
    (e,) = entries_of(isolated_engine, done.source_id)
    calls: list[int] = []
    real = src.settle
    monkeypatch.setattr(src, "settle", lambda engine: calls.append(1) or real(engine))
    update_source(isolated_engine, done.source_id, amount=-1, dry_run=True)
    assert calls == []
    update_source(isolated_engine, done.source_id, amount=-1, expected_versions={e.id: e.version})
    assert calls == [1]


def test_two_edits_racing_one_wins_and_one_is_a_conflict(isolated_engine: Engine, acct: int):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    done = enter(isolated_engine, acct, amount=-100)
    (e,) = entries_of(isolated_engine, done.source_id)
    barrier = Barrier(2)

    def attempt(amount: int) -> str:
        barrier.wait()
        try:
            update_source(isolated_engine, done.source_id, amount=amount, expected_versions={e.id: e.version})
            return "ok"
        except VersionConflict:
            return "conflict"

    with ThreadPoolExecutor(2) as pool:
        results = sorted(pool.map(attempt, [-200, -300]))
    assert results == ["conflict", "ok"]
    assert entries_of(isolated_engine, done.source_id)[0].amount in (-200, -300)


# ---- delete -------------------------------------------------------------------------------------


def test_delete_removes_the_row_and_its_entries(isolated_engine: Engine, acct: int):
    set_manual_record(isolated_engine, acct, date(2026, 3, 1), 10_000)
    done = enter(isolated_engine, acct, amount=-1_000, on=date(2026, 2, 20))
    (e,) = entries_of(isolated_engine, done.source_id)
    out = delete_source(isolated_engine, done.source_id, expected_versions={e.id: e.version})
    assert q(isolated_engine, "SELECT 1 FROM source_transaction") == []
    assert q(isolated_engine, "SELECT 1 FROM ledger_entry WHERE source_transaction_id IS NOT NULL") == []
    assert [r.amount for r in q(isolated_engine, "SELECT amount FROM ledger_entry")] == [
        10_000
    ]  # the opening
    assert [x.id for x in out.removed] == [e.id] and out.settle is not None and not out.dry_run


def test_delete_with_tags_and_a_dry_run_that_counts(
    isolated_engine: Engine, acct: int, world: dict[str, int]
):
    done = enter(isolated_engine, acct, amount=-100, purpose="REWE")
    first, second = split(isolated_engine, done.source_id, [-60, -40])
    with isolated_engine.begin() as conn:
        t1, t2 = seed.tag(conn, "a"), seed.tag(conn, "b")
        conn.execute(
            text("INSERT INTO ledger_entry_tag (ledger_entry_id, tag_id) VALUES (:e, :a), (:e, :b)"),
            {"e": first, "a": t1, "b": t2},
        )
    before = fingerprint(isolated_engine)
    out = delete_source(isolated_engine, done.source_id, dry_run=True)
    assert fingerprint(isolated_engine) == before
    assert out.dry_run and out.settle is None
    assert out.counts.entries == 2 and out.counts.tagged_entries == 1 and out.counts.tag_memberships == 2
    assert out.counts.partners_returning_to_review == 0 and out.counts.freed_documents == 0
    assert [e.id for e in out.removed] == [first, second]
    assert {e.id: e.tag_ids for e in out.removed}[first] == tuple(sorted((t1, t2)))


def test_dry_run_counts_confirmed_entries(isolated_engine: Engine, acct: int, world: dict[str, int]):
    done = enter(isolated_engine, acct, purpose="REWE")  # confirmed by the rule
    out = delete_source(isolated_engine, done.source_id, dry_run=True)
    assert out.counts.confirmed_entries == 1


def test_delete_with_a_partner_returns_it_to_review(
    isolated_engine: Engine, acct: int, world: dict[str, int]
):
    done = enter(isolated_engine, acct, amount=-100)
    (entry,) = [r.id for r in entries_of(isolated_engine, done.source_id)]
    leg = make_pair(isolated_engine, entry, world["b"])
    dry = delete_source(isolated_engine, done.source_id, dry_run=True)
    assert dry.counts.partners_returning_to_review == 1 and [p.id for p in dry.partners] == [leg]
    v = versions(isolated_engine, entry, leg)
    out = delete_source(isolated_engine, done.source_id, expected_versions=v)
    (p,) = q(isolated_engine, "SELECT * FROM ledger_entry WHERE id = :i", i=leg)
    assert p.counterpart_entry_id is None and p.type == "transfer" and p.counter_account_id is None
    assert [x.id for x in out.partners] == [leg] and out.partners[0].counterpart_entry_id is None
    assert [u.anchor_entry_id for u in out.units.views] == [leg]
    assert p.review_flags == ["unmatched_transfer"]  # no counter-account left: unpaired, nothing to wait for
    assert out.units.views[0].state.confirmed is False


def test_delete_needs_the_partners_version(isolated_engine: Engine, acct: int, world: dict[str, int]):
    done = enter(isolated_engine, acct, amount=-100)
    (entry,) = [r.id for r in entries_of(isolated_engine, done.source_id)]
    leg = make_pair(isolated_engine, entry, world["b"])
    before = fingerprint(isolated_engine)
    with pytest.raises(VersionConflict) as exc:
        delete_source(
            isolated_engine,
            done.source_id,
            expected_versions={entry: versions(isolated_engine, entry)[entry]},
        )
    assert exc.value.entry_ids == (leg,)
    assert fingerprint(isolated_engine) == before


def test_delete_refuses_an_imported_row(isolated_engine: Engine, acct: int):
    with isolated_engine.begin() as conn:
        s = make_source(conn, acct)
        e = make_entry(conn, s)
    before = fingerprint(isolated_engine)
    with pytest.raises(NotUserAuthored):
        delete_source(isolated_engine, s, expected_versions={e: 1})
    with pytest.raises(NotUserAuthored):
        delete_source(isolated_engine, s, dry_run=True)
    assert fingerprint(isolated_engine) == before
    with pytest.raises(SourceMissing):
        delete_source(isolated_engine, 99999, dry_run=True)


def test_delete_settles_once(isolated_engine: Engine, acct: int, monkeypatch: pytest.MonkeyPatch):
    done = enter(isolated_engine, acct)
    (e,) = entries_of(isolated_engine, done.source_id)
    calls: list[int] = []
    real = src.settle
    monkeypatch.setattr(src, "settle", lambda engine: calls.append(1) or real(engine))
    delete_source(isolated_engine, done.source_id, dry_run=True)
    assert calls == []
    delete_source(isolated_engine, done.source_id, expected_versions={e.id: e.version})
    assert calls == [1]


# ---- lock order (architecture §5.2) ------------------------------------------------------------


@pytest.mark.parametrize("op", ["create", "update", "delete"])
def test_every_entry_form_write_takes_the_settle_lock_shared_first(
    isolated_engine: Engine, acct: int, op: str
):
    """The settle lock is taken shared first: a write waiting on an account lock already holds it."""
    import threading

    from app.utils.db.locks import lock_accounts
    from tests import lockwatch

    settle_class = 1 << 24

    done = enter(isolated_engine, acct)
    (e,) = entries_of(isolated_engine, done.source_id)
    acts = {
        "create": lambda: enter(isolated_engine, acct),
        "update": lambda: update_source(
            isolated_engine, done.source_id, purpose="y", expected_versions={e.id: e.version}
        ),
        "delete": lambda: delete_source(isolated_engine, done.source_id, expected_versions={e.id: e.version}),
    }
    finished: list[Any] = []
    with isolated_engine.connect() as holder:
        with holder.begin():
            pid = int(holder.execute(text("SELECT pg_backend_pid()")).scalar_one())
            lock_accounts(holder, [acct])
            thread = threading.Thread(target=lambda: finished.append(acts[op]()))
            thread.start()
            lockwatch.wait_until_waiting(isolated_engine, f"{op} to wait for the account lock")
            held = lockwatch.advisory_held(
                isolated_engine, exclude_pid=pid, classid=settle_class, mode="ShareLock"
            )
            assert held == 1
    thread.join(timeout=15)
    assert not thread.is_alive() and len(finished) == 1
