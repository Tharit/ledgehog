"""Rule writes (spec §5.9, architecture §4.1 'Management writes', D198-D204): create, update, delete.

Every write is ONE transaction: settle lock shared, the rule row locked (`FOR UPDATE`), the write,
then the preview of the rule as it now stands (`rule_preview.build_preview`); it commits, and only
then settles (a settling failure is the `error` of the result, never raised into the committed write).
`dry_run` runs the same code and rolls it back, so the preview shown is the one the real run
computes. The real run carries `expected_count`, the number of entries the preview matched; another
number rolls everything back (409 `filter_result_changed`).

A rule write changes no entry (I20) and bumps no version: settling applies the rules to the
unconfirmed units afterwards. What a rule sets is fixed at creation (D199); there is no enabled flag
and no version (D198): the last write wins.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

from app.core.ledger.dimensions import (
    DimensionError,
    DuplicateName,
    ExpectedCountRequired,
    clean_name,
    previewable,
)
from app.core.ledger.rule_preview import DEFAULT_LIMIT, RulePreview, build_preview
from app.core.ledger.tags import FilterResultChanged
from app.core.plugins.classifier import Condition, RuleInvalid, RuleSpec
from app.core.resolution.load import conditions_of, load_rules
from app.core.resolution.registry import rule_tools
from app.core.settle.settle import SettleResult, settle
from app.core.stale import StaleReference
from app.utils.db.errors import constraint_name
from app.utils.db.locks import lock_rows, retry_on_deadlock

SETS = ("counter_account", "payee", "category")
DEFAULT_PRIORITY = 100
_TARGET_FIELD = {"counter_account": "counter_account_id", "payee": "payee_id", "category": "category_id"}
_TARGET_ENTITY = {"counter_account": "account", "payee": "payee", "category": "category"}


class RuleMissing(DimensionError):
    def __init__(self, rule_id: int) -> None:
        self.rule_id = rule_id
        super().__init__(f"rule {rule_id} does not exist")


class InvalidRule(DimensionError):
    """The rule cannot be saved; `field` names the part at fault. The message never quotes the input."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(message)


class RuleCountChanged(FilterResultChanged):
    """The rule now matches another number of entries than its preview showed."""

    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(expected, actual)
        self.args = (f"the rule now matches {actual} entries, not the {expected} that were previewed",)


@dataclass(frozen=True)
class RuleDraft:
    """What a rule write says. Exactly the target id `sets` names is given.

    `sets` is None on an update that does not restate it (it can never change).
    """

    name: str
    sets: str | None = None
    counter_account_id: int | None = None
    payee_id: int | None = None
    category_id: int | None = None
    conditions: tuple[Condition, ...] = ()
    # None: the client gave none; a rule update takes the default
    priority: int | None = None


@dataclass(frozen=True)
class RuleRow:
    """A rule as stored: the one target column `sets` names is filled, the others None."""

    id: int
    name: str
    sets: str
    counter_account_id: int | None
    payee_id: int | None
    category_id: int | None
    conditions: tuple[Condition, ...]
    priority: int

    @property
    def target_id(self) -> int:
        value = getattr(self, _TARGET_FIELD[self.sets])
        assert value is not None  # the schema's ck_rule_sets
        return int(value)

    def spec(self) -> RuleSpec:
        return RuleSpec(
            id=self.id,
            name=self.name,
            sets=self.sets,  # type: ignore[arg-type]
            target_id=self.target_id,
            priority=self.priority,
            conditions=self.conditions,
        )


@dataclass(frozen=True)
class SettleBreakdown:
    """Where the entries a rule write's settling touched stand afterwards, by the final derivation pass
    of the field the rule sets: decided by this rule, proposed by history, decided by another rule, or
    anything else (no value for the field, flag-only changes, the user's own decisions, ...). The parts
    add up to `total`. A deleted rule decides nothing: entries still carrying its key count as `other`."""

    total: int
    this_rule: int
    history: int
    other_rules: int
    other: int


