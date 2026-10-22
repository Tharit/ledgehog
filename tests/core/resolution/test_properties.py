"""Properties of resolution: deterministic, idempotent, I9-safe, order-independent."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from app.core.plugins.classifier import EMPTY, STANDING_PASSES, Field, Proposal
from app.core.resolution import Decided, Resolved, diff, rederive, resolve
from tests.core.resolution.helpers import Script, account, entry

ACCOUNTS = [
    account(1),
    account(2),
    account(3, "USD"),
    account(4, ref="de89370400440532013000"),
]
PASSES = ["rule", "history", "llm"]

fields: list[Field] = ["type", "payee", "category", "counter_account"]
answers = st.fixed_dictionaries(
    {},
    optional={
        "type": st.sampled_from(["flow", "transfer"]),
        "payee": st.one_of(st.integers(1, 3), st.just(EMPTY)),
        "category": st.integers(1, 3),
        "counter_account": st.integers(1, 6),
    },
)
scripts = st.lists(answers, max_size=3).map(
    lambda ans: [Script(PASSES[i], a) for i, a in enumerate(ans)]  # type: ignore[arg-type]
)
entries = st.builds(
    lambda ref, cur, inst, acct: entry(
        counterparty_ref=ref, currency=cur, instructed_currency=inst, account_id=acct
    ),
    st.sampled_from([None, "DE89 3704 0044 0532 0130 00", "x"]),
    st.sampled_from(["EUR", "USD"]),
    st.sampled_from([None, "USD", "EUR"]),
    st.integers(1, 4),
)
decideds = st.builds(
    lambda v, p: Decided(v, p, {}),
    st.integers(1, 3),
    st.sampled_from(["user", "rule", "history", "own_account"]),
)
currents = st.fixed_dictionaries(
    {},
    optional={
        "type": st.builds(
            lambda v, p: Decided(v, p, {}),
            st.sampled_from(["flow", "transfer"]),
            st.sampled_from(["user", "rule", "history"]),
        ),
        "payee": decideds,
        "category": decideds,
        "counter_account": decideds,
    },
)


def check_i9(e, r) -> None:  # type: ignore[no-untyped-def]
    if r.get("type") is None:
        assert dict(r) == {}
        return
    if r["type"].value == "flow":
        assert "counter_account" not in r
    else:
        assert "payee" not in r and "category" not in r
        if "counter_account" in r:
            assert r["counter_account"].value != e.account_id


@given(entries, scripts)
def test_resolve_is_deterministic_and_never_violates_i9(e, cs) -> None:  # type: ignore[no-untyped-def]
    a = resolve(e, accounts=ACCOUNTS, classifiers=cs)
    assert a == resolve(e, accounts=ACCOUNTS, classifiers=cs)
    check_i9(e, a)


@given(entries, scripts, currents)
def test_rederive_is_idempotent_and_never_violates_i9(e, cs, current) -> None:  # type: ignore[no-untyped-def]
    first = rederive(e, current, accounts=ACCOUNTS, classifiers=cs)
    check_i9(e, first)
    second = rederive(e, first, accounts=ACCOUNTS, classifiers=cs)
    assert second == first
    assert diff(first, second) == {}


@given(entries, scripts)
def test_account_order_does_not_matter(e, cs) -> None:  # type: ignore[no-untyped-def]
    a = resolve(e, accounts=ACCOUNTS, classifiers=cs)
    b = resolve(e, accounts=list(reversed(ACCOUNTS)), classifiers=cs)
    assert a == b


@given(entries, scripts, currents)
def test_standing_values_before_any_change_are_kept(e, cs, current) -> None:  # type: ignore[no-untyped-def]
    r = rederive(e, current, accounts=ACCOUNTS, classifiers=cs)
    t = current.get("type")
    if t is not None and t.pass_name == "user":
        assert r["type"] == t


def test_proposal_import_is_used() -> None:
    assert Proposal("type", "flow", {}).value == "flow"


def _walk_resolving_each_field(e, current, cs) -> Resolved:  # type: ignore[no-untyped-def]
    """Reference for `rederive`: the walk of spec §5.9 with a full resolve for every field."""
    fixed: dict[Field, Decided] = {}
    changed = False

    def step(field: Field) -> Decided | None:
        nonlocal changed
        cur = current.get(field)
        own = field == "counter_account" and cur is not None and cur.value == e.account_id
        if cur is not None and cur.pass_name in STANDING_PASSES and not changed and not own:
            new = cur
        else:
            new = resolve(e, accounts=ACCOUNTS, classifiers=cs, fixed=fixed).get(field)
            changed = changed or (new.value if new else None) != (cur.value if cur else None)
        if new is not None:
            fixed[field] = new
        return new

    kind = step("type")
    for field in (
        ("counter_account",)
        if kind and kind.value == "transfer"
        else (("payee", "category") if kind and kind.value == "flow" else ())
    ):
        step(field)  # type: ignore[arg-type]
    return Resolved(fixed)


@given(entries, scripts, currents)
def test_rederive_equals_resolving_around_each_field(e, cs, current) -> None:  # type: ignore[no-untyped-def]
    """The one-resolve shortcut in `rederive` changes nothing: it equals a resolve per field."""
    assert rederive(e, current, accounts=ACCOUNTS, classifiers=cs) == _walk_resolving_each_field(
        e, current, cs
    )
