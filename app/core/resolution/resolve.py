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
from typing import Literal

from app.core.plugins.classifier import (
    NO_PAYEE,
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
from app.core.resolution.types import Decided, Resolved

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

    def ctx(self) -> ClassifierContext:
        return ClassifierContext(
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
            ok = _is_id(p.value) or (field == "payee" and p.value == NO_PAYEE)
        if not ok:
            raise ValueError(f"{c.pass_name} proposed {p.value!r} for {field}")
        return p

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
            if (f := self.fixed.get(field)) is not None and not (
                field == "counter_account" and f.value == self.entry.account_id
            ):
                kind = "transfer" if field == "counter_account" else "flow"
                return Decided(kind, f.pass_name, f.basis)
        # a document implies a flow (spec §5.9 field order): no pass proposes a transfer for a transaction
        # with a linked or picked document, whichever it is (own account, rule, history): it is dropped
        documented = self.entry.documented
        if not documented and (p0 := self.own_account()) is not None:
            return p0[0]
        for c in self.classifiers:
            p = self.ask(c, "type")
            if p is not None and not (documented and p.value == "transfer"):
                return Decided(str(p.value), c.pass_name, p.basis)
            # a pass that proposes a counter-account proposes a transfer, a payee or category a flow
            if not documented and (p := self.counter_proposal(c)) is not None:
                return Decided("transfer", c.pass_name, p.basis)
            for field in _FLOW_FIELDS:
                p = self.ask(c, field)
                if p is not None and p.value != NO_PAYEE:
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
            if p.value == NO_PAYEE:
                return None
            return Decided(p.value, c.pass_name, p.basis)
        return None

    def run(self) -> Resolved:
        kind = self.type_()
        if kind is None:
            return Resolved()
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
) -> Resolved:
    """What the passes decide for `entry`, around the `fixed` fields; `classifiers` by authority.

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
    ).run()