_BREAKDOWN = (
    "SELECT CASE"
    " WHEN d.p = 'rule' AND d.rid = :rid THEN 'this_rule'"
    " WHEN d.p = 'rule' THEN 'other_rules'"
    " WHEN d.p = 'history' THEN 'history'"
    " ELSE 'other' END AS kind, count(*) AS n"
    " FROM (SELECT derivation -> CAST(:f AS text) ->> 'pass' AS p,"
    " derivation -> CAST(:f AS text) -> 'basis' ->> 'rule_id' AS rid"
    " FROM ledger_entry WHERE id = ANY(:ids)) d GROUP BY 1"
)


def _breakdown(
    engine: Engine, result: SettleResult, rule: RuleRow, *, deleted: bool
) -> SettleBreakdown | None:
    """Classify the touched entries; None when settling failed (its numbers would mislead)."""
    if result.error is not None:
        return None
    ids = list(result.touched_entry_ids)
    counts: dict[str, int] = {}
    if ids:
        with engine.connect() as conn:
            rows = conn.execute(text(_BREAKDOWN), {"f": rule.sets, "rid": str(rule.id), "ids": ids}).all()
        counts = {str(r.kind): int(r.n) for r in rows}
    this_rule = 0 if deleted else counts.get("this_rule", 0)
    return SettleBreakdown(
        total=len(ids),
        this_rule=this_rule,
        history=counts.get("history", 0),
        other_rules=counts.get("other_rules", 0),
        other=counts.get("other", 0) + (counts.get("this_rule", 0) if deleted else 0),
    )


def _settled(engine: Engine, result: RuleWritten) -> RuleWritten:
    """The write's result with the settle round run after the committed write, and its breakdown."""
    assert result.rule is not None
    done = settle(engine)
    return replace(
        result, settle=done, settle_breakdown=_breakdown(engine, done, result.rule, deleted=result.deleted)
    )


@dataclass(frozen=True)
class RuleWritten:
    """A create, update or delete. `rule` is the rule as it stands after the write (as it was, for a
    delete); None for the dry run of a create, which has no id yet. `settle` is None on a dry run."""

    rule: RuleRow | None
    preview: RulePreview
    deleted: bool
    settle: SettleResult | None = None
    settle_breakdown: SettleBreakdown | None = None


_COLUMNS = "id, name, sets, counter_account_id, payee_id, category_id, conditions, priority"


def _row(r: Any) -> RuleRow:
    return RuleRow(
        r.id, r.name, r.sets, r.counter_account_id, r.payee_id, r.category_id,
        conditions_of(r.conditions), r.priority,
    )  # fmt: skip


def get_rule(conn: Connection, rule_id: int) -> RuleRow | None:
    row = conn.execute(text(f"SELECT {_COLUMNS} FROM rule WHERE id = :i"), {"i": rule_id}).one_or_none()  # noqa: S608
    return None if row is None else _row(row)


def list_rules(conn: Connection) -> list[RuleRow]:
    """Every rule in evaluation order: counter-account, payee, category; priority, then id."""
    rows = {r.id: r for r in (_row(x) for x in conn.execute(text(f"SELECT {_COLUMNS} FROM rule")))}  # noqa: S608
    return [rows[s.id] for s in rule_tools().precedence_order(r.spec() for r in rows.values())]


def _canonical(cond: Condition) -> Condition:
    """A payee condition's id as plain digits (`007` is `7`), so a merge finds it by its text. What
    is not an id is left for the plugin to refuse."""
    if cond.field == "payee" and cond.value.isascii() and cond.value.isdigit():
        return replace(cond, value=str(int(cond.value)))
    return cond


