"""The rederive walk of spec §5.9 (I18, D203): standing kept, proposals afresh, cascade."""

from __future__ import annotations

from app.core.resolution import Decided, diff, rederive, resolve, resolve_afresh
from tests.core.resolution.helpers import Script, account, entry

ACCOUNTS = [account(1), account(2), account(3)]


def go(current, classifiers):  # type: ignore[no-untyped-def]
    return rederive(entry(), current, accounts=ACCOUNTS, classifiers=classifiers)


def dec(value, pass_name):  # type: ignore[no-untyped-def]
    return Decided(value, pass_name, {"x": 1})


def values(r):  # type: ignore[no-untyped-def]
    return {f: d.value for f, d in r.items()}


def test_empty_current_resolves_everything_afresh() -> None:
    s = Script("history", {"type": "flow", "payee": 5, "category": 8})
    assert dict(go({}, [s])) == dict(resolve(entry(), accounts=ACCOUNTS, classifiers=[s]))


def test_a_standing_field_is_kept_and_later_fields_resolve_around_it() -> None:
    current = {"type": dec("flow", "rule"), "payee": dec(7, "user"), "category": dec(1, "history")}
    s = Script("history", {"category": lambda ctx: ctx.resolved["payee"].value + 100})
    r = go(current, [s])
    assert r["payee"] == current["payee"]
    assert r["category"].value == 107


def test_a_proposal_is_rederived_from_current_rules_and_history() -> None:
    current = {"type": dec("flow", "history"), "payee": dec(5, "history")}
    r = go(current, [Script("history", {"type": "flow", "payee": 6})])
    assert r["payee"].value == 6


def test_a_changed_value_derives_the_later_standing_fields_again() -> None:
    current = {"type": dec("flow", "history"), "payee": dec(5, "history"), "category": dec(8, "rule")}
    s = Script("history", {"type": "flow", "payee": 6, "category": 9})
    r = go(current, [s])
    assert values(r) == {"type": "flow", "payee": 6, "category": 9}


def test_an_unchanged_value_does_not_reopen_later_standing_fields() -> None:
    current = {"type": dec("flow", "history"), "payee": dec(5, "history"), "category": dec(8, "user")}
    r = go(current, [Script("history", {"type": "flow", "payee": 5, "category": 9})])
    assert r["category"] == current["category"]


def test_a_changed_type_drops_what_it_no_longer_allows() -> None:
    current = {"type": dec("flow", "history"), "payee": dec(5, "user"), "category": dec(8, "user")}
    r = go(current, [Script("history", {"type": "transfer", "counter_account": 2})])
    assert values(r) == {"type": "transfer", "counter_account": 2}


def test_a_standing_type_keeps_the_walk_in_its_branch() -> None:
    current = {"type": dec("transfer", "user"), "counter_account": dec(3, "history")}
    r = go(current, [Script("history", {"type": "flow", "counter_account": 2})])
    assert values(r) == {"type": "transfer", "counter_account": 2}


def test_a_value_that_disappears_is_a_change() -> None:
    current = {"type": dec("flow", "history"), "payee": dec(5, "history"), "category": dec(8, "rule")}
    r = go(current, [Script("history", {"type": "flow"})])
    assert dict(r) == {"type": r["type"]}


def test_a_user_value_is_kept_when_nothing_before_it_changed() -> None:
    current = {"type": dec("flow", "user"), "payee": dec(7, "user")}
    assert go(current, [Script("rule", {"type": "transfer"})])["payee"] == current["payee"]


def test_rederive_is_idempotent() -> None:
    s = [Script("rule", {"payee": 5}), Script("history", {"category": 8})]
    first = go({}, s)
    assert go(first, s) == first


def test_resolve_afresh_ignores_what_was_stored() -> None:
    s = Script("history", {"type": "flow", "payee": 6})
    r = resolve_afresh(entry(), accounts=ACCOUNTS, classifiers=[s])
    assert r["payee"].value == 6


