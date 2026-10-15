"""Classifier pass 1: rules (spec §5.9, classifiers/rules.md).

Pure: rules arrive whole from core, nothing is read or written here. `matches` is the one
match function; the rule preview (step 6c) must use it too.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from functools import lru_cache

from app.core.ingest.identity import canonical_text
from app.core.plugins.classifier import (
    CONDITION_FIELDS,
    CONDITION_OPS,
    PAYEE_FIELD,
    TEXT_OPS,
    ClassifierContext,
    Condition,
    EntryInput,
    Field,
    Proposal,
    RuleInvalid,
    RuleSpec,
)
from app.core.plugins.text import normalise_name
from app.core.resolution.registry import RuleTools

MAX_PATTERN_LENGTH = 200
_DIGITS = re.compile(r"[0-9]+")

_GROUP_RANK = {"counter_account": 0, "payee": 1, "category": 2}
# fields compared as codes (canonical text) rather than as words (name normalisation)
_IDENTIFIERS = frozenset({"counterparty_ref", "mandate_ref"})


class RuleError(RuleInvalid):
    """A rule that cannot be saved."""


@lru_cache(maxsize=1024)
def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


def validate_rule(rule: RuleSpec) -> None:
    """Raise `RuleError` when the rule would be refused on save (rules.md §3, spec §5.9).

    Uniqueness of the name is the database's to check; here only what a rule says of itself. A
    message names the part at fault (`conditions[2].value`) and never quotes a value.
    """
    if not rule.name.strip():
        raise RuleError("the rule name must not be blank", "name")
    if rule.sets not in _GROUP_RANK:
        raise RuleError("a rule sets a counter-account, a payee or a category", "sets")
    if not rule.conditions:
        raise RuleError("a rule needs at least one condition", "conditions")
    for i, cond in enumerate(rule.conditions):
        at = f"conditions[{i}]"
        if cond.field not in CONDITION_FIELDS:
            raise RuleError(f"{at}: the field is not one a rule can read", f"{at}.field")
        if cond.op not in CONDITION_OPS:
            raise RuleError(f"{at}: the operator is not one a rule knows", f"{at}.op")
        if cond.field == PAYEE_FIELD:
            if rule.sets != "category":
                raise RuleError(f"{at}: a payee condition is only for category rules", f"{at}.field")
            if cond.op != "is":
                raise RuleError(f"{at}: a payee condition takes the operator `is` only", f"{at}.op")
        elif cond.op not in TEXT_OPS:
            raise RuleError(f"{at}: the operator is not one this field takes", f"{at}.op")
        if not isinstance(cond.value, str) or not cond.value.strip():
            raise RuleError(f"{at}: the value must not be blank", f"{at}.value")
        if cond.field == PAYEE_FIELD:
            if _payee_id(cond) is None:
                raise RuleError(f"{at}: a payee condition's value is a payee id", f"{at}.value")
            continue
        if cond.op == "regex":
            if len(cond.value) > MAX_PATTERN_LENGTH:
                raise RuleError(
                    f"{at}: a regex must be at most {MAX_PATTERN_LENGTH} characters", f"{at}.value"
                )
            try:
                _compile(cond.value)
            except re.error as exc:
                # the message of `re` can quote a piece of the pattern: only where it failed is said
                where = f" (at position {exc.pos})" if exc.pos is not None else ""
                raise RuleError(f"{at}: the regex does not compile{where}", f"{at}.value") from exc


def _payee_id(cond: Condition) -> int | None:
    """The id a `payee` condition names: a digit string of a positive integer, else None."""
    if not _DIGITS.fullmatch(cond.value):
        return None
    wanted = int(cond.value)
    return wanted if wanted > 0 else None


def default_rule_tools() -> RuleTools:
    """What the composition root hands core for rule writes and their preview."""
    return RuleTools(validate=validate_rule, matches=matches, precedence_order=precedence_order)


def precedence_order(rules: Iterable[RuleSpec]) -> list[RuleSpec]:
    """Evaluation order: counter-account, then payee, then category rules; within a group
    priority ascending, then id ascending (spec §5.9 Rule order)."""
    return sorted(rules, key=lambda r: (_GROUP_RANK[r.sets], r.priority, r.id))


def _comparable(field: str, text_: str | None) -> str:
    return canonical_text(text_) if field in _IDENTIFIERS else normalise_name(text_)


@lru_cache(maxsize=4096)
def _wanted(field: str, value: str) -> str:
    return _comparable(field, value)


def _holds(cond: Condition, entry: EntryInput, ctx_payee_id: int | None) -> bool:
    if cond.field == PAYEE_FIELD:
        # judged on the payee resolved so far; an id that no payee has any more never equals it
        wanted = _payee_id(cond)
        return wanted is not None and wanted == ctx_payee_id
    raw: str | None = getattr(entry, cond.field)
    if raw is None or not raw.strip():
        return False  # a condition on a field the entry lacks fails
    if cond.op == "regex":
        return _compile(cond.value).search(raw) is not None
    have = _comparable(cond.field, raw)
    want = _wanted(cond.field, cond.value)
    if not have or not want:
        return False  # nothing comparable on either side (a value of punctuation only, say)
    if cond.op == "equals":
        return have == want
    if cond.op == "starts_with":
        return have.startswith(want)
    return want in have


def matches(rule: RuleSpec, entry: EntryInput, ctx_payee_id: int | None = None) -> bool:
    """All of the rule's conditions hold, payee conditions judged on `ctx_payee_id`; a condition on a
    field the entry lacks does not (rules.md §2)."""
    return all(_holds(c, entry, ctx_payee_id) for c in rule.conditions)


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
            plain = [c for c in self._category if not any(k.field == PAYEE_FIELD for k in c.conditions)]
            r = self._first(plain, entry, ctx)
        return self._proposal("type", "flow", r) if r else None

    @staticmethod
    def _proposal(field: Field, value: int | str, rule: RuleSpec) -> Proposal:
        return Proposal(field, value, {"rule_id": rule.id})
