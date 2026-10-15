"""Settle step 1, resolution (architecture §5.2, spec §5.9): rederive every unconfirmed entry.

The baseline is a pass over all unconfirmed units. For each entry the stored values and keys
become the `current` decisions, `rederive` walks the fields (standing keys kept, proposals
resolved afresh, a changed value rederiving the standing ones after it), and only the differences
are written: `type`, `payee_id`, `category_id`, `counter_account_id` and their `derivation` keys,
in one set-based statement under `ledger.settling`, so no version moves. A second settle finds
nothing to write (I37). Confirmed units are never read (I20).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, text

from app.core.plugins.classifier import FIELD_ORDER, AccountFact, Classifier, Field, HistorySource
from app.core.resolution import Decided, Resolved, diff, rederive
from app.core.resolution.load import UnconfirmedEntry, load_accounts, load_rules, load_unconfirmed
from app.core.resolution.registry import classifiers_for
from app.core.resolution.snapshot import load_snapshot, load_votes_of, touches
from app.core.resolution.types import USER_NO_PAYEE, is_user_no_payee
from app.core.settle.run import ResolutionContext, SettleRun, StepOutcome, current_run

_COLUMN: dict[Field, str] = {
    "type": "type",
    "payee": "payee_id",
    "category": "category_id",
    "counter_account": "counter_account_id",
}

_WRITE = text(
    """
    UPDATE ledger_entry AS e
       SET type = v.type, payee_id = v.payee_id, category_id = v.category_id,
           counter_account_id = v.counter_account_id, derivation = CAST(v.derivation AS jsonb)
      FROM unnest(CAST(:ids AS bigint[]), CAST(:types AS text[]), CAST(:payees AS bigint[]),
                  CAST(:categories AS bigint[]), CAST(:counters AS bigint[]), CAST(:derivations AS text[]))
           AS v(id, type, payee_id, category_id, counter_account_id, derivation)
     WHERE e.id = v.id
    RETURNING e.id
    """
)


def _context(conn: Connection, run: SettleRun) -> ResolutionContext:
    """Accounts, the classifiers for the rules, and the history snapshot: loaded once per settle."""
    if run.resolution is None:
        classifiers = classifiers_for(load_rules(conn))
        run.resolution = ResolutionContext(load_accounts(conn), classifiers, load_snapshot(conn))
    else:
        run.resolution.grown = run.resolution.snapshot.add(load_votes_of(conn, run.to_teach))
    run.to_teach.clear()
    return run.resolution


def stored_decisions(row: UnconfirmedEntry) -> dict[Field, Decided | None]:
    """The decisions on the entry now. A value without a key is kept as a user's: never destroyed."""
    values: dict[Field, int | str | None] = {
        "type": row.type,
        "payee": row.payee_id,
        "category": row.category_id,
        "counter_account": row.counter_account_id,
    }
    current: dict[Field, Decided | None] = {}
    for f in FIELD_ORDER:
        value = values[f]
        key = row.derivation.get(f)
        if value is None:
            # the one key a NULL carries: the user's decision of no payee (a standing key)
            is_decision = f == "payee" and isinstance(key, Mapping) and key.get("pass") == "user"
            current[f] = USER_NO_PAYEE if is_decision else None
            continue
        if isinstance(key, Mapping) and isinstance(key.get("pass"), str):
            basis = key.get("basis")
            current[f] = Decided(value, key["pass"], dict(basis) if isinstance(basis, Mapping) else {})
        else:
            current[f] = Decided(value, "user", {})
    return current


def new_derivation(old: Mapping[str, Any], new: Resolved) -> dict[str, Any]:
    out = {k: v for k, v in old.items() if k not in _COLUMN}
    for f, d in new.items():
        out[f] = {"pass": "user"} if is_user_no_payee(d) else {"pass": d.pass_name, "basis": dict(d.basis)}
    return out


def _stale_keys(row: UnconfirmedEntry, current: Mapping[Field, Decided | None]) -> bool:
    """A key of a field that has no value: it is removed (a key explains a value). The user's decision of
    no payee is the exception: a standing key on a NULL (`stored_decisions` reads it as a decision)."""
    return any(f in row.derivation and current[f] is None for f in _COLUMN)


@dataclass(frozen=True, slots=True)
class Rewrite:
    """What settling writes on one entry: its four values and its whole `derivation`."""

    type: str | None
    payee_id: int | None
    category_id: int | None
    counter_account_id: int | None
    derivation: dict[str, Any]


def rewrite_of(
    row: UnconfirmedEntry,
    *,
    accounts: Sequence[AccountFact],
    classifiers: Sequence[Classifier],
    history: HistorySource | None,
) -> Rewrite | None:
    """What step 1 writes for one entry of an unconfirmed unit, or None when it writes nothing.

    The one decision both settling and the unit preview take, so a preview cannot drift from the settle
    that follows a commit. A paired leg is never rewritten (the pair owns its type and counter-account),
    nor is a transfer on an entry that is not its source's original (I31).
    """
    if row.paired:  # a pair's type and counter-account belong to the pair (spec §5.7, step 8)
        return None
    current = stored_decisions(row)
    new = rederive(
        row.input,
        current,
        accounts=accounts,
        classifiers=classifiers,
        history=history,
        exclude_entry_ids=frozenset({row.input.entry_id}),
    )
    if not diff(current, new) and not _stale_keys(row, current):
        return None
    kind = new.get("type")
    if kind is not None and kind.value == "transfer" and not row.original:
        # a source transaction has at most one transfer entry (I31), and a split's other
        # entries are flows: leave this one as it is rather than break the unique index
        return None

    def value(d: Decided | None) -> int | None:
        return int(d.value) if d is not None and not is_user_no_payee(d) else None

    return Rewrite(
        type=str(kind.value) if kind is not None else None,
        payee_id=value(new.get("payee")),
        category_id=value(new.get("category")),
        counter_account_id=value(new.get("counter_account")),
        derivation=new_derivation(row.derivation, new),
    )


def resolve_step(conn: Connection) -> StepOutcome:
    run = current_run()
    ctx = _context(conn, run)
    ids: list[int] = []
    types: list[str | None] = []
    payees: list[int | None] = []
    categories: list[int | None] = []
    counters: list[int | None] = []
    derivations: list[str] = []
    for row in load_unconfirmed(conn):
        # after the first pass only what the new votes can reach is resolved again: rules and accounts
        # do not change within a settle, and a second pass over unchanged inputs writes nothing
        if ctx.grown is not None and not touches(ctx.grown, row.input, row.payee_id):
            continue
        rewrite = rewrite_of(row, accounts=ctx.accounts, classifiers=ctx.classifiers, history=ctx.snapshot)
        if rewrite is None:
            continue
        ids.append(row.input.entry_id)
        types.append(rewrite.type)
        payees.append(rewrite.payee_id)
        categories.append(rewrite.category_id)
        counters.append(rewrite.counter_account_id)
        derivations.append(json.dumps(rewrite.derivation))
    if not ids:
        return StepOutcome()
    written = conn.execute(
        _WRITE,
        {
            "ids": ids,
            "types": types,
            "payees": payees,
            "categories": categories,
            "counters": counters,
            "derivations": derivations,
        },
    ).scalars()
    return StepOutcome(touched=[int(i) for i in written])
