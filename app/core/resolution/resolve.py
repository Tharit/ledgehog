"""Resolution, the orchestration of spec §5.9 (architecture §5.1, §5.4): pure, writes nothing.

Fields are decided in the order of "Field order": the type first, by pass 0 and then each
classifier in authority order, then the fields the type allows: a transfer's counter-account, a
flow's payee and category. The first pass with a value for a field wins; the type carries the key
of the pass that decided it. A field in `fixed` (the review draft, standing values kept by
`rederive`) is decided and the others resolve around it. Nothing here contradicts I9: a transfer
has no payee or category, a flow no counter-account, and the entry's own account is never one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Literal

from app.core.plugins.classifier import (
    EMPTY,
    MAY_BE_EMPTY,
    AccountFact,
    Classifier,
    ClassifierContext,
    EntryInput,
    Field,
    HistorySource,
    Proposal,
)
from app.core.resolution.accounts import counter_account_ok
from app.core.resolution.pass0 import own_account_index, pass0
from app.core.resolution.types import Decided, Resolved, is_decided_empty

__all__ = ["Decided", "Resolved", "resolve"]

_TYPES = ("flow", "transfer")
_FLOW_FIELDS: tuple[Literal["payee", "category"], ...] = ("payee", "category")


def _is_id(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(slots=True)
class _Run:
    entry: EntryInput
    accounts: Mapping[int, AccountFact]
    classifiers: Sequence[Classifier]
    history: HistorySource | None
    exclude_entry_ids: frozenset[int]
    fixed: Mapping[Field, Decided]
    decided: dict[Field, Decided]
    stored: Mapping[Field, Decided | None]
    # the explained absences (a proposal with no value) met while looking for a type, by field: when no
    # pass decides a type, nothing proposes a value either, but an absence still stands
    explained: dict[Field, Decided] = dataclass_field(default_factory=dict)

    def ctx(self) -> ClassifierContext:
        return ClassifierContext(
            stored=self.stored,
            resolved={f: Proposal(f, d.value, d.basis) for f, d in self.decided.items()},
            account_ok=self.account_ok,
            history=self.history,
            exclude_entry_ids=self.exclude_entry_ids,
        )

    def account_ok(self, account_id: int) -> bool:
        account = self.accounts.get(account_id)
        return account is not None and counter_account_ok(self.entry, account)

    def ask(self, c: Classifier, field: Field) -> Proposal | None:
        p = c.propose(field, self.entry, self.ctx())
        if p is None:
            return None
        if p.field != field:
            raise ValueError(f"{c.pass_name} proposed {p.field} when asked for {field}")
        if field == "type":
            ok = p.value in _TYPES
        else:
            ok = (
                _is_id(p.value)
                or (field in MAY_BE_EMPTY and p.value == EMPTY)  # an empty result
                # an explained absence, on a field that may not be empty (where empty is a result instead)
                or (p.value is None and field in _FLOW_FIELDS and field not in MAY_BE_EMPTY)
            )
        if not ok:
            raise ValueError(f"{c.pass_name} proposed {p.value!r} for {field}")
        return p

    @staticmethod
    def decision(c: Classifier, p: Proposal) -> Decided:
        """A proposal as a decision: its key carries `"none": true` when it has no value (the key that
        explains an absence, whatever the classifier put in its basis)."""
        basis = dict(p.basis)
        if p.value is None:
            basis["none"] = True
        return Decided(p.value, c.pass_name, basis)

    def counter_proposal(self, c: Classifier) -> Proposal | None:
        """A counter-account proposal that passes core's tests, else None (dropped)."""
        p = self.ask(c, "counter_account")
        if p is None or not isinstance(p.value, int) or not self.account_ok(p.value):
            return None
        return p

    def own_account(self) -> tuple[Decided, Decided] | None:
        return pass0(self.entry, own_account_index(self.accounts.values()))

    def type_(self) -> Decided | None:
        if (d := self.fixed.get("type")) is not None:
            return d if d.value in _TYPES else None
        for field in ("payee", "category", "counter_account"):
            if (
                (f := self.fixed.get(field)) is not None
                and (f.value is not None or is_decided_empty(f))  # an explained absence implies no type
                and not (field == "counter_account" and f.value == self.entry.account_id)
            ):
                kind = "transfer" if field == "counter_account" else "flow"
                return Decided(kind, f.pass_name, f.basis)
        if (p0 := self.own_account()) is not None:
            return p0[0]
        for c in self.classifiers:
            p = self.ask(c, "type")
            if p is not None:
                return Decided(str(p.value), c.pass_name, p.basis)
            # a pass that proposes a counter-account proposes a transfer, a payee or category a flow
            if (p := self.counter_proposal(c)) is not None:
                return Decided("transfer", c.pass_name, p.basis)
            for field in _FLOW_FIELDS:
                p = self.ask(c, field)
                if p is None or p.value == EMPTY:  # an empty result decides no type
                    continue
                if p.value is None:  # an absence implies no type
                    self.explained.setdefault(field, self.decision(c, p))
                    continue
                return Decided("flow", c.pass_name, p.basis)
        return None

    def counter_account(self) -> Decided | None:
        if (d := self.fixed.get("counter_account")) is not None:
            if d.value != self.entry.account_id:
                return d
        if (p0 := self.own_account()) is not None:
            return p0[1]
        for c in self.classifiers:
            if (p := self.counter_proposal(c)) is not None:
                return Decided(p.value, c.pass_name, p.basis)
        return None

    def first_proposal(self, field: Literal["payee", "category"]) -> Decided | None:
        if (d := self.fixed.get(field)) is not None:
            return d
        for c in self.classifiers:
            p = self.ask(c, field)
            if p is None:
                continue
            if p.value == EMPTY:  # an empty result wins like a value, ends the search, stores nothing
                return None
            return self.decision(c, p)
        return None

    def run(self) -> Resolved:
        kind = self.type_()
        if kind is None:
            return Resolved(self.explained)
        self.decided["type"] = kind
        if kind.value == "transfer":
            if (d := self.counter_account()) is not None:
                self.decided["counter_account"] = d
        else:
            for field in _FLOW_FIELDS:
                if (d := self.first_proposal(field)) is not None:
                    self.decided[field] = d
        return Resolved(self.decided)


def resolve(
    entry: EntryInput,
    *,
    accounts: Sequence[AccountFact],
    classifiers: Sequence[Classifier],
    history: HistorySource | None = None,
    fixed: Mapping[Field, Decided] | None = None,
    exclude_entry_ids: frozenset[int] = frozenset(),
    stored: Mapping[Field, Decided | None] | None = None,
) -> Resolved:
    """What the passes decide for `entry`, around the `fixed` fields; `classifiers` by authority.

    `stored` is what the entry carries now: the model's answer, its `llm` key, is read from it.

    A fixed later field without a fixed type implies the type (payee or category a flow,
    counter-account a transfer), keyed as that field. Fixed fields the type does not allow are
    left out. Classifier errors propagate.
    """
    return _Run(
        entry=entry,
        accounts={a.id: a for a in accounts},
        classifiers=classifiers,
        history=history,
        exclude_entry_ids=exclude_entry_ids,
        fixed=fixed or {},
        decided={},
        stored=stored or {},
    ).run()