def _checked(draft: RuleDraft, sets: str) -> RuleDraft:
    """The cleaned draft, refused when the rule cannot be saved (before any transaction)."""
    if sets not in SETS:
        raise InvalidRule("sets", "a rule sets a counter-account, a payee or a category")
    given = {f: getattr(draft, f) for f in _TARGET_FIELD.values() if getattr(draft, f) is not None}
    wanted = _TARGET_FIELD[sets]
    if wanted not in given:
        raise InvalidRule(wanted, f"a rule that sets a {sets.replace('_', '-')} needs `{wanted}`")
    for extra in given:
        if extra != wanted:
            raise InvalidRule(extra, f"a rule that sets a {sets.replace('_', '-')} takes `{wanted}` only")
    cleaned = replace(
        draft,
        name=clean_name(draft.name),
        sets=sets,
        conditions=tuple(_canonical(c) for c in draft.conditions),
    )
    spec = RuleSpec(
        id=0,
        name=cleaned.name,
        sets=sets,  # type: ignore[arg-type]
        target_id=given[wanted],
        priority=DEFAULT_PRIORITY if cleaned.priority is None else cleaned.priority,
        conditions=cleaned.conditions,
    )
    try:
        rule_tools().validate(spec)
    except RuleInvalid as exc:
        raise InvalidRule(exc.field, str(exc)) from exc
    return cleaned


def _exists(conn: Connection, table: str, row_id: int) -> bool:
    return conn.execute(text(f"SELECT 1 FROM {table} WHERE id = :i"), {"i": row_id}).first() is not None  # noqa: S608


def _check_references(conn: Connection, draft: RuleDraft) -> None:
    """A target or payee condition that no longer exists is `stale_reference`, naming the field."""
    assert draft.sets is not None
    field = _TARGET_FIELD[draft.sets]
    target = getattr(draft, field)
    entity = _TARGET_ENTITY[draft.sets]
    if not _exists(conn, entity, target):
        raise StaleReference(field, entity, target)
    for i, cond in enumerate(draft.conditions):
        # the plugin has validated the value as a positive integer id
        if cond.field == "payee" and not _exists(conn, "payee", int(cond.value)):
            raise StaleReference(f"conditions[{i}].value", "payee", int(cond.value))


def _duplicate(exc: DBAPIError) -> bool:
    return constraint_name(exc) == "ux_rule_name"


def _params(draft: RuleDraft) -> dict[str, Any]:
    return {
        "n": draft.name,
        "s": draft.sets,
        "ca": draft.counter_account_id,
        "p": draft.payee_id,
        "c": draft.category_id,
        "conds": json.dumps(
            [{"field": c.field, "op": c.op, "value": c.value} for c in draft.conditions],
            separators=(",", ":"),
        ),
        "pri": DEFAULT_PRIORITY if draft.priority is None else draft.priority,
    }


def _require_count(dry_run: bool, expected: int | None) -> None:
    if not dry_run and expected is None:
        raise ExpectedCountRequired("a rule write")


def _check_count(dry_run: bool, expected: int | None, preview: RulePreview) -> None:
    """The real run's guard: the entries the rule matches are the number the user confirmed."""
    if not dry_run and expected != preview.matches.total:
        assert expected is not None  # `_require_count` ran first
        raise RuleCountChanged(expected, preview.matches.total)


def _spec_of(rules: list[RuleSpec], rule_id: int) -> RuleSpec:
    return next(r for r in rules if r.id == rule_id)


