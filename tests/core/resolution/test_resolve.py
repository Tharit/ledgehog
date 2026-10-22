"""resolve: field order, first proposal wins, I9 (spec §5.9), with scripted classifiers."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.plugins.classifier import EMPTY
from app.core.resolution import Decided, resolve
from tests.core.resolution.helpers import DAY, Boom, Script, account, entry

ACCOUNTS = [account(1), account(2), account(3, "USD"), account(4, closed_on=DAY - timedelta(days=5))]
OWN_REF = "de89370400440532013000"


def run(classifiers: list[Script], e=None, **kw):  # type: ignore[no-untyped-def]
    return resolve(e or entry(), accounts=ACCOUNTS, classifiers=classifiers, **kw)


def values(r) -> dict:  # type: ignore[no-untyped-def]
    return {f: d.value for f, d in r.items()}


def test_no_evidence_is_empty() -> None:
    assert dict(run([Script("rule", {}), Script("history", {})])) == {}
    assert dict(run([])) == {}


def test_pass_zero_decides_transfer_and_counter_and_asks_nobody() -> None:
    s = Script("rule", {"payee": 9, "category": 8})
    accounts = [account(1), account(2, ref=OWN_REF)]
    r = resolve(entry(counterparty_ref=OWN_REF), accounts=accounts, classifiers=[s])
    assert values(r) == {"type": "transfer", "counter_account": 2}
    assert r["type"].pass_name == r["counter_account"].pass_name == "own_account"
    assert r["type"].basis == {"account_id": 2}
    assert s.calls == []


def test_a_type_proposal_decides_and_carries_its_basis() -> None:
    r = run([Script("history", {"type": "flow", "payee": 5})])
    assert r["type"] == Decided("flow", "history", {"by": "history", "v": "flow"})
    assert values(r) == {"type": "flow", "payee": 5}


def test_first_proposal_wins_per_field_in_classifier_order() -> None:
    rules = Script("rule", {"payee": 5})
    history = Script("history", {"payee": 6, "category": 7})
    r = run([rules, history])
    assert (r["payee"].value, r["payee"].pass_name) == (5, "rule")
    assert (r["category"].value, r["category"].pass_name) == (7, "history")


def test_a_payee_proposal_makes_the_type_flow_with_its_key() -> None:
    r = run([Script("rule", {"payee": 5})])
    assert r["type"] == Decided("flow", "rule", {"by": "rule", "v": 5})


def test_a_category_proposal_makes_the_type_flow() -> None:
    r = run([Script("rule", {"category": 8})])
    assert values(r) == {"type": "flow", "category": 8}


def test_a_counter_account_proposal_makes_the_type_transfer() -> None:
    r = run([Script("rule", {"counter_account": 2})])
    assert r["type"] == Decided("transfer", "rule", {"by": "rule", "v": 2})
    assert values(r) == {"type": "transfer", "counter_account": 2}


def test_counter_account_rules_come_before_payee_rules() -> None:
    r = run([Script("rule", {"counter_account": 2, "payee": 5})])
    assert values(r) == {"type": "transfer", "counter_account": 2}


def test_an_earlier_classifier_decides_the_type_by_authority() -> None:
    r = run([Script("rule", {"payee": 5}), Script("history", {"type": "transfer"})])
    assert r["type"].value == "flow"


def test_a_transfer_never_gets_payee_or_category() -> None:
    r = run([Script("history", {"type": "transfer", "payee": 5, "category": 8})])
    assert values(r) == {"type": "transfer"}


def test_a_flow_never_gets_a_counter_account() -> None:
    r = run([Script("history", {"type": "flow", "counter_account": 2})])
    assert "counter_account" not in r


@pytest.mark.parametrize("target", [3, 4, 1, 99], ids=["currency", "closed", "own", "unknown"])
def test_a_counter_proposal_breaking_core_tests_is_dropped_for_the_next_pass(target: int) -> None:
    rules = Script("rule", {"type": "transfer", "counter_account": target})
    history = Script("history", {"counter_account": 2})
    r = run([rules, history])
    assert (r["counter_account"].value, r["counter_account"].pass_name) == (2, "history")


def test_a_dropped_counter_proposal_does_not_decide_the_type() -> None:
    assert dict(run([Script("rule", {"counter_account": 3})])) == {}


def test_a_transfer_with_no_acceptable_counter_account_stays_a_bare_transfer() -> None:
    r = run([Script("history", {"type": "transfer", "counter_account": 4})])
    assert values(r) == {"type": "transfer"}


def test_instructed_currency_selects_the_counter_account() -> None:
    e = entry(instructed_currency="USD")
    r = run([Script("rule", {"counter_account": 3})], e)
    assert values(r) == {"type": "transfer", "counter_account": 3}


def test_ctx_account_ok_is_core_s_test() -> None:
    seen: list[bool] = []

    def probe(ctx):  # type: ignore[no-untyped-def]
        seen.extend([ctx.account_ok(2), ctx.account_ok(3), ctx.account_ok(4), ctx.account_ok(1)])

    run([Script("rule", {"type": probe})])
    assert seen == [True, False, False, False]


def test_classifiers_see_what_is_resolved_so_far() -> None:
    s = Script("history", {"type": "flow", "payee": 5, "category": 8})
    run([s])
    asked = {f: resolved for f, resolved in s.calls if f in ("payee", "category")}
    # the first payee call is the type probe, the last ones are the fields themselves
    assert s.calls[-2] == ("payee", ("type",))
    assert s.calls[-1] == ("category", ("type", "payee"))
    assert asked


def test_a_category_rule_reads_the_resolved_payee() -> None:
    def by_payee(ctx):  # type: ignore[no-untyped-def]
        p = ctx.resolved.get("payee")
        return 8 if p is not None and p.value == 5 else None

    r = run([Script("rule", {"payee": 5, "category": by_payee})])
    assert values(r) == {"type": "flow", "payee": 5, "category": 8}


def test_no_payee_ends_the_payee_field_and_category_still_resolves() -> None:
    history = Script("history", {"type": "flow", "payee": EMPTY, "category": 8})
    llm = Script("llm", {"payee": 9})
    r = run([history, llm])
    assert values(r) == {"type": "flow", "category": 8}
    assert ("payee", ("type",)) not in llm.calls


def test_no_payee_alone_does_not_decide_the_type() -> None:
    assert dict(run([Script("history", {"payee": EMPTY})])) == {}


def test_a_later_pass_is_tried_when_an_earlier_has_none() -> None:
    r = run([Script("rule", {}), Script("history", {"type": "flow", "category": 8})])
    assert r["category"].pass_name == "history"


def test_fixed_fields_are_decided_and_others_resolve_around_them() -> None:
    fixed = {"type": Decided("flow", "user", {}), "payee": Decided(7, "user", {})}
    s = Script("rule", {"payee": 5, "category": 8, "counter_account": 2})
    r = run([s], fixed=fixed)
    assert (r["payee"].value, r["payee"].pass_name) == (7, "user")
    assert r["category"].value == 8
    assert "counter_account" not in r
    assert not any(f == "payee" for f, _ in s.calls)


def test_a_fixed_type_wins_over_pass_zero_and_classifiers() -> None:
    accounts = [account(1), account(2, ref=OWN_REF)]
    fixed = {"type": Decided("flow", "user", {})}
    r = resolve(
        entry(counterparty_ref=OWN_REF),
        accounts=accounts,
        classifiers=[Script("rule", {"type": "transfer"})],
        fixed=fixed,
    )
    assert values(r) == {"type": "flow"}


def test_pass_zero_supplies_the_counter_account_of_a_fixed_transfer() -> None:
    accounts = [account(1), account(2, ref=OWN_REF), account(3)]
    r = resolve(
        entry(counterparty_ref=OWN_REF),
        accounts=accounts,
        classifiers=[Script("rule", {"counter_account": 3})],
        fixed={"type": Decided("transfer", "user", {})},
    )
    assert (r["counter_account"].value, r["counter_account"].pass_name) == (2, "own_account")


def test_a_fixed_counter_account_is_not_overridden_by_pass_zero() -> None:
    accounts = [account(1), account(2, ref=OWN_REF), account(3)]
    fixed = {"counter_account": Decided(3, "user", {})}
    r = resolve(entry(counterparty_ref=OWN_REF), accounts=accounts, classifiers=[], fixed=fixed)
    assert values(r) == {"type": "transfer", "counter_account": 3}
    assert r["type"].pass_name == "user"


def test_a_fixed_payee_implies_flow_and_drops_nothing_it_allows() -> None:
    r = run([Script("history", {"type": "transfer"})], fixed={"payee": Decided(7, "user", {})})
    assert values(r) == {"type": "flow", "payee": 7}


def test_fixed_fields_the_type_does_not_allow_are_left_out() -> None:
    fixed = {"type": Decided("transfer", "user", {}), "payee": Decided(7, "user", {})}
    assert values(run([], fixed=fixed)) == {"type": "transfer"}


def test_the_own_account_is_never_a_counter_account_even_fixed() -> None:
    fixed = {"counter_account": Decided(1, "user", {})}
    assert "counter_account" not in run([], fixed=fixed)


def test_a_classifier_crash_propagates() -> None:
    with pytest.raises(RuntimeError, match="crashed"):
        run([Boom()])  # type: ignore[list-item]


def test_a_malformed_proposal_is_an_error() -> None:
    with pytest.raises(ValueError):
        run([Script("rule", {"type": "maybe"})])
    with pytest.raises(ValueError):
        run([Script("rule", {"type": "flow", "payee": "x"})])


def test_resolved_is_immutable_and_ordered() -> None:
    r = run([Script("rule", {"category": 8, "payee": 5})])
    assert list(r) == ["type", "payee", "category"]
    with pytest.raises(TypeError):
        r["payee"] = Decided(1, "x", {})  # type: ignore[index]


# ---- a document decides the type `flow` first, with the link's key (spec §5.9 field order) ----


@pytest.mark.parametrize("link", ["user", "matcher_decision", "matcher_proposal"])
def test_a_document_decides_flow_with_the_key_of_its_link_and_an_empty_basis(link: str) -> None:
    r = run([Script("rule", {"payee": 5})], entry(documented=True, document_pass=link))
    assert r["type"] == Decided("flow", link, {})
    assert r["payee"].value == 5  # the payee and category passes run as for any flow


def test_a_document_without_a_known_link_pass_reads_as_a_pick() -> None:
    assert run([], entry(documented=True))["type"] == Decided("flow", "user", {})


def test_a_documented_entry_with_no_other_evidence_is_still_a_flow() -> None:
    assert values(run([], entry(documented=True, document_pass="matcher_decision"))) == {"type": "flow"}


def test_the_own_account_pass_proposes_no_transfer_for_a_documented_entry() -> None:
    accounts = [account(1), account(2, ref=OWN_REF)]
    e = entry(counterparty_ref=OWN_REF, documented=True)
    assert values(resolve(e, accounts=accounts, classifiers=[])) == {"type": "flow"}
    undocumented = resolve(entry(counterparty_ref=OWN_REF), accounts=accounts, classifiers=[])
    assert values(undocumented) == {"type": "transfer", "counter_account": 2}  # the control


@pytest.mark.parametrize(
    "proposal",
    [
        {"type": "transfer", "counter_account": 2},  # a rule, history or the model proposing the type
        {"counter_account": 2},  # a counter-account proposal is a transfer proposal
    ],
)
@pytest.mark.parametrize("name", ["rule", "history", "llm"])
def test_a_transfer_proposal_of_any_pass_is_ignored_for_a_documented_entry(name: str, proposal: dict) -> None:
    script = Script(name, proposal)
    r = run([script], entry(documented=True, document_pass="matcher_decision"))
    assert r["type"] == Decided("flow", "matcher_decision", {})
    assert "counter_account" not in r
    assert run([Script(name, proposal)])["type"].value == "transfer"  # without a document it decides


def test_a_standing_flow_of_another_pass_becomes_document_decided() -> None:
    fixed = {"type": Decided("flow", "rule", {"rule_id": 1})}
    r = run([], entry(documented=True, document_pass="user"), fixed=fixed)
    assert r["type"] == Decided("flow", "user", {})


def test_a_documented_entry_still_resolves_a_flow_from_a_payee() -> None:
    r = run([Script("rule", {"type": "transfer", "payee": 5})], entry(documented=True))
    assert r["type"].value == "flow" and r["payee"].value == 5
