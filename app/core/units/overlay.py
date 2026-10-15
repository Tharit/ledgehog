"""A draft laid over a stored unit, in memory (spec §5.9, §6, architecture §6.3): what a commit would do.

`plan_unit` is pure. It runs the functions settling runs, over rows that exist only here:

1. The draft's rows are assembled: removals, the rows a split creates (temporary ids), allocations. A
   source's ORIGINAL entry (its lowest stored id) is the residual: it takes what the other entries leave.
2. Each entry's derived fields are walked in field order (§5.9 "Rederiving"): a drafted value is decided and
   the fields after it resolve around it; an untouched field is kept when it is standing and resolved afresh
   when it is a proposal; a re-resolved field is decided by the passes again. A paired leg's type and
   counter-account belong to the pair (§5.7) until the draft moves them, which breaks the pair: the former
   partner is left behind (the removal routine, `core.ingest.removal.unpair`).
3. Keys are derived as a commit derives them (§5.9, D212): a value left as stored keeps a standing key, an
   accepted proposal becomes `user` with the proposal's key as its basis, anything else is `user` without one.
   That is `Written`, the state a commit writes.
4. Settling is simulated over the result (`core.settle.resolution.settle_rewrites`, the function step 1 calls,
   and the pure `pair_all` of step 4): every unit still not confirmed is rederived, a paired leg whose guess
   changed releases its pair, legs are paired, units that became confirmed teach history, and the rounds
   repeat until nothing more is confirmed. Pairing runs over the plan's unpaired transfer legs and, in a
   preview, every other unpaired transfer leg of the ledger (`World.ledger_legs`); a pair with a leg outside
   the plan is reported (`Plan.pulled_entry_ids`) for the preview to bring that leg's unit in and plan again.
   That is the state the user will find afterwards.
5. The invariants the schema's deferred triggers would check are checked here (`Problem`), so a commit is
   refused by code with a machine code, not by an aborted transaction.

A drafted partner (`DraftEntry.pairing`, spec §5.7) is applied after the walk: a `pick` is validated as an
offer (`picks.check_pick`), breaks the leg's pair and the picked leg's, types an untyped partner as a
transfer, sets a missing counter-account as the pair's and writes the pair with the keys `user`;
`reresolve` drops the stored pair. The partner's closure is part of the stored unit
(`stored.load_drafted_unit`). A `counter_leg` is validated as the offer it is (the leg unpaired, its
counter-account known, open and unsynced; its amount from the leg or from the amount received) and adds a
SYNTHETIC ROW: a new source transaction on the counter-account with its single entry, paired with the leg,
all keys `user`. Its source id is above every real one (`SYNTHETIC_SOURCE_BASE`), so the unit key stays the
stored source's, as it will after the commit.

A leg paired in one currency with a user-authored single-entry source on an unsynced account whose amount the
draft changes (a split moves the residual) makes that source FOLLOW: its amount, and its entry's, become the
negated new amount (spec §5.7, I2, I3). The follower keeps its values and keys: following is not an input.

Only the anchor's unit (after the draft) and the entries the draft lists are written; the rest of the
closure is a consequence (a partner left behind, the other side of a pair that no longer exists).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.core.matching import Leg, counter_leg_amount, leg_of, pair_all, unmatched, waiting
from app.core.plugins.classifier import (
    FIELD_ORDER,
    STANDING_PASSES,
    AccountFact,
    EntryInput,
    Field,
    Vote,
)
from app.core.resolution import Decided, Resolved, resolve
from app.core.resolution.load import UnconfirmedEntry
from app.core.resolution.snapshot import LayeredHistory
from app.core.resolution.types import USER_NO_PAYEE, is_user_no_payee
from app.core.settle.pairing import PAIR_COUNTER_KEY_VALUE, PAIR_KEY_VALUE
from app.core.settle.resolution import settle_rewrites, stored_decisions
from app.core.units.closure import UnitEntry, units_of
from app.core.units.draft import (
    DERIVED_FIELDS,
    PROPOSAL_PASSES,
    DraftEntry,
    DraftError,
    FieldDraft,
    UnitDraft,
    _Unset,
)
from app.core.units.picks import PickLeg, check_pick, window_of
from app.core.units.plan import (
    Consequence,
    FieldResult,
    Plan,
    PlannedRow,
    PlannedUnit,
    Problem,
    Split,
    Stored,
    StoredSource,
    StoredUnit,
    SuggestedSplit,
    World,
    Written,
)
from app.core.units.state import LegState, UnitState, unit_state

MAX_ROUNDS = 20
RERESOLVE = FieldDraft(mode="reresolve")
_USER: Mapping[str, Any] = {"pass": "user"}
PAIR_COUNTER_BASIS: Mapping[str, str] = {"from": "counterpart"}
SYNTHETIC_SOURCE_BASE = 2**52  # the source ids of the counter-legs a draft creates: above every real id


@dataclass(slots=True)
class _Row:
    id: int
    stored: Stored | None
    src: StoredSource
    original: bool
    draft: DraftEntry
    explicit: bool
    amount: int
    description: str | None
    note: str | None
    tag_ids: tuple[int, ...]
    account_id: int
    # the state a commit writes (S1), then what settling leaves (S2)
    type: str | None = None
    payee_id: int | None = None
    category_id: int | None = None
    counter_account_id: int | None = None
    counterpart: int | None = None
    derivation: dict[str, Any] | None = None
    evidence: dict[Field, Decided | None] | None = None
    accepted: bool = False
    # the stored state with a broken pair undone: what the draft is judged against (a commit's `stored`)
    s0: dict[Field, Decided | None] | None = None
    s0_counter: int | None = None
    s0_derivation: dict[str, Any] | None = None
    # what a commit writes, kept to tell what settling changed after it
    s1_values: dict[Field, int | str | None] | None = None
    s1_derivation: dict[str, Any] | None = None
    # a counter-leg the draft creates: the entry it is the other side of
    counter_leg_for: int | None = None

    @property
    def is_new(self) -> bool:
        return self.stored is None


# ---- small helpers ------------------------------------------------------------------------------


def _sign(n: int) -> int:
    return (n > 0) - (n < 0)


def _values(row: _Row) -> dict[Field, int | str | None]:
    return {
        "type": row.type,
        "payee": row.payee_id,
        "category": row.category_id,
        "counter_account": row.counter_account_id,
    }


def _entry_input(row: _Row) -> EntryInput:
    s = row.src
    return EntryInput(
        entry_id=row.id,
        account_id=row.account_id,
        currency=s.currency,
        booked_on=s.booked_on,
        amount=row.amount,
        user_authored=s.user_authored,
        counterparty_ref=s.counterparty_ref,
        counterparty_name=s.counterparty_name,
        purpose=s.purpose,
        booking_text=s.booking_text,
        mandate_ref=s.mandate_ref,
        instructed_currency=s.instructed_currency,
        end_to_end_id=s.end_to_end_id,
        instructed_amount=s.instructed_amount,
    )


def _as_unconfirmed(row: _Row) -> UnconfirmedEntry:
    return UnconfirmedEntry(
        input=_entry_input(row),
        type=row.type,
        payee_id=row.payee_id,
        category_id=row.category_id,
        counter_account_id=row.counter_account_id,
        derivation=row.derivation or {},
        paired=row.counterpart is not None,
        original=row.original,
        counterpart_id=row.counterpart,
    )


def _decisions(row: _Row) -> dict[Field, Decided | None]:
    """The row's values with the keys they carry (a value without a key is a user's)."""
    return dict(stored_decisions(_as_unconfirmed(row)))


def _set_base(row: _Row, *, released: bool) -> None:
    """`s0`: what the draft is judged against. For a stored entry its stored values (a pair broken by the
    draft already undone: `removal.unpair`); for a created one a flow, decided by the user (I31)."""
    if row.stored is None:
        row.s0 = {**{f: None for f in DERIVED_FIELDS}, "type": Decided("flow", "user", {})}
        row.s0_counter, row.s0_derivation = None, {"type": {"pass": "user"}}
        return
    e = row.stored
    counter, der = _release(e) if released else (e.counter_account_id, dict(e.derivation))
    row.s0_counter, row.s0_derivation = counter, der
    probe = UnconfirmedEntry(
        input=_entry_input(row),
        type=e.type,
        payee_id=e.payee_id,
        category_id=e.category_id,
        counter_account_id=counter,
        derivation=der,
        paired=False,
        original=row.original,
    )
    row.s0 = dict(stored_decisions(probe))


def _unit_entries(rows: Sequence[_Row]) -> list[UnitEntry]:
    return [
        UnitEntry(
            id=r.id,
            source_transaction_id=r.src.id,
            type=r.type,
            category_id=r.category_id,
            counterpart_entry_id=r.counterpart,
            derivation=r.derivation or {},
        )
        for r in rows
    ]


def _tags(base: tuple[int, ...], draft: DraftEntry) -> tuple[int, ...]:
    """The entry's tags with the draft's change applied, ascending."""
    return tuple(sorted((set(base) | set(draft.tags_add)) - set(draft.tags_remove)))


def _stored_entry_row(
    e: Stored, src: StoredSource, draft: DraftEntry, explicit: bool, original: bool
) -> _Row:
    return _Row(
        id=e.id,
        stored=e,
        src=src,
        original=original,
        draft=draft,
        explicit=explicit,
        amount=e.amount,
        description=e.description if isinstance(draft.description, _Unset) else draft.description,
        note=e.note if isinstance(draft.note, _Unset) else draft.note,
        tag_ids=_tags(e.tag_ids, draft),
        account_id=e.account_id,
        type=e.type,
        payee_id=e.payee_id,
        category_id=e.category_id,
        counter_account_id=e.counter_account_id,
        counterpart=e.counterpart_entry_id,
        derivation=dict(e.derivation),
    )


# ---- 1. assembling the rows ---------------------------------------------------------------------


def _assemble(stored: StoredUnit, draft: UnitDraft) -> tuple[dict[int, _Row], list[Problem]]:
    if stored.entry(draft.anchor_entry_id) is None:
        raise DraftError("unknown_entry", "the anchor is not in the unit", entry_id=draft.anchor_entry_id)
    removed = set(draft.removed_entry_ids)
    for rid in removed:
        e = stored.entry(rid)
        if e is None:
            raise DraftError("unknown_entry", "the entry is not in the unit", entry_id=rid)
        if rid == stored.original_of(e.source_transaction_id):
            raise DraftError("original_removed", "the original entry is the residual: it stays", entry_id=rid)
    rows: dict[int, _Row] = {}
    for e in stored.entries:
        if e.id in removed:
            continue
        listed = draft.entry(e.id)
        src = stored.sources[e.source_transaction_id]
        rows[e.id] = _stored_entry_row(
            e,
            src,
            listed if listed is not None else DraftEntry(e.id),
            listed is not None,
            e.id == stored.original_of(src.id),
        )
    for d in draft.entries:
        if d.is_new:
            assert d.source_entry_id is not None
            base = stored.entry(d.source_entry_id)
            if base is None:
                raise DraftError("unknown_entry", "the source entry is not in the unit", entry_id=d.id)
            src = stored.sources[base.source_transaction_id]
            origin = stored.entry(stored.original_of(src.id))
            assert origin is not None
            rows[d.id] = _Row(
                id=d.id,
                stored=None,
                src=src,
                original=False,
                draft=d,
                explicit=True,
                amount=d.amount or 0,
                description=origin.description if isinstance(d.description, _Unset) else d.description,
                note=None if isinstance(d.note, _Unset) else d.note,
                tag_ids=_tags(origin.tag_ids, d),
                account_id=src.account_id,
                type="flow",
                derivation={"type": {"pass": "user"}},
            )
        elif stored.entry(d.id) is None:
            raise DraftError("unknown_entry", "the entry is not in the unit", entry_id=d.id)
        elif d.id in removed:
            raise DraftError("removed_and_edited", "an entry is removed and edited", entry_id=d.id)
    problems = _allocate(stored, rows)
    return rows, problems


def _allocate(stored: StoredUnit, rows: dict[int, _Row]) -> list[Problem]:
    """Amounts: the original of each source is the residual of what the others hold (§5.9)."""
    problems: list[Problem] = []
    for src in stored.sources.values():
        members = [r for r in rows.values() if r.src.id == src.id]
        original = rows[stored.original_of(src.id)]
        others = [r for r in members if r is not original]
        for r in others:
            r.amount = r.draft.amount if r.draft.amount is not None else (r.stored.amount if r.stored else 0)
        original.amount = src.amount - sum(r.amount for r in others)
        if original.amount == 0:
            problems.append(Problem("residual_zero", original.id))
        elif _sign(original.amount) != _sign(src.amount):
            problems.append(Problem("residual_sign_flip", original.id, detail={"amount": original.amount}))
    return problems


# ---- 2. walking the fields ----------------------------------------------------------------------


@dataclass(slots=True)
class _Walk:
    world: World
    reresolve_all: bool

    def run(
        self, row: _Row, cur: Mapping[Field, Decided | None], *, owned: bool, rederive_ok: bool
    ) -> dict[Field, Decided | None]:
        """The row's decisions after the draft: spec §5.9 'Rederiving', with the draft's fields fixed."""
        entry = _entry_input(row)
        # a drafted payee or category makes the entry a flow, a drafted counter-account a transfer (§5.9)
        # (a payee drafted as none is the user's decision of no payee: a drafted payee all the same)
        hints: dict[Field, Decided] = {
            f: USER_NO_PAYEE if d.value is None else Decided(d.value, "user", {})
            for f in ("payee", "category", "counter_account")
            if (d := _normalised(row.draft.field(f), f)).mode == "fixed"
            and (d.value is not None or f == "payee")
        }
        implied: str | None = None
        if any(f in hints for f in ("payee", "category")):
            implied = "flow"
        elif "counter_account" in hints:
            implied = "transfer"
        fixed: dict[Field, Decided] = {}
        changed = False
        last: Resolved | None = None

        def afresh(f: Field) -> Decided | None:
            nonlocal last
            if f == "type" and hints:
                return resolve(
                    entry,
                    accounts=self.world.accounts,
                    classifiers=self.world.classifiers,
                    history=self.world.history,
                    fixed=hints,
                    exclude_entry_ids=frozenset({row.id}),
                ).get("type")
            if last is None or any(last.get(k) != d for k, d in fixed.items()):
                last = resolve(
                    entry,
                    accounts=self.world.accounts,
                    classifiers=self.world.classifiers,
                    history=self.world.history,
                    fixed=fixed,
                    exclude_entry_ids=frozenset({row.id}),
                )
            return last.get(f)

        def step(f: Field) -> Decided | None:
            nonlocal changed
            d = _normalised(row.draft.field(f), f)
            c = cur.get(f)
            new: Decided | None
            if d.mode == "fixed":
                if d.value is None:  # only the payee: 'no payee' is the user's decision (three states)
                    new = c if is_user_no_payee(c) else USER_NO_PAYEE
                elif c is not None and c.value == d.value:
                    new = c
                else:
                    new = Decided(d.value, "user", {})
            elif f == "type" and row.is_new and d.mode == "keep":
                new = c  # a created entry is a flow (I31): a pass does not decide that again
            elif f == "type" and implied is not None and d.mode == "keep" and not self.reresolve_all:
                new = c if c is not None and c.value == implied else Decided(implied, "user", {})
            elif d.mode == "reresolve" or self.reresolve_all:
                new = afresh(f)
            else:
                own = f == "counter_account" and c is not None and c.value == entry.account_id
                if owned and f in ("type", "counter_account"):
                    new = c  # the pair's, until the draft moves it
                elif is_user_no_payee(c):
                    new = c  # the user's 'no payee' stands until the user changes it (I18, I20)
                elif c is not None and c.pass_name in STANDING_PASSES and not changed and not own:
                    new = c
                elif not rederive_ok and not changed:
                    new = c  # a reviewed entry is left alone (I20) unless an earlier field changed
                else:
                    new = afresh(f)
            if (
                f == "type"
                and not row.original
                and d.mode != "fixed"
                and new is not None
                and new.value == "transfer"
                and (c is None or c.value != "transfer")
            ):
                new = c  # only a source's original may become a transfer (I31); settling leaves it as it is
            changed = changed or (new.value if new else None) != (c.value if c else None)
            if new is not None:
                fixed[f] = new
            return new

        out: dict[Field, Decided | None] = {f: None for f in DERIVED_FIELDS}
        kind = step("type")
        out["type"] = kind
        later: tuple[Field, ...] = ()
        if kind is not None:
            later = ("counter_account",) if kind.value == "transfer" else ("payee", "category")
        for f in later:
            out[f] = step(f)
        return out


def _release(e: Stored) -> tuple[int | None, dict[str, Any]]:
    """A stored entry with its pair undone (`removal._release`): counter-account value and derivation."""
    der = dict(e.derivation)
    key = der.get("counter_account")
    basis = key.get("basis") if isinstance(key, Mapping) else None
    pair_set = isinstance(basis, Mapping) and basis.get("from") == "counterpart"
    counter = e.counter_account_id
    if pair_set:
        counter = None
        der.pop("counter_account", None)
    der.pop("counterpart", None)
    return counter, der


def _normalised(d: FieldDraft, f: Field) -> FieldDraft:
    """An emptied type, category or counter-account is not a decision: the passes propose again. Only the
    payee has the decision 'no payee' (`fixed` with no value; the three states)."""
    if d.mode == "fixed" and d.value is None and f != "payee":
        return RERESOLVE
    return d


def _commit_key(
    stored_dec: Decided | None,
    stored_key: Mapping[str, Any] | None,
    final: Decided | None,
    shown: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    """The key a commit writes for a value (§5.9, D212); None for an empty field. The user's decision of no
    payee is an empty field that carries the standing key `user`."""
    if final is None:
        return None
    if is_user_no_payee(final):
        return _USER
    if stored_dec is not None and stored_dec.value == final.value and stored_dec.pass_name in STANDING_PASSES:
        return stored_key if stored_key is not None else _USER
    if shown is not None:
        return {"pass": "user", "basis": dict(shown)}
    if final.pass_name in PROPOSAL_PASSES:
        return {"pass": "user", "basis": {"pass": final.pass_name, "basis": dict(final.basis)}}
    return _USER


# ---- 4. simulating settling -----------------------------------------------------------------------


def _vote(row: _Row, rows: Mapping[int, _Row], world: World) -> Vote | None:
    if row.type not in ("flow", "transfer"):
        return None
    s = row.src
    counter = None
    if row.counterpart is not None and row.counter_account_id is not None:
        counter = next((a for a in world.accounts if a.id == row.counter_account_id), None)
    return Vote(
        entry_id=row.id,
        account_id=row.account_id,
        booked_on=s.booked_on,
        type="transfer" if row.type == "transfer" else "flow",
        payee_id=row.payee_id,
        category_id=row.category_id,
        counter_account_id=row.counter_account_id if row.counterpart is not None else None,
        counter_account_currency=counter.currency if counter else None,
        counter_account_closed_on=counter.closed_on if counter else None,
        counterparty_ref=s.counterparty_ref,
        counterparty_name=s.counterparty_name,
        purpose=s.purpose,
        booking_text=s.booking_text,
        mandate_ref=s.mandate_ref,
    )


def _leg_state(row: _Row, world: World) -> LegState | None:
    """`waiting` or `unmatched` for an unpaired transfer leg (the pure twin of the flags SQL), else None."""
    if row.type != "transfer" or row.counterpart is not None:
        return None
    leg = Leg(
        entry_id=row.id,
        account_id=row.account_id,
        currency=row.src.currency,
        amount=row.amount,
        booked_on=row.src.booked_on,
        counter_account_id=row.counter_account_id,
    )
    synced, through = world.account_sync.get(row.counter_account_id or 0, (False, None))
    window = world.matching_window
    if waiting(leg, counter_synced=synced, synced_through=through, window=window):
        return "waiting"
    if unmatched(leg, paired=False, counter_synced=synced, synced_through=through, window=window):
        return "unmatched"
    return None


def _states(rows: Sequence[_Row], world: World) -> dict[int, tuple[tuple[_Row, ...], UnitState]]:
    """Per unit key: its rows and its state (an unpaired leg's reason says whether it waits)."""
    by_id = {r.id: r for r in rows}
    out: dict[int, tuple[tuple[_Row, ...], UnitState]] = {}
    for key, unit in units_of(_unit_entries(rows)).items():
        members = tuple(by_id[e.id] for e in unit)
        leg_states = {r.id: st for r in members if (st := _leg_state(r, world)) is not None}
        out[key] = (members, unit_state(list(unit), leg_states))
    return out


def _with_matching_flags(flags: tuple[str, ...], row: _Row, world: World) -> tuple[str, ...]:
    """`waiting` or `unmatched_transfer` for an unpaired transfer leg, among the unit's flags."""
    state = _leg_state(row, world)
    if state is None:
        return flags
    return tuple(sorted((*flags, "waiting" if state == "waiting" else "unmatched_transfer")))


def _pair(rows: Sequence[_Row], world: World) -> set[int]:
    """Settling's step 4 (the same pure `pair_all`) over the plan's unpaired transfer legs and every other
    unpaired transfer leg of the ledger (`world.ledger_legs`), in place on `rows`.

    A pair of two rows is made. A pair of a row with a leg outside the plan is not (there is no row to
    hold it): the leg's id is returned, so the preview can bring its unit in and plan again. A pair between
    two legs outside the plan is none of the plan's business.
    """
    legs = [
        leg_of(_entry_input(r), type=r.type, counter_account_id=r.counter_account_id)
        for r in rows
        if r.type == "transfer" and r.counterpart is None
    ]
    by_id = {r.id: r for r in rows}
    if not legs or (len(legs) < 2 and not world.ledger_legs):
        return set()
    outside = [leg for leg in world.ledger_legs if leg.entry_id not in by_id]
    pulled: set[int] = set()
    for p in pair_all([*legs, *outside], world.matching_window, {a.id: a for a in world.accounts}):
        a, b = by_id.get(p.leg_id), by_id.get(p.partner_id)
        if a is None and b is None:
            continue
        if a is None or b is None:
            pulled.add(p.leg_id if a is None else p.partner_id)
            continue
        for entry_id, partner_id, counter in (
            (p.leg_id, p.partner_id, p.leg_counter_account),
            (p.partner_id, p.leg_id, p.partner_counter_account),
        ):
            r = by_id[entry_id]
            r.counterpart = partner_id
            derivation = dict(r.derivation or {})
            derivation["counterpart"] = dict(PAIR_KEY_VALUE)
            if counter is not None:
                r.counter_account_id = counter
                derivation["counter_account"] = dict(PAIR_COUNTER_KEY_VALUE)
            r.derivation = derivation
    return pulled


def _settle(rows: Sequence[_Row], world: World, documented: frozenset[int]) -> set[int]:
    """Settling's rounds over the plan's units (step 1, the pairing of step 4 and the teaching of step 5),
    in place on `rows`; returns the legs outside the plan that pairing took a row to (`_pair`).

    A unit that is confirmed teaches history before the first round (the snapshot a settle loads holds the
    committed state) and after each round that confirms it; a source with a document votes nothing. Step 1
    is `settle_rewrites`, the function settling calls: a paired leg of an unconfirmed unit is rederived too,
    and its pair falls on both legs when its type or its own counter-account changes (I18).
    """
    by_id = {r.id: r for r in rows}
    taught: set[int] = set()
    pulled: set[int] = set()
    for _ in range(MAX_ROUNDS):
        states = _states(rows, world)
        for k, (members, st) in states.items():
            if st.confirmed and k not in taught:
                taught.add(k)
                world.history.add(
                    v
                    for r in members
                    if r.src.id not in documented and (v := _vote(r, by_id, world)) is not None
                )
        pending = [r for _k, (members, st) in states.items() if not st.confirmed for r in members]
        rewrites = settle_rewrites(
            [_as_unconfirmed(r) for r in pending],
            reach=lambda _row: True,
            accounts=world.accounts,
            classifiers=world.classifiers,
            history=world.history,
        )
        for entry_id, rw in rewrites.items():
            r = by_id[entry_id]
            r.type, r.payee_id, r.category_id = rw.type, rw.payee_id, rw.category_id
            r.counter_account_id, r.derivation = rw.counter_account_id, rw.derivation
            if rw.unpair:
                r.counterpart = None
        pulled |= _pair(rows, world)
        if all(k in taught or not st.confirmed for k, (_m, st) in _states(rows, world).items()):
            return pulled
    raise RuntimeError("the preview of settling did not converge")


# ---- pairing: picks and re-resolving ---------------------------------------------------------------


@dataclass(slots=True)
class _Picks:
    """The valid picks of a draft: (leg, partner, is_proposal), and the legs whose own pair they break."""

    pairs: list[tuple[int, int, bool]]
    broken: set[int]
    counter_legs: list[_Row] = dataclasses.field(default_factory=list)  # the synthetic rows, in draft order

    def partners(self) -> dict[int, int]:
        out: dict[int, int] = {}
        for leg, partner, _p in self.pairs:
            out[leg], out[partner] = partner, leg
        return out


def _own_counter(dec: Decided | None) -> int | None:
    """The counter-account a leg had before: a pair's own (basis `{"from": "counterpart"}`) goes with it."""
    if dec is None or not isinstance(dec.value, int) or dec.basis.get("from") == "counterpart":
        return None
    return dec.value


def _apply_pairing(
    stored: StoredUnit,
    draft: UnitDraft,
    rows: Mapping[int, _Row],
    first: Mapping[int, Mapping[Field, Decided | None]],
    links: dict[int, int | None],
    world: World,
    problems: list[Problem],
) -> _Picks:
    """The draft's `pairing` fields over `links` (the pairs that stand), in place. A pick that is not an offer
    is a problem and changes nothing; a no-op pick (the leg's current partner) neither."""
    out = _Picks([], set())
    groups = units_of(
        UnitEntry(e.id, e.source_transaction_id, e.type, e.category_id, e.counterpart_entry_id, e.derivation)
        for e in stored.entries
    )
    unit_of = {ue.id: frozenset(ue2.id for ue2 in unit) for unit in groups.values() for ue in unit}
    accounts = {a.id: a for a in world.accounts}
    window = window_of(draft.window_days, world.matching_window)
    used: set[int] = set()
    for d in draft.entries:
        if d.pairing.mode == "keep":
            continue
        r = rows.get(d.id)
        kind = first[d.id]["type"] if r is not None else None
        if r is None or r.stored is None or kind is None or kind.value != "transfer":
            raise DraftError(
                "pairing_not_transfer", "only a transfer leg has a partner", entry_id=d.id, field="pairing"
            )
        s = r.stored
        if d.pairing.mode == "reresolve":
            old = s.counterpart_entry_id
            # only a pair that still stands is dropped: a leg a pick has just paired elsewhere is left alone
            if old is not None and links.get(r.id) == old:
                links[r.id] = None
                if links.get(old) == r.id:
                    links[old] = None
            continue
        if d.pairing.mode == "counter_leg":
            # a proposal is not the user's choice: one the plan cannot make (the draft moved the leg since
            # the preview proposed it) is dropped, never a problem that refuses the commit
            found: list[Problem] = []
            row = _counter_leg_row(d, r, first, links, used, accounts, world, found, len(out.counter_legs))
            if not d.pairing.is_proposal:
                problems.extend(found)
            if row is not None:
                out.counter_legs.append(row)
                links[r.id], links[row.id] = row.id, r.id
                used.add(r.id)
                out.pairs.append((r.id, row.id, d.pairing.is_proposal))
            continue
        partner_id = d.pairing.partner_entry_id
        assert partner_id is not None
        if s.counterpart_entry_id == partner_id:
            continue  # the leg's own partner again: nothing to do
        partner = rows.get(partner_id)
        leg = PickLeg(
            id=r.id,
            account_id=r.account_id,
            amount=r.amount,
            currency=r.src.currency,
            booked_on=r.src.booked_on,
            counter_account_id=_own_counter(first[r.id]["counter_account"]),
            instructed_currency=r.src.instructed_currency,
        )
        refused = check_pick(leg, partner_id, stored, unit_of.get(r.id, frozenset({r.id})), accounts, window)
        if refused is None and (partner is None or partner.stored is None or {r.id, partner_id} & used):
            refused = Problem("partner_not_offered", r.id, "pairing", {"partner": partner_id})
        if refused is not None:
            problems.append(refused)
            continue
        assert partner is not None and partner.stored is not None
        former = {x for x in (s.counterpart_entry_id, partner.stored.counterpart_entry_id) if x is not None}
        for x in former:
            if x in links:
                links[x] = None
        links[r.id], links[partner_id] = partner_id, r.id
        if s.counterpart_entry_id is not None:
            out.broken.add(r.id)
        if partner.stored.counterpart_entry_id is not None:
            out.broken.add(partner_id)
        used |= {r.id, partner_id, *former}
        out.pairs.append((r.id, partner_id, d.pairing.is_proposal))
        for a, b in ((r, partner), (partner, r)):
            acc = accounts.get(b.account_id)
            wanted = a.src.instructed_currency
            if wanted is not None and acc is not None and acc.currency != wanted:
                problems.append(
                    Problem(
                        "currency_rule",
                        a.id,
                        "counter_account",
                        {"required": wanted, "actual": acc.currency},
                    )
                )
    return out


def _counter_leg_row(
    d: DraftEntry,
    leg: _Row,
    first: Mapping[int, Mapping[Field, Decided | None]],
    links: Mapping[int, int | None],
    used: set[int],
    accounts: Mapping[int, AccountFact],
    world: World,
    problems: list[Problem],
    index: int,
) -> _Row | None:
    """The synthetic row of a counter-leg (spec §5.7), or None with the problem that refuses it.

    The leg must be a stored transfer without a partner (once the draft's own changes are applied), whose
    counter-account is known, exists, is open on the leg's date and is unsynced (I40), and takes the leg's
    instructed currency (I11). Its amount is `counter_leg_amount`, or the user's amount received."""
    spec = d.pairing.counter_leg
    assert spec is not None
    c = _own_counter(first[leg.id]["counter_account"])
    acc = accounts.get(c) if c is not None else None
    not_offered = Problem("counter_leg_not_offered", leg.id, "pairing", {"account": c})
    if (
        links.get(leg.id) is not None
        or leg.id in used
        or c is None
        or c == leg.account_id
        or acc is None
        or (acc.closed_on is not None and leg.src.booked_on > acc.closed_on)
        or (leg.src.instructed_currency is not None and acc.currency != leg.src.instructed_currency)
    ):
        problems.append(not_offered)
        return None
    if world.account_sync.get(c, (True, None))[0]:
        problems.append(Problem("counter_leg_account_synced", leg.id, "pairing", {"account": c}))
        return None
    amount = counter_leg_amount(leg_of(_entry_input(leg), type="transfer", counter_account_id=c), acc)
    detail: dict[str, int | str | None] = {"account": c, "currency": acc.currency}
    if amount is None:
        if spec.received_amount is None:
            problems.append(Problem("received_amount_required", leg.id, "pairing", detail))
            return None
        amount = -_sign(leg.amount) * spec.received_amount
    elif spec.received_amount is not None:
        problems.append(Problem("received_amount_not_needed", leg.id, "pairing", detail))
        return None
    src = StoredSource(
        id=SYNTHETIC_SOURCE_BASE + index + 1,
        amount=amount,
        account_id=c,
        currency=acc.currency,
        booked_on=leg.src.booked_on,
        value_on=None,
        user_authored=True,
        purpose=leg.src.purpose,
    )
    return _Row(
        id=spec.temp_id,
        stored=None,
        src=src,
        original=True,
        # a placeholder: the row is not walked, and nothing reads a draft of it
        draft=DraftEntry(spec.temp_id, amount=amount, source_entry_id=leg.id),
        explicit=True,
        amount=amount,
        description=None,
        note=None,
        tag_ids=(),
        account_id=c,
        type="transfer",
        counter_account_id=leg.account_id,
        counterpart=leg.id,
        derivation={
            "type": dict(_USER),
            "counter_account": {"pass": "user", "basis": dict(PAIR_COUNTER_BASIS)},
            "counterpart": {"pass": "user", "basis": {}},
        },
        accepted=True,
        counter_leg_for=leg.id,
    )


def _pick_decisions(
    dec: Mapping[Field, Decided | None], other_account: int
) -> tuple[dict[Field, Decided | None], bool]:
    """A leg's decisions once it is picked: a transfer (an untyped partner is typed by the user), no payee or
    category, and the partner's account as counter-account where the leg had none of its own (the second
    value: the pair set it, spec §5.7)."""
    out = dict(dec)
    kind = out["type"]
    if kind is None or kind.value != "transfer":
        out["type"] = Decided("transfer", "user", {})
    out["payee"], out["category"] = None, None
    counter = out["counter_account"]
    set_by_pair = counter is None or counter.value != other_account
    if set_by_pair:
        out["counter_account"] = Decided(other_account, "user", dict(PAIR_COUNTER_BASIS))
    return out, set_by_pair


def _pick_keys(row: _Row, set_by_pair: bool) -> None:
    """The keys of a pick (spec §5.7 "Keys on pairs"): the pair is the user's on both legs, and a
    counter-account the pair set says so."""
    derivation = dict(row.derivation or {})
    derivation["counterpart"] = {"pass": "user", "basis": {}}
    if set_by_pair:
        derivation["counter_account"] = {"pass": "user", "basis": dict(PAIR_COUNTER_BASIS)}
    row.derivation = derivation


# ---- 5. the invariants --------------------------------------------------------------------------


def _problems(rows: Sequence[_Row], world: World) -> list[Problem]:
    out: list[Problem] = []
    accounts = {a.id: a for a in world.accounts}
    by_id = {r.id: r for r in rows}
    transfers: dict[int, list[_Row]] = {}
    for r in rows:
        if r.type == "transfer":
            transfers.setdefault(r.src.id, []).append(r)
            if r.is_new and r.counter_leg_for is None:
                out.append(Problem("new_entry_not_flow", r.id, "type"))
        if (r.category_id is not None or r.payee_id is not None) and r.type != "flow":
            out.append(Problem("type_conflict", r.id, "category" if r.category_id is not None else "payee"))
        if (r.counter_account_id is not None or r.counterpart is not None) and r.type != "transfer":
            out.append(Problem("type_conflict", r.id, "counter_account"))
        d = r.draft.counter_account
        if d.mode == "fixed" and d.value == r.account_id:
            out.append(Problem("own_counter_account", r.id, "counter_account"))
        if r.counter_account_id is not None and r.type == "transfer" and r.counterpart is None:
            acc = accounts.get(r.counter_account_id)
            if acc is None:
                out.append(
                    Problem("stale_reference", r.id, "counter_account_id", {"id": r.counter_account_id})
                )
            elif r.src.instructed_currency is not None and acc.currency != r.src.instructed_currency:
                out.append(
                    Problem(
                        "currency_rule",
                        r.id,
                        "counter_account",
                        {"required": r.src.instructed_currency, "actual": acc.currency},
                    )
                )
        if (
            r.category_id is not None
            and r.draft.category.mode == "fixed"
            and r.draft.category.value is not None
            and r.category_id not in world.categories
        ):
            out.append(Problem("stale_reference", r.id, "category_id", {"id": r.category_id}))
        if (
            r.accepted
            and r.payee_id is None
            and isinstance(r.derivation, Mapping)
            and "payee" in r.derivation
            and r.type != "flow"
        ):
            out.append(Problem("type_conflict", r.id, "payee"))  # the user's 'no payee' is for flows (I9)
        if r.payee_id is not None and r.draft.payee.mode == "fixed" and r.payee_id not in world.payees:
            out.append(Problem("stale_reference", r.id, "payee_id", {"id": r.payee_id}))
    for src_id, legs in sorted(transfers.items()):
        for extra in sorted(legs, key=lambda x: x.id)[1:]:
            out.append(Problem("second_transfer", extra.id, "type", {"source": src_id}))
    seen: set[int] = set()
    for r in rows:
        if r.counterpart is None or r.id in seen or r.counterpart not in by_id:
            continue
        o = by_id[r.counterpart]
        seen.update((r.id, o.id))
        if _sign(o.amount) == _sign(r.amount):
            out.append(Problem("pair_sign", r.id, detail={"partner": o.id}))
        elif o.src.currency == r.src.currency and o.amount != -r.amount:
            larger = r if abs(r.amount) > abs(o.amount) else o
            out.append(
                Problem(
                    "pair_unequal",
                    r.id,
                    detail={"partner": o.id, "difference": r.amount + o.amount},
                    suggested_split=SuggestedSplit(
                        larger.id, larger.amount + (o if larger is r else r).amount
                    ),
                )
            )
    by_source: dict[int, int] = {}
    for r in rows:
        by_source[r.src.id] = by_source.get(r.src.id, 0) + r.amount
    for src_id, total in by_source.items():
        src = next(r.src for r in rows if r.src.id == src_id)
        if total != src.amount:
            out.append(
                Problem("split_sum", None, detail={"source": src_id, "difference": total - src.amount})
            )
    return out


# ---- following the partner ----------------------------------------------------------------------


def _follow(rows: Mapping[int, _Row], links: Mapping[int, int | None], world: World) -> dict[int, int]:
    """A counter-leg follows its partner (spec §5.7): where the draft changes the amount of a leg whose
    stored pair stands, in one currency, with a user-authored source that is the only entry of its source, on
    an unsynced account, that source's amount and its entry's become the negated new amount, in place on
    the follower's row. Returns source id -> its new amount. The follower keeps its values and keys."""
    out: dict[int, int] = {}
    for r in list(rows.values()):
        s = r.stored
        if s is None or s.counterpart_entry_id is None or r.amount == s.amount:
            continue
        if links.get(r.id) != s.counterpart_entry_id:
            continue  # the pair does not stand: nothing follows
        p = rows.get(s.counterpart_entry_id)
        if (
            p is None
            or p.stored is None
            or not p.src.user_authored
            or p.src.currency != r.src.currency
            or sum(1 for x in rows.values() if x.src.id == p.src.id) != 1
            or world.account_sync.get(p.account_id, (True, None))[0]
        ):
            continue
        follower = -r.amount
        if _sign(follower) != _sign(p.stored.amount):
            continue  # a sign flip is a different movement: the pair breaks, as an edit of it does
        p.amount = follower
        p.src = dataclasses.replace(p.src, amount=follower)
        out[p.src.id] = follower
    return out


# ---- the plan -----------------------------------------------------------------------------------


def _stored_confirmed(stored: StoredUnit) -> dict[int, bool]:
    """Per stored entry: whether its unit was reviewed before the draft (left alone if so, I20)."""
    out: dict[int, bool] = {}
    entries = (
        UnitEntry(e.id, e.source_transaction_id, e.type, e.category_id, e.counterpart_entry_id, e.derivation)
        for e in stored.entries
    )
    for unit in units_of(entries).values():
        confirmed = unit_state(list(unit)).confirmed
        for ue in unit:
            out[ue.id] = confirmed
    return out


def _pairs_that_stand(
    ordered: Sequence[_Row], rows: Mapping[int, _Row], first: Mapping[int, Mapping[Field, Decided | None]]
) -> dict[int, int | None]:
    """The counterpart of each row once the draft is applied: a pair stands while both legs are still
    transfers, each on the other's account (I10); a removed, retyped or redirected leg breaks it."""
    links: dict[int, int | None] = {r.id: None for r in ordered}
    for r in ordered:
        p = r.stored.counterpart_entry_id if r.stored else None
        if p is None or p not in rows or r.id > p:
            continue
        o = rows[p]
        a, b = first[r.id], first[o.id]
        ta, tb, ca, cb = a["type"], b["type"], a["counter_account"], b["counter_account"]
        if (
            ta is not None
            and tb is not None
            and ca is not None
            and cb is not None
            and ta.value == "transfer"
            and tb.value == "transfer"
            and ca.value == o.account_id
            and cb.value == r.account_id
        ):
            links[r.id], links[o.id] = o.id, r.id
    return links


def _write_stored(r: _Row) -> None:
    """A row the draft does not write: its stored values, a pair undone where the draft broke it."""
    assert r.stored is not None and r.s0_derivation is not None
    e = r.stored
    r.type, r.payee_id, r.category_id = e.type, e.payee_id, e.category_id
    r.counter_account_id, r.derivation = r.s0_counter, dict(r.s0_derivation)


def _write_accepted(r: _Row, decisions: Mapping[Field, Decided | None]) -> None:
    """The row as a commit writes it: the decided values, each with the key the commit derives for it."""
    assert r.s0 is not None and r.s0_derivation is not None
    derivation = {k: v for k, v in r.s0_derivation.items() if k not in FIELD_ORDER}
    for f in DERIVED_FIELDS:
        shown = r.draft.field(f).shown_basis
        key = _commit_key(
            r.s0.get(f),
            r.s0_derivation.get(f),
            decisions[f],
            None if shown is None else {"pass": shown.pass_name, "basis": dict(shown.basis)},
        )
        if key is not None:
            derivation[f] = key

    def value(f: Field) -> Any:
        d = decisions[f]
        return None if d is None else d.value

    r.type = None if decisions["type"] is None else str(decisions["type"].value)
    r.payee_id, r.category_id, r.counter_account_id = (
        None if is_user_no_payee(decisions["payee"]) else value("payee"),
        value("category"),
        value("counter_account"),
    )
    r.derivation = derivation
    r.evidence = dict(decisions)


def _field_results(r: _Row) -> dict[Field, FieldResult]:
    after = _decisions(r)
    values = _values(r)
    stored_values = (
        {"type": None, "payee": None, "category": None, "counter_account": None}
        if r.stored is None
        else {
            "type": r.stored.type,
            "payee": r.stored.payee_id,
            "category": r.stored.category_id,
            "counter_account": r.stored.counter_account_id,
        }
    )
    out: dict[Field, FieldResult] = {}
    der = r.derivation or {}
    for f in DERIVED_FIELDS:
        value = values[f]
        # the evidence the walk gave, unless settling rewrote this field after the commit
        untouched = (
            r.evidence is not None
            and r.s1_values is not None
            and r.s1_derivation is not None
            and r.s1_values[f] == value
            and r.s1_derivation.get(f) == der.get(f)
        )
        evidence = (r.evidence or {}).get(f) if untouched else after.get(f)
        # an empty payee that carries the user's key is a decision, shown like a value
        shown = value is not None or is_user_no_payee(evidence)
        out[f] = FieldResult(
            value=value,
            evidence=evidence if shown else None,
            key=der.get(f) if shown else None,
            stored_value=stored_values[f],
            stored_key=r.stored.derivation.get(f) if r.stored else None,
        )
    return out


def plan_unit(stored: StoredUnit, draft: UnitDraft, world: World) -> Plan:
    """Lay `draft` over `stored` (module docstring). Raises `DraftError` for a draft that is nonsense."""
    # the plan teaches history what its units confirm: into a layer of its own, so the world is left as it was
    world = dataclasses.replace(world, history=LayeredHistory(world.history))
    rows, problems = _assemble(stored, draft)
    ordered = [*(rows[e.id] for e in stored.entries if e.id in rows), *(r for r in rows.values() if r.is_new)]
    walk = _Walk(world, draft.reresolve_all)
    stored_confirmed = _stored_confirmed(stored)
    documented = frozenset(e.source_transaction_id for e in stored.entries if e.document_id is not None)

    # phase 1: every entry walked, a paired leg's type and counter-account left to its pair
    first: dict[int, dict[Field, Decided | None]] = {}
    for r in ordered:
        _set_base(r, released=False)
        assert r.s0 is not None
        owned = r.stored is not None and r.stored.counterpart_entry_id in rows
        first[r.id] = walk.run(
            r, r.s0, owned=owned, rederive_ok=r.is_new or not stored_confirmed.get(r.id, False)
        )
    links = _pairs_that_stand(ordered, rows, first)
    picks = _apply_pairing(stored, draft, rows, first, links, world, problems)
    for row in picks.counter_legs:  # the synthetic rows: after the stored ones, in draft order
        rows[row.id] = row
        ordered.append(row)
    picked = picks.partners()
    followed = _follow(rows, links, world)
    unpaired = sorted(
        e.id for e in stored.entries if e.counterpart_entry_id is not None and links.get(e.id) is None
    )
    released = set(unpaired) | picks.broken
    for r in ordered:
        r.counterpart = links[r.id]
        if r.id in released:
            _set_base(r, released=True)

    # the draft's entries: the anchor's unit once the draft is applied, and every source the draft lists
    members: set[int] = set()
    for unit in units_of(_unit_entries(ordered)).values():
        if any(ue.id == draft.anchor_entry_id for ue in unit):
            members = {ue.id for ue in unit}
    # a source the draft splits or lists is committed whole: the residual's new amount is part of it
    touched = {r.src.id for r in ordered if r.explicit}
    touched |= {e.source_transaction_id for e in stored.entries if e.id in set(draft.removed_entry_ids)}
    touched |= set(followed)
    for r in ordered:
        if r.counter_leg_for is not None:
            continue  # a counter-leg is made whole: decided by the user, every key standing
        r.accepted = r.id in members or r.src.id in touched
        if not r.accepted:
            _write_stored(r)
            continue
        assert r.s0 is not None
        decisions = first[r.id]
        if r.id in released:  # a leg left free by its pair is judged as a free entry
            decisions = walk.run(r, r.s0, owned=False, rederive_ok=not stored_confirmed.get(r.id, False))
        if r.id in picked:
            decisions, set_by_pair = _pick_decisions(decisions, rows[picked[r.id]].account_id)
            _write_accepted(r, decisions)
            _pick_keys(r, set_by_pair)
        else:
            _write_accepted(r, decisions)

    problems.extend(_problems(ordered, world))
    written = {
        r.id: Written(
            type=r.type,
            payee_id=r.payee_id,
            category_id=r.category_id,
            counter_account_id=r.counter_account_id,
            counterpart_entry_id=r.counterpart,
            amount=r.amount,
            description=r.description,
            note=r.note,
            derivation=dict(r.derivation or {}),
            accepted=r.accepted,
        )
        for r in ordered
    }
    for r in ordered:
        r.s1_values, r.s1_derivation = dict(_values(r)), dict(r.derivation or {})

    # what settling leaves of it
    pulled = _settle(ordered, world, documented)
    final_states = _states(ordered, world)
    unit_of = {ur.id: key for key, (unit_rows, _st) in final_states.items() for ur in unit_rows}
    anchor_key = unit_of[draft.anchor_entry_id]

    planned = tuple(
        PlannedRow(
            id=r.id,
            version=r.stored.version if r.stored else None,
            stored=r.stored,
            source_transaction_id=r.src.id,
            unit_key=unit_of[r.id],
            in_unit=unit_of[r.id] == anchor_key,
            account_id=r.account_id,
            currency=r.src.currency,
            booked_on=r.src.booked_on,
            value_on=r.src.value_on,
            amount=r.amount,
            description=r.description,
            note=r.note,
            tag_ids=r.tag_ids,
            counterpart_entry_id=r.counterpart,
            fields=_field_results(r),
            derivation=dict(r.derivation or {}),
            flags=_with_matching_flags(final_states[unit_of[r.id]][1].flags[r.id], r, world),
            written=written[r.id],
            original=r.original,
            leg=leg_of(_entry_input(r), type=r.type, counter_account_id=r.counter_account_id),
            purpose=r.src.purpose,
            counter_leg_for=r.counter_leg_for,
        )
        for r in ordered
    )
    draft_order = {r.id: i for i, r in enumerate(ordered)}
    units = tuple(
        PlannedUnit(
            anchor_entry_id=min(ur.id for ur in unit_rows if ur.id > 0),
            unit_key=key,
            entry_ids=(
                *sorted(ur.id for ur in unit_rows if ur.id > 0),
                *sorted((ur.id for ur in unit_rows if ur.id < 0), key=draft_order.__getitem__),
            ),
            state=st,
        )
        for key, (unit_rows, st) in sorted(final_states.items())
    )
    now = {r.src.id: r.src for r in ordered}  # a source that follows its partner has its new amount
    splits = tuple(
        Split(
            source_transaction_id=src.id,
            source_amount=now[src.id].amount,
            residual_entry_id=stored.original_of(src.id),
            residual_amount=rows[stored.original_of(src.id)].amount,
            entry_ids=tuple(r.id for r in ordered if r.src.id == src.id),
        )
        for src in stored.sources.values()
    )
    return Plan(
        rows=planned,
        removed=tuple(e for e in stored.entries if e.id in set(draft.removed_entry_ids)),
        unpaired_entry_ids=tuple(unpaired),
        units=units,
        anchor_unit=next(u for u in units if u.unit_key == anchor_key),
        splits=splits,
        problems=tuple(problems),
        consequences=tuple(
            _consequences(stored, ordered, unpaired, anchor_key, stored_confirmed, final_states, unit_of)
        ),
        versions={e.id: e.version for e in stored.entries},
        created_ids=tuple(r.id for r in ordered if r.is_new),
        pulled_entry_ids=tuple(sorted(pulled)),
        followed_sources=followed,
    )


def _consequences(
    stored: StoredUnit,
    ordered: Sequence[_Row],
    unpaired: Sequence[int],
    anchor_key: int,
    stored_confirmed: Mapping[int, bool],
    final_states: Mapping[int, tuple[tuple[_Row, ...], UnitState]],
    unit_of: Mapping[int, int],
) -> list[Consequence]:
    """What the draft does beyond the values the user typed: rows made, removed, changed, freed, returned."""
    out: list[Consequence] = []
    kept = {r.id for r in ordered}
    out.extend(Consequence(e.id, "deleted") for e in stored.entries if e.id not in kept)
    for r in ordered:
        s = r.stored
        if s is None:
            out.append(Consequence(r.id, "created"))
            continue
        if r.id in unpaired:
            out.append(Consequence(r.id, "unpaired" if unit_of[r.id] == anchor_key else "left_behind"))
        before = (s.type, s.payee_id, s.category_id, s.counter_account_id, s.amount, s.description, s.note)
        after = (r.type, r.payee_id, r.category_id, r.counter_account_id, r.amount, r.description, r.note)
        if before != after or s.counterpart_entry_id != r.counterpart:
            out.append(Consequence(r.id, "changed"))
        if stored_confirmed.get(r.id, False) and not final_states[unit_of[r.id]][1].confirmed:
            out.append(Consequence(r.id, "returns_to_review"))
    return out