def test_diff_lists_changed_new_and_removed_fields_only() -> None:
    old = {"type": dec("flow", "rule"), "payee": dec(5, "history"), "category": dec(8, "rule")}
    new = resolve(entry(), accounts=ACCOUNTS, classifiers=[Script("history", {"payee": 6})])
    changes = diff(old, new)
    assert set(changes) == {"type", "payee", "category"}
    assert changes["category"] is None
    assert diff(new, new) == {}
    assert diff({"payee": None}, {}) == {}


def test_a_second_settle_writes_nothing() -> None:
    s = [Script("rule", {"payee": 5}), Script("history", {"category": 8})]
    first = go({}, s)
    assert diff(first, go(first, s)) == {}


# ---- the third payee state: no payee by the user's decision (a standing key on a NULL) ------------


def test_a_value_decided_empty_is_a_standing_value_like_any_other() -> None:
    user_no_payee = Decided(None, "user", {})
    s = Script("rule", {"type": "flow", "payee": 6, "category": 9})

    # nothing before it changes: kept, and never proposed over
    kept = {"type": dec("flow", "rule"), "payee": user_no_payee, "category": dec(8, "rule")}
    r = go(kept, [s])
    assert r["payee"] == user_no_payee
    assert diff(r, go(r, [s])) == {}

    # an earlier value changes (the type is derived afresh): it is derived again
    current = {"payee": user_no_payee, "category": dec(8, "rule")}
    r = go(current, [s])
    assert r["payee"].value == 6
    assert r["category"].value == 9


def test_a_link_reopens_a_value_decided_empty_as_it_does_any_standing_value() -> None:
    user_no_payee = Decided(None, "user", {})
    current = {"type": dec("flow", "rule"), "payee": user_no_payee, "category": dec(1, "rule")}
    e = entry(documented=True, document_pass="matcher_decision")
    s = Script("rule", {"payee": 7, "category": 2})
    assert rederive(e, current, accounts=ACCOUNTS, classifiers=[s])["payee"] == user_no_payee  # plain: kept
    r = rederive(e, current, accounts=ACCOUNTS, classifiers=[s], reopen=True)
    assert r["payee"].value == 7 and r["payee"].pass_name == "rule"
    # nothing proposes: the payee is undecided afterwards, not decided empty
    r = rederive(e, current, accounts=ACCOUNTS, classifiers=[], reopen=True)
    assert "payee" not in r or not (r["payee"].value is None and r["payee"].pass_name == "user")


# ---- a document decides the type first, with the link's key (spec §5.9 field order) -----------------


def test_a_rule_keyed_flow_that_gets_a_document_becomes_document_decided_and_the_rest_is_derived_again() -> (
    None
):
    current = {"type": dec("flow", "rule"), "payee": dec(7, "rule"), "category": dec(1, "rule")}
    e = entry(documented=True, document_pass="matcher_decision")
    s = Script("rule", {"payee": 7, "category": 2})
    r = rederive(e, current, accounts=ACCOUNTS, classifiers=[s], reopen=True)
    assert r["type"] == Decided("flow", "matcher_decision", {})
    assert r["category"].value == 2  # re-derived: the link is new input


def test_a_stored_transfer_proposal_never_survives_a_document() -> None:
    current = {"type": dec("transfer", "history"), "counter_account": dec(2, "history")}
    s = Script("history", {"type": "transfer", "counter_account": 2})
    r = rederive(entry(documented=True), current, accounts=ACCOUNTS, classifiers=[s])
    assert r["type"] == Decided("flow", "user", {}) and "counter_account" not in r


def test_dropping_the_link_derives_the_type_again_as_for_any_entry() -> None:
    s = Script("history", {"type": "flow", "payee": 5})
    with_doc = rederive(entry(documented=True, document_pass="user"), {}, accounts=ACCOUNTS, classifiers=[s])
    assert with_doc["type"] == Decided("flow", "user", {})
    current = dict(with_doc)
    r = rederive(entry(), current, accounts=ACCOUNTS, classifiers=[s], reopen=True)
    assert r["type"] == Decided("flow", "history", {"by": "history", "v": "flow"})
