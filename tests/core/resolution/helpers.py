"""Builders and a scripted classifier for the resolution tests (no database)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from app.core.plugins.classifier import (
    AccountFact,
    ClassifierContext,
    EntryInput,
    Field,
    Proposal,
)

DAY = date(2026, 3, 10)


def entry(**kw: Any) -> EntryInput:
    base: dict[str, Any] = {
        "entry_id": 1,
        "account_id": 1,
        "currency": "EUR",
        "booked_on": DAY,
        "amount": -500,
    }
    base.update(kw)
    return EntryInput(**base)


def account(id: int, currency: str = "EUR", ref: str | None = None, **kw: Any) -> AccountFact:
    return AccountFact(id=id, currency=currency, external_ref=ref, **kw)


class Script:
    """A classifier answering from a table: field -> value, or field -> callable(ctx).

    Records every call as (field, resolved fields so far).
    """

    def __init__(self, pass_name: str, answers: Mapping[Field, Any]) -> None:
        self.pass_name = pass_name
        self.answers = answers
        self.calls: list[tuple[Field, tuple[Field, ...]]] = []

    def propose(self, field: Field, entry: EntryInput, ctx: ClassifierContext) -> Proposal | None:
        self.calls.append((field, tuple(ctx.resolved)))
        answer = self.answers.get(field)
        if callable(answer):
            answer = answer(ctx)
        if answer is None:
            return None
        return Proposal(field, answer, {"by": self.pass_name, "v": answer})


class Boom:
    pass_name = "boom"

    def propose(self, field: Field, entry: EntryInput, ctx: ClassifierContext) -> Proposal | None:
        raise RuntimeError("classifier crashed")
