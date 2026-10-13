"""The preview of a rule write (spec §5.9 'The preview of a rule write', D204), read-only.

Given the rule as it stands after the write (the preview runs inside the write's own transaction,
which a dry run rolls back, so there is no second code path to drift from the real one) and the
whole rule set it belongs to, it answers:

* (a) `matches`: every movement entry the rule matches, confirmed or not, each with the earlier rule
  that would win over it (`shadowed_by_rule_id`);
* (b) `would_confirm` / `stay_in_review`: of the matched entries that are not confirmed, how many
  would end complete with only standing keys once settling applies the rule set (the same
  `rederive` over the same history snapshot settling uses, in memory);
* (c) list A, `different_value`: matched entries whose stored value of what the rule sets differs
  from the rule's value and that settling will leave as they are (confirmed, or under a standing
  key; a mere proposal is replaced by the settle that follows, so it is not listed), and list B,
  `lost_key`: entries carrying this rule's standing key that the rule no longer matches (every keyed
  entry, for a deletion; none for a new rule).

The one match function is the rules plugin's (`RuleTools.matches`), the same settling's rules
classifier calls; core adds the tests it owns for a counter-account rule (currency, open on the
booking date). A category rule with a payee condition is judged against the entry's stored payee.
Nothing here writes, and no entry value changes (I20).
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Connection, text

from app.core.domain.source import SourceFields
from app.core.plugins.classifier import STANDING_PASSES, AccountFact, Field, RuleSpec
from app.core.resolution import counter_account_ok, rederive
from app.core.resolution.load import UnconfirmedEntry, load_accounts, load_movements
from app.core.resolution.registry import RuleTools, classifiers_for, rule_tools
from app.core.resolution.snapshot import load_snapshot
from app.core.settle.resolution import new_derivation, stored_decisions

DEFAULT_LIMIT = 100
MAX_LIMIT = 500

_FIELDS: tuple[Field, ...] = ("type", "payee", "category", "counter_account")
# what a rule sets -> (the derivation key of that field, the `UnconfirmedEntry` attribute holding it)
_TARGET: dict[str, tuple[Field, str]] = {
    "counter_account": ("counter_account", "counter_account_id"),
    "payee": ("payee", "payee_id"),
    "category": ("category", "category_id"),
}


@dataclass(frozen=True)
class PreviewRow:
    """One entry of a list. `current_value`/`current_key` are those of the field the rule sets."""

    entry_id: int
    account_id: int
    booked_on: date
    amount: int
    currency: str
    description: str | None
    confirmed: bool
    current_value: int | None
    current_key: Mapping[str, Any] | None
    shadowed_by_rule_id: int | None = None  # matches only
    keyed_fields: tuple[str, ...] = ()  # lost-key list only: the fields carrying the rule's key
    source: SourceFields | None = None  # the entry's source, as in the ledger list (D206)


@dataclass(frozen=True)
class PreviewList:
    total: int  # exact; `rows` is one page of it
    rows: tuple[PreviewRow, ...]


@dataclass(frozen=True)
class RulePreview:
    matches: PreviewList
    would_confirm: int  # matched unconfirmed entries whose unit would be confirmed by settling
    stay_in_review: int  # matched unconfirmed entries that would not
    different_value: PreviewList  # list A
    lost_key: PreviewList  # list B


@dataclass(frozen=True)
class _Evaluation:
    """Everything one preview reads, matched once."""

    tools: RuleTools
    rules: Sequence[RuleSpec]  # in evaluation order
    accounts: Mapping[int, AccountFact]

    def matches(self, rule: RuleSpec, row: UnconfirmedEntry) -> bool:
        if not self.tools.matches(rule, row.input, row.payee_id):
            return False
        if rule.sets == "counter_account":
            account = self.accounts.get(rule.target_id)
            return account is not None and counter_account_ok(row.input, account)
        return True

    def shadow_of(self, subject: RuleSpec, row: UnconfirmedEntry) -> int | None:
        """The rule that wins this entry's field before `subject` does, if one does (spec §5.9 Rule order).

        Evaluation is counter-account rules, payee rules, category rules; a matching counter-account
        rule makes the entry a transfer, so it also takes the payee and the category from every rule.
        """
        for rule in self.rules:
            if rule.sets not in (subject.sets, "counter_account"):
                continue
            if rule.id == subject.id:
                return None
            if self.matches(rule, row):
                return rule.id
        return None


def _key_of(row: UnconfirmedEntry, sets: str) -> Mapping[str, Any] | None:
    key = row.derivation.get(_TARGET[sets][0])
    return key if isinstance(key, Mapping) else None


def _value_of(row: UnconfirmedEntry, sets: str) -> int | None:
    value = getattr(row, _TARGET[sets][1])
    return None if value is None else int(value)


def _keeps_value(row: UnconfirmedEntry, sets: str) -> bool:
    """True when settling will leave the entry's value of what the rule sets as it is.

    A confirmed entry, a value under a standing key and a value with no key (hand-seeded or
    user-authored, treated as standing) stay; a proposal, or no value yet in an unconfirmed entry,
    is replaced by the settle that follows the write, so the user has nothing to check there.
    """
    if row.confirmed:
        return True
    key = _key_of(row, sets)
    if key is None:
        return _value_of(row, sets) is not None
    return key.get("pass") in STANDING_PASSES


def _row(
    row: UnconfirmedEntry, sets: str, *, shadow: int | None = None, keyed: tuple[str, ...] = ()
) -> PreviewRow:
    return PreviewRow(
        entry_id=row.input.entry_id,
        account_id=row.input.account_id,
        booked_on=row.input.booked_on,
        amount=row.input.amount,
        currency=row.input.currency,
        description=row.description,
        confirmed=row.confirmed,
        current_value=_value_of(row, sets),
        current_key=_key_of(row, sets),
        shadowed_by_rule_id=shadow,
        keyed_fields=keyed,
        source=row.source,
    )


def _page(rows: list[UnconfirmedEntry], build: Any, limit: int, offset: int) -> PreviewList:
    # newest first, like the ledger list
    rows = sorted(rows, key=lambda r: (r.input.booked_on, r.input.entry_id), reverse=True)
    return PreviewList(len(rows), tuple(build(r) for r in rows[offset : offset + limit]))


def _key_carriers(conn: Connection, rule_id: int) -> set[int]:
    """The entries whose derivation carries this rule's standing key under any field.

    One containment per field (`derivation @> ...`), the shape the GIN index `ix_le_derivation`
    (jsonb_path_ops) serves: a bitmap-or of four index scans, not a scan of the ledger.
    """
    params: dict[str, Any] = {
        f: json.dumps({f: {"pass": "rule", "basis": {"rule_id": rule_id}}}, separators=(",", ":"))
        for f in _FIELDS
    }
    where = " OR ".join(f"derivation @> CAST(:{f} AS jsonb)" for f in _FIELDS)
    return {
        int(i) for i in conn.execute(text(f"SELECT id FROM ledger_entry WHERE {where}"), params).scalars()
    }  # noqa: S608


def _keyed_fields(row: UnconfirmedEntry, rule_id: int) -> tuple[str, ...]:
    out = []
    for f in _FIELDS:
        key = row.derivation.get(f)
        if (
            isinstance(key, Mapping)
            and key.get("pass") == "rule"
            and isinstance(key.get("basis"), Mapping)
            and key["basis"].get("rule_id") == rule_id
        ):
            out.append(f)
    return tuple(out)


def _units_confirmed(
    conn: Connection,
    ev: _Evaluation,
    unit_ids: set[int],
    by_unit: Mapping[int, list[UnconfirmedEntry]],
) -> dict[int, bool]:
    """Per unit (source transaction): would it be confirmed once settling has applied `ev.rules`?

    Settling's own resolution step, in memory: the stored decisions are rederived against the rule
    set and the history snapshot, and the unit is complete when every entry has a type, a flow its
    category, a transfer its pair, and no key is a proposal (confirmed.py, the same definition).
    """
    classifiers = classifiers_for(ev.rules)
    snapshot = load_snapshot(conn)
    accounts = list(ev.accounts.values())
    result: dict[int, bool] = {}
    for unit in unit_ids:
        ok = True
        for row in by_unit[unit]:
            current = stored_decisions(row)
            derivation: Mapping[str, Any] = row.derivation
            type_, category = row.type, row.category_id
            if not row.paired:
                new = rederive(
                    row.input,
                    current,
                    accounts=accounts,
                    classifiers=classifiers,
                    history=snapshot,
                    exclude_entry_ids=frozenset({row.input.entry_id}),
                )
                kind = new.get("type")
                if not (kind is not None and kind.value == "transfer" and not row.original):
                    derivation = new_derivation(row.derivation, new)
                    type_ = str(kind.value) if kind is not None else None
                    cat = new.get("category")
                    category = int(cat.value) if cat is not None else None
            complete = (
                type_ is not None
                and (type_ != "flow" or category is not None)
                and (type_ != "transfer" or row.paired)
                and all(
                    isinstance(k, Mapping) and k.get("pass") in STANDING_PASSES for k in derivation.values()
                )
            )
            if not complete:
                ok = False
                break
        result[unit] = ok
    return result


def build_preview(
    conn: Connection,
    subject: RuleSpec,
    rules: Sequence[RuleSpec],
    *,
    deleted: bool = False,
    new: bool = False,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> RulePreview:
    """The preview of `subject` among `rules` (which contain it, a deleted one included).

    `deleted`: the rule is being removed: it is previewed as it stands now, a deletion confirms
    nothing and carries no value to differ from, and every entry holding its key is listed.
    `new`: the rule has no key anywhere yet (list B is empty without asking the index).
    `rules` is the set settling applies afterwards: for a deletion, without the subject.
    """
    tools = rule_tools()
    accounts = {a.id: a for a in load_accounts(conn)}
    entries = load_movements(conn)
    shadow_set = list(rules) if not deleted else [*rules, subject]
    ev = _Evaluation(tools, tools.precedence_order(shadow_set), accounts)
    sets = subject.sets

    matched = [r for r in entries if ev.matches(subject, r)]
    matches = _page(matched, lambda r: _row(r, sets, shadow=ev.shadow_of(subject, r)), limit, offset)

    would_confirm = stay = 0
    unconfirmed = [r for r in matched if not r.confirmed]
    if unconfirmed and not deleted:
        by_unit: dict[int, list[UnconfirmedEntry]] = defaultdict(list)
        for r in entries:
            by_unit[r.source_id].append(r)
        units = {r.source_id for r in unconfirmed}
        confirmed_units = _units_confirmed(conn, _Evaluation(tools, list(rules), accounts), units, by_unit)
        would_confirm = sum(1 for r in unconfirmed if confirmed_units[r.source_id])
        stay = len(unconfirmed) - would_confirm

    different = (
        []
        if deleted
        else [r for r in matched if _value_of(r, sets) != subject.target_id and _keeps_value(r, sets)]
    )
    list_a = _page(different, lambda r: _row(r, sets), limit, offset)

    lost: list[UnconfirmedEntry] = []
    if not new:
        carriers = _key_carriers(conn, subject.id)
        by_id = {r.input.entry_id: r for r in entries}
        lost = [by_id[i] for i in carriers if i in by_id and (deleted or not ev.matches(subject, by_id[i]))]
    list_b = _page(lost, lambda r: _row(r, sets, keyed=_keyed_fields(r, subject.id)), limit, offset)
    return RulePreview(matches, would_confirm, stay, list_a, list_b)
