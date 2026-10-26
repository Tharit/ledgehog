"""Rederiving an unconfirmed entry (spec §5.9, I18, D203).

The walk takes the fields in order. A field with a standing key is kept and joins the fixed set
the later fields resolve around; one with a proposal key, or none, is resolved afresh; when a
field's value changes, every later standing field is derived again. Settling writes the
differences (`diff`), so a second settle writes nothing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.core.plugins.classifier import (
    STANDING_PASSES,
    AccountFact,
    Classifier,
    EntryInput,
    Field,
    HistorySource,
)
from app.core.resolution.resolve import Decided, Resolved, resolve
from app.core.resolution.types import is_explained_absence, stands_for

__all__ = ["diff", "rederive", "resolve_afresh"]


def resolve_afresh(
    entry: EntryInput,
    *,
    accounts: Sequence[AccountFact],
    classifiers: Sequence[Classifier],
    history: HistorySource | None = None,
    exclude_entry_ids: frozenset[int] = frozenset(),
) -> Resolved:
    """Every value derived again, standing and a user's included: the entry's input changed."""
    return resolve(
        entry,
        accounts=accounts,
        classifiers=classifiers,
        history=history,
        exclude_entry_ids=exclude_entry_ids,
    )


def _walk(type_value: int | str | None) -> tuple[Field, ...]:
    if type_value == "transfer":
        return ("counter_account",)
    # an entry without a type has no value to find, but a pass may still explain why its payee or category
    # stays empty (`resolve` returns that and nothing else for it)
    return ("payee", "category")


def rederive(
    entry: EntryInput,
    current: Mapping[Field, Decided | None],
    *,
    accounts: Sequence[AccountFact],
    classifiers: Sequence[Classifier],
    history: HistorySource | None = None,
    exclude_entry_ids: frozenset[int] = frozenset(),
) -> Resolved:
    """The values of an unconfirmed entry now, given what is stored (`current`). A value decided empty is a
    standing value like any other."""
    fixed: dict[Field, Decided] = {}
    changed = False
    # The last afresh resolution. Resolving around values it decided itself gives the same answer,
    # so the next field reads it instead of resolving the entry again (one resolve, not one per field).
    last: Resolved | None = None

    def step(field: Field) -> Decided | None:
        nonlocal changed, last
        cur = current.get(field)
        own = field == "counter_account" and cur is not None and cur.value == entry.account_id
        new: Decided | None
        if cur is not None and cur.pass_name in STANDING_PASSES and not changed and not own:
            new = cur
        else:
            if last is None or any(last.get(f) != d for f, d in fixed.items()):
                last = resolve(
                    entry,
                    accounts=accounts,
                    classifiers=classifiers,
                    history=history,
                    fixed=fixed,
                    exclude_entry_ids=exclude_entry_ids,
                    stored=current,
                )
            new = last.get(field)
            changed = changed or stands_for(new) != stands_for(cur)
        if new is not None:
            fixed[field] = new
        return new

    kind = step("type")
    for field in _walk(kind.value if kind else None):
        step(field)
    if kind is None:  # nothing but an explained absence can stand without a type
        fixed = {f: d for f, d in fixed.items() if is_explained_absence(d)}
    return Resolved(fixed)


def diff(old: Mapping[Field, Decided | None], new: Mapping[Field, Decided]) -> dict[Field, Decided | None]:
    """The fields to write: a new or changed decision (value, pass or basis), None for a removal."""
    changes: dict[Field, Decided | None] = {}
    for field in ("type", "payee", "category", "counter_account"):
        before, after = old.get(field), new.get(field)
        if before != after:
            changes[field] = after
    return changes
