"""Settle step 1, resolution (architecture §5.2, spec §5.9): rederive every unconfirmed entry.

The baseline is a pass over all unconfirmed units. For each entry the stored values and keys
become the `current` decisions, `rederive` walks the fields (standing keys kept, proposals
resolved afresh, a changed value rederiving the standing ones after it), and only the differences
are written: `type`, `payee_id`, `category_id`, `counter_account_id` and their `derivation` keys,
in one set-based statement under `ledger.settling`, so no version moves. A second settle finds
nothing to write (I37). Confirmed units are never read (I20).

A paired leg of an unconfirmed unit is rederived like any other (spec §5.7, I18). When its `type` or its
OWN counter-account changes the pair falls: it is released on both legs (`rewrite_released`) and step 4
may make it again in the same round. A counter-account whose key basis is `{"from": "counterpart"}` is
the pair's, not a guess: it is never compared and goes with the pair.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import Connection, text

from app.core.model.queue import current_model_queue
from app.core.plugins.classifier import (
    FIELD_ORDER,
    STANDING_PASSES,
    AccountFact,
    Classifier,
    Field,
    HistorySource,
)
from app.core.resolution import Decided, Resolved, diff, rederive
from app.core.resolution.load import UnconfirmedEntry, load_accounts, load_rules, load_unconfirmed
from app.core.resolution.registry import classifiers_for
from app.core.resolution.snapshot import load_snapshot, load_votes_of, touches
from app.core.resolution.types import USER_NO_PAYEE, column_of, is_user_no_payee
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
           counter_account_id = v.counter_account_id, derivation = CAST(v.derivation AS jsonb),
           counterpart_entry_id = CASE WHEN v.unpair THEN NULL ELSE e.counterpart_entry_id END
      FROM unnest(CAST(:ids AS bigint[]), CAST(:types AS text[]), CAST(:payees AS bigint[]),
                  CAST(:categories AS bigint[]), CAST(:counters AS bigint[]), CAST(:derivations AS text[]),
                  CAST(:unpair AS boolean[]))
           AS v(id, type, payee_id, category_id, counter_account_id, derivation, unpair)
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


def _stored_absence(key: object) -> Decided | None:
    """The key of an empty field that explains the absence (`"none": true`, a proposal's: a standing pass
    has no such key), as the decision it is; any other key on an empty field is none."""
    if not isinstance(key, Mapping) or not isinstance(key.get("pass"), str) or key["pass"] in STANDING_PASSES:
        return None
    basis = key.get("basis")
    if not isinstance(basis, Mapping) or basis.get("none") is not True:
        return None
    return Decided(None, key["pass"], dict(basis))


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
            # the keys a NULL carries: the user's decision of no payee (a standing key) and a proposal's
            # explained absence
            is_decision = f == "payee" and isinstance(key, Mapping) and key.get("pass") == "user"
            current[f] = USER_NO_PAYEE if is_decision else _stored_absence(key)
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
    """A key of a field that has no decision: it is removed (a key explains a value or an absence).
    `stored_decisions` reads the user's decision of no payee and a proposal's explained absence as
    decisions; they stand while resolution produces them again (`diff`)."""
    return any(f in row.derivation and current[f] is None for f in _COLUMN)


@dataclass(frozen=True, slots=True)
class Rewrite:
    """What settling writes on one entry: its four values and its whole `derivation`."""

    type: str | None
    payee_id: int | None
    category_id: int | None
    counter_account_id: int | None
    derivation: dict[str, Any]
    unpair: bool = False  # the entry's pair is released with this write (the partner's is too)


def _is_pair_set(key: object) -> bool:
    """A counter-account key made by a pair (basis `{"from": "counterpart"}`): the pair's, not a guess."""
    basis = key.get("basis") if isinstance(key, Mapping) else None
    return isinstance(basis, Mapping) and basis.get("from") == "counterpart"


def _rewrite(row: UnconfirmedEntry, new: Resolved, *, unpair: bool = False) -> Rewrite:
    kind = new.get("type")
    return Rewrite(
        type=str(kind.value) if kind is not None else None,
        payee_id=column_of(new.get("payee")),
        category_id=column_of(new.get("category")),
        counter_account_id=column_of(new.get("counter_account")),
        derivation=new_derivation(row.derivation, new),
        unpair=unpair,
    )


