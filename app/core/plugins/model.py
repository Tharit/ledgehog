"""The model client protocol (architecture §5.4, spec §5.9 pass 3).

Core's worker (`core/model`) asks a `ModelClient` for the category of one entry; the
concrete client (`plugins/classifiers/llm`) owns the payload restriction, the request and the validation of
the reply. Ids only: an answer can reference an existing category, nothing else.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.core.plugins.classifier import EntryInput


class ModelUnavailable(Exception):
    """The model could not be reached or answered with an error (timeout, refused, HTTP error)."""


@dataclass(frozen=True, slots=True)
class CategoryPath:
    """One category of the tree: its id and its path (`Expense > Food > Groceries`)."""

    id: int
    path: str


@dataclass(frozen=True, slots=True)
class ModelAnswer:
    """A valid answer: an existing category id and a one-line rationale; or no id, the model's answer that
    no category fits, with the rationale that says what would."""

    category_id: int | None
    rationale: str
    model: str


@dataclass(frozen=True, slots=True)
class NoAnswer:
    """The model gave no usable answer; `reason` is a short code (`not_json`, `unknown_id`, `truncated`, ...)
    that says why and never carries any of the reply."""

    reason: str
    tokens: int | None = None  # for `truncated`: the completion tokens spent, a number, nothing of the reply


class ModelClient(Protocol):
    name: str

    def fingerprint(self, subject: EntryInput) -> str | None:
        """A fingerprint of the payload the model would be given, or None when the payload is empty."""
        ...

    async def ask(self, subject: EntryInput, categories: Sequence[CategoryPath]) -> ModelAnswer | NoAnswer:
        """The model's answer, or `NoAnswer` with the reason when it has none (the reply was not valid).
        Raises `ModelUnavailable` when the model cannot be reached."""
        ...

    async def aclose(self) -> None: ...