def create_rule(
    engine: Engine,
    draft: RuleDraft,
    *,
    dry_run: bool = False,
    expected_count: int | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> RuleWritten:
    """Create a rule (`draft.sets` names what it sets, fixed from now on); previewed.

    The preview is the rule as written: the entries it matches, the units it would confirm and lists
    A and B (B is empty for a new rule). `dry_run` writes nothing.
    """
    if draft.sets is None:
        raise InvalidRule("sets", "a rule needs `sets`: what it sets")
    cleaned = _checked(draft, draft.sets)
    _require_count(dry_run, expected_count)

    def work(conn: Connection) -> RuleWritten:
        _check_references(conn, cleaned)
        try:
            new_id = int(conn.execute(text(_INSERT), _params(cleaned)).scalar_one())
        except DBAPIError as exc:
            if _duplicate(exc):
                raise DuplicateName("rule") from exc
            raise
        row = get_rule(conn, new_id)
        assert row is not None
        rules = load_rules(conn)
        preview = build_preview(conn, _spec_of(rules, new_id), rules, new=True, limit=limit, offset=offset)
        _check_count(dry_run, expected_count, preview)
        return RuleWritten(None if dry_run else row, preview, False)

    result = retry_on_deadlock(lambda: previewable(engine, dry_run, work))
    return result if dry_run else _settled(engine, result)


_INSERT = (
    "INSERT INTO rule (name, sets, counter_account_id, payee_id, category_id,"
    " conditions, priority)"
    " VALUES (:n, :s, :ca, :p, :c, CAST(:conds AS jsonb), :pri) RETURNING id"
)

_UPDATE = (
    "UPDATE rule SET name = :n, counter_account_id = :ca, payee_id = :p, category_id = :c,"
    " conditions = CAST(:conds AS jsonb), priority = :pri WHERE id = :id"
)


def update_rule(
    engine: Engine,
    rule_id: int,
    draft: RuleDraft,
    *,
    dry_run: bool = False,
    expected_count: int | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> RuleWritten:
    """Replace a rule's name, target value, conditions and priority; previewed.

    What it sets never changes: a `draft.sets` naming another value is `InvalidRule` (the same value is
    tolerated). The draft gives the target id of the rule's own `sets` and the full set of conditions.
    """
    if draft.sets is not None and draft.sets not in SETS:
        raise InvalidRule("sets", "a rule sets a counter-account, a payee or a category")
    _require_count(dry_run, expected_count)

    def work(conn: Connection) -> RuleWritten:
        if not lock_rows(conn, "rule", [rule_id]):
            raise RuleMissing(rule_id)
        current = get_rule(conn, rule_id)
        if current is None:
            raise RuleMissing(rule_id)
        if draft.sets is not None and draft.sets != current.sets:
            raise InvalidRule(
                "sets", "what a rule sets cannot be changed: delete the rule and create another"
            )
        cleaned = _checked(draft, current.sets)
        _check_references(conn, cleaned)
        try:
            conn.execute(text(_UPDATE), {**_params(cleaned), "id": rule_id})
        except DBAPIError as exc:
            if _duplicate(exc):
                raise DuplicateName("rule") from exc
            raise
        row = get_rule(conn, rule_id)
        assert row is not None
        rules = load_rules(conn)
        preview = build_preview(conn, _spec_of(rules, rule_id), rules, limit=limit, offset=offset)
        _check_count(dry_run, expected_count, preview)
        return RuleWritten(row, preview, False)

    result = retry_on_deadlock(lambda: previewable(engine, dry_run, work))
    return result if dry_run else _settled(engine, result)


def delete_rule(
    engine: Engine,
    rule_id: int,
    *,
    dry_run: bool = False,
    expected_count: int | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> RuleWritten:
    """Delete a rule; previewed. Keys naming it stay on the entries (they read "rule deleted").

    The preview is the rule as it stood: what it matched, and in list B every entry carrying its key.
    A deletion confirms nothing.
    """
    _require_count(dry_run, expected_count)

    def work(conn: Connection) -> RuleWritten:
        if not lock_rows(conn, "rule", [rule_id]):
            raise RuleMissing(rule_id)
        row = get_rule(conn, rule_id)
        if row is None:
            raise RuleMissing(rule_id)
        conn.execute(text("DELETE FROM rule WHERE id = :i"), {"i": rule_id})
        preview = build_preview(conn, row.spec(), load_rules(conn), deleted=True, limit=limit, offset=offset)
        _check_count(dry_run, expected_count, preview)
        return RuleWritten(row, preview, not dry_run)

    result = retry_on_deadlock(lambda: previewable(engine, dry_run, work))
    return result if dry_run else _settled(engine, result)