def rewrite_of(
    row: UnconfirmedEntry,
    *,
    accounts: Sequence[AccountFact],
    classifiers: Sequence[Classifier],
    history: HistorySource | None,
    reopen: bool = False,
) -> Rewrite | None:
    """What step 1 writes for one entry of an unconfirmed unit, or None when it writes nothing.

    The unit preview's decision (an unpaired entry's; settling takes the same for these), so a preview
    cannot drift from the settle that follows a commit. A paired leg is not rewritten here: settling
    rederives it too and releases the pair when it falls (`settle_rewrites`), which the preview does not
    yet simulate. Nor is a transfer on an entry that is not its source's original (I31).
    """
    if row.paired:
        return None
    current, new = _rederived(row, accounts=accounts, classifiers=classifiers, history=history, reopen=reopen)
    if not diff(current, new) and not _stale_keys(row, current):
        return None
    return _checked(row, new)


def _checked(row: UnconfirmedEntry, new: Resolved) -> Rewrite | None:
    kind = new.get("type")
    if kind is not None and kind.value == "transfer" and not row.original:
        # a source transaction has at most one transfer entry (I31), and a split's other
        # entries are flows: leave this one as it is rather than break the unique index
        return None
    return _rewrite(row, new)


def _rederived(
    row: UnconfirmedEntry,
    *,
    accounts: Sequence[AccountFact],
    classifiers: Sequence[Classifier],
    history: HistorySource | None,
    reopen: bool = False,
) -> tuple[dict[Field, Decided | None], Resolved]:
    current = stored_decisions(row)
    new = rederive(
        row.input,
        current,
        accounts=accounts,
        classifiers=classifiers,
        history=history,
        exclude_entry_ids=frozenset({row.input.entry_id}),
        reopen=reopen,
    )
    return current, new


def pair_falls(row: UnconfirmedEntry, new: Resolved) -> bool:
    """Whether the rederived values of a paired leg end its pair: its type or its own counter-account
    differs from what is stored (§5.7, I18). A counter-account its pair set is not compared."""
    kind = new.get("type")
    if (str(kind.value) if kind is not None else None) != row.type:
        return True
    if _is_pair_set(row.derivation.get("counter_account")):
        return False
    return column_of(new.get("counter_account")) != row.counter_account_id


def _stripped(row: UnconfirmedEntry) -> UnconfirmedEntry:
    """The leg as it is once its pair is released: no counterpart, no counter-account the pair set, no
    pair key, every other value and key kept (what `removal._release` leaves)."""
    derivation = {k: v for k, v in row.derivation.items() if k != "counterpart"}
    counter = row.counter_account_id
    if _is_pair_set(row.derivation.get("counter_account")):
        derivation.pop("counter_account", None)
        counter = None
    return replace(row, paired=False, counterpart_id=None, counter_account_id=counter, derivation=derivation)


def rewrite_released(
    row: UnconfirmedEntry,
    *,
    accounts: Sequence[AccountFact],
    classifiers: Sequence[Classifier],
    history: HistorySource | None,
    reopen: bool = False,
) -> Rewrite:
    """What step 1 writes for a leg whose pair is released (it or its partner fell): always a write.

    The leg is rederived as the unpaired leg it now is, so a second settle finds it as it is left.
    """
    leg = _stripped(row)
    _, new = _rederived(leg, accounts=accounts, classifiers=classifiers, history=history, reopen=reopen)
    kind = new.get("type")
    if kind is not None and kind.value == "transfer" and not leg.original:
        return Rewrite(  # cannot happen for a leg that was paired; keep its values rather than break I31
            leg.type, leg.payee_id, leg.category_id, leg.counter_account_id, dict(leg.derivation), True
        )
    return _rewrite(leg, new, unpair=True)


