"""Classifier pass 1: rules (spec §5.9, classifiers/rules.md).

Pure: rules arrive whole from core, nothing is read or written here. `matches` is the one
match function; the rule preview (step 6c) must use it too.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from functools import lru_cache

from app.core.ingest.identity import canonical_text
from app.core.plugins.classifier import ClassifierContext, EntryInput, Field, Proposal, RuleSpec
from app.core.plugins.text import normalise_name

MAX_PATTERN_LENGTH = 200

_GROUP_RANK = {"counter_account": 0, "payee": 1, "category": 2}


class RuleError(ValueError):
    """A rule that cannot be saved."""


def _present(s: str | None) -> bool:
    return s is not None and s.strip() != ""


@lru_cache(maxsize=1024)
def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


def validate_rule(rule: RuleSpec) -> None:
    """Raise `RuleError` when the rule would be refused on save (rules.md §3, spec §5.9).

    Uniqueness of the name is the database's to check; here only what a rule says of itself.
    """
    if not rule.name.strip():
        raise RuleError("rule name is blank")
    if rule.sets not in _GROUP_RANK:
        raise RuleError(f"unknown target: {rule.sets!r}")
    if rule.condition_payee_id is not None and rule.sets != "category":
        raise RuleError("a payee condition is only for category rules")
    if _present(rule.purpose_regex):
        assert rule.purpose_regex is not None
        if len(rule.purpose_regex) > MAX_PATTERN_LENGTH:
            raise RuleError(f"regex longer than {MAX_PATTERN_LENGTH} characters")
        try:
            _compile(rule.purpose_regex)
        except re.error as exc:
            raise RuleError(f"regex does not compile: {exc}") from exc
    if not (
        rule.condition_payee_id is not None
        or any(
            _present(c)
            for c in (
                rule.counterparty_ref,
                rule.mandate_ref,
                rule.name_exact,
                rule.name_prefix,
                rule.purpose_regex,
                rule.booking_text,
            )
        )
    ):
        raise RuleError("a rule needs at least one condition")


def precedence_order(rules: Iterable[RuleSpec]) -> list[RuleSpec]:
    """Evaluation order: counter-account, then payee, then category rules; within a group
    priority ascending, then id ascending (spec §5.9 Rule order)."""
    return sorted(rules, key=lambda r: (_GROUP_RANK[r.sets], r.priority, r.id))


def matches(rule: RuleSpec, entry: EntryInput, ctx_payee_id: int | None = None) -> bool:
    """All of the rule's conditions hold; a condition on a field the entry lacks does not.

    Cheap conditions first, the regex last. Blank condition strings count as absent.
    """
    if rule.condition_payee_id is not None and rule.condition_payee_id != ctx_payee_id:
        return False
    for cond, value in (
        (rule.counterparty_ref, entry.counterparty_ref),
        (rule.mandate_ref, entry.mandate_ref),
        (rule.booking_text, entry.booking_text),
    ):
        if _present(cond):
            have = canonical_text(value)
            if not have or have != canonical_text(cond):
                return False
    if _present(rule.name_exact) or _present(rule.name_prefix):
        name = normalise_name(entry.counterparty_name)
        if not name:
            return False
        if _present(rule.name_exact) and name != normalise_name(rule.name_exact):
            return False
        if _present(rule.name_prefix) and not name.startswith(normalise_name(rule.name_prefix)):
            return False
    if _present(rule.purpose_regex):
        assert rule.purpose_regex is not None
        if not entry.purpose or _compile(rule.purpose_regex).search(entry.purpose) is None:
            return False
    return True


def _payee_in(ctx: ClassifierContext) -> int | None:
    p = ctx.resolved.get("payee")
    return p.value if p is not None and isinstance(p.value, int) else None


class RulesClassifier:
    """Pass 1. Constructed from every rule; refuses an invalid one."""

    pass_name = "rule"

    def __init__(self, rules: Sequence[RuleSpec]) -> None:
        for r in rules:
            validate_rule(r)
        ordered = precedence_order(rules)
        self._counter = [r for r in ordered if r.sets == "counter_account"]
        self._payee = [r for r in ordered if r.sets == "payee"]
        self._category = [r for r in ordered if r.sets == "category"]

    def matching_rules(
        self, entry: EntryInput, rule_candidates: Iterable[RuleSpec], ctx: ClassifierContext
    ) -> list[RuleSpec]:
        """The rules among `rule_candidates` matching the entry, in evaluation order.

        A counter-account rule whose account fails `ctx.account_ok` does not match.
        """
        payee_id = _payee_in(ctx)
        return [
            r
            for r in precedence_order(rule_candidates)
            if matches(r, entry, payee_id) and (r.sets != "counter_account" or ctx.account_ok(r.target_id))
        ]

    def _first(self, group: Sequence[RuleSpec], entry: EntryInput, ctx: ClassifierContext) -> RuleSpec | None:
        payee_id = _payee_in(ctx)
        for r in group:
            if not matches(r, entry, payee_id):
                continue
            if r.sets == "counter_account" and not ctx.account_ok(r.target_id):
                continue
            return r
        return None

    def propose(self, field: Field, entry: EntryInput, ctx: ClassifierContext) -> Proposal | None:
        if field == "counter_account":
            r = self._first(self._counter, entry, ctx)
            return self._proposal("counter_account", r.target_id, r) if r else None
        if field == "payee":
            r = self._first(self._payee, entry, ctx)
            return self._proposal("payee", r.target_id, r) if r else None
        if field == "category":
            r = self._first(self._category, entry, ctx)
            return self._proposal("category", r.target_id, r) if r else None
        # type: a payee condition cannot be judged before the payee is
        r = self._first(self._counter, entry, ctx)
        if r is not None:
            return self._proposal("type", "transfer", r)
        r = self._first(self._payee, entry, ctx)
        if r is None:
            plain = [c for c in self._category if c.condition_payee_id is None]
            r = self._first(plain, entry, ctx)
        return self._proposal("type", "flow", r) if r else None

    @staticmethod
    def _proposal(field: Field, value: int | str, rule: RuleSpec) -> Proposal:
        return Proposal(field, value, {"rule_id": rule.id})