def settle_rewrites(
    rows: Sequence[UnconfirmedEntry],
    *,
    reach: Callable[[UnconfirmedEntry], bool],
    accounts: Sequence[AccountFact],
    classifiers: Sequence[Classifier],
    history: HistorySource | None,
    reopen: bool = False,
) -> dict[int, Rewrite]:
    """What step 1 writes, by entry id, for the entries of `rows` that `reach` selects.

    An unpaired entry as `rewrite_of`. A paired leg is rederived: when its type or its own counter-account
    changes, both legs of the pair are released (each is rederived as the unpaired leg it becomes and is
    always written, the partner even if `reach` skipped it); otherwise its differences are written and
    the pair stands (a changed basis writes the key only). `reopen`: every value of the entries `reach`
    selects is derived again (step 3, after a link).
    """
    by_id = {r.input.entry_id: r for r in rows}
    out: dict[int, Rewrite] = {}
    released: set[int] = set()
    for row in rows:
        if not reach(row):
            continue
        if not row.paired:
            if rewrite := rewrite_of(
                row, accounts=accounts, classifiers=classifiers, history=history, reopen=reopen
            ):
                out[row.input.entry_id] = rewrite
            continue
        current, new = _rederived(
            row, accounts=accounts, classifiers=classifiers, history=history, reopen=reopen
        )
        if pair_falls(row, new):
            released.add(row.input.entry_id)
            if row.counterpart_id in by_id:
                released.add(row.counterpart_id)
        elif (diff(current, new) or _stale_keys(row, current)) and (rewrite := _checked(row, new)):
            out[row.input.entry_id] = rewrite
    for entry_id in released:
        out[entry_id] = rewrite_released(
            by_id[entry_id],
            accounts=accounts,
            classifiers=classifiers,
            history=history,
            reopen=reopen and reach(by_id[entry_id]),  # a partner `reach` skipped keeps its standing values
        )
    return out


def resolve_step(conn: Connection) -> StepOutcome:
    run = current_run()
    ctx = _context(conn, run)

    def reach(row: UnconfirmedEntry) -> bool:
        # after the first pass only what the new votes can reach is resolved again: rules and accounts
        # do not change within a settle, and a second pass over unchanged inputs writes nothing
        return ctx.grown is None or touches(ctx.grown, row.input, row.payee_id)

    rows = load_unconfirmed(conn)
    rewrites = settle_rewrites(
        rows,
        reach=reach,
        accounts=ctx.accounts,
        classifiers=ctx.classifiers,
        history=ctx.snapshot,
    )
    if rewrites:
        run.documents_dirty = True  # a payee may have changed: step 2 looks again
    outcome = write_rewrites(conn, rewrites)
    _list_for_model(rows, rewrites)
    return outcome


def _list_for_model(rows: Sequence[UnconfirmedEntry], rewrites: Mapping[int, Rewrite]) -> None:
    """Hand the model's list the entries whose category falls to pass 3 (spec §5.9, architecture §5.4):
    a flow, or an entry without a type yet, that no pass proposed a category for (no value, no explained
    absence: such a key says the field is answered), whose payload is not empty. Settling never waits for
    the model: this only fills an in-memory list. No model configured: nothing is listed."""
    queue = current_model_queue()
    if queue is None:
        return
    wanted: list[tuple[int, str]] = []
    for row in rows:
        if row.paired:
            continue
        rewrite = rewrites.get(row.input.entry_id)
        kind, category = (rewrite.type, rewrite.category_id) if rewrite else (row.type, row.category_id)
        derivation = rewrite.derivation if rewrite else row.derivation
        if kind not in (None, "flow") or category is not None or "category" in derivation:
            continue  # a key on the empty category is a proposal's explained absence (an entry settling
            # does not rewrite carries only keys resolution produced)
        if (fingerprint := queue.fingerprint(row.input)) is not None:
            wanted.append((row.input.entry_id, fingerprint))
    queue.sync(wanted)


def write_rewrites(conn: Connection, rewrites: Mapping[int, Rewrite]) -> StepOutcome:
    """Write the rewrites in one set-based statement (under `ledger.settling`: no version moves)."""
    if not rewrites:
        return StepOutcome()
    ids = sorted(rewrites)
    written = conn.execute(
        _WRITE,
        {
            "ids": ids,
            "types": [rewrites[i].type for i in ids],
            "payees": [rewrites[i].payee_id for i in ids],
            "categories": [rewrites[i].category_id for i in ids],
            "counters": [rewrites[i].counter_account_id for i in ids],
            "derivations": [json.dumps(rewrites[i].derivation) for i in ids],
            "unpair": [rewrites[i].unpair for i in ids],
        },
    ).scalars()
    return StepOutcome(touched=[int(i) for i in written])
