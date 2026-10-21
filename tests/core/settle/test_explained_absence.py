"""A classifier's explained absence (spec §5.9 Derivation, architecture §5.4): a proposal with no value,
kept by settling while its classifier proposes it again and dropped when it does not. Generic: a fake
classifier, not the model."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence

import pytest
from sqlalchemy import Engine, text

from app.core.plugins.classifier import Classifier, ClassifierContext, EntryInput, Field, Proposal
from app.core.resolution.registry import configure_classifiers, current_factory, unconfigure_classifiers
from app.core.settle import settle
from tests.core.settle.test_resolution_step import _new

MakeAccount = Callable[..., int]


class Explains:
    """Proposes "the category stays empty, and why" for every entry while `on`."""

    pass_name = "history"

    def __init__(self) -> None:
        self.on = True

    def propose(self, field: Field, entry: EntryInput, ctx: ClassifierContext) -> Proposal | None:
        if field != "category" or not self.on:
            return None
        return Proposal("category", None, {"why": "nothing fits"})


@pytest.fixture
def classifier() -> Iterator[Explains]:
    previous = current_factory()
    c = Explains()
    chain: Sequence[Classifier] = [c]
    configure_classifiers(lambda rules: chain)
    try:
        yield c
    finally:
        if previous is None:
            unconfigure_classifiers()
        else:
            configure_classifiers(previous)


def _row(engine: Engine, entry: int):  # type: ignore[no-untyped-def]
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT type, category_id, derivation, review_flags FROM ledger_entry WHERE id = :i"),
            {"i": entry},
        ).one()


def test_an_explained_absence_is_kept_while_its_classifier_proposes_it(
    classifier: Explains, isolated_engine: Engine, make_account: MakeAccount
) -> None:
    with isolated_engine.begin() as conn:
        e = _new(conn, make_account(conn), counterparty_name="X")
    settle(isolated_engine)
    row = _row(isolated_engine, e)
    assert row.category_id is None and row.type is None
    assert row.derivation["category"] == {"pass": "history", "basis": {"why": "nothing fits", "none": True}}
    assert list(row.review_flags) == ["unclassified", "unconfirmed"]  # a proposal: never confirmed
    assert settle(isolated_engine).touched_entry_ids == ()  # stable: written once


def test_it_is_dropped_when_the_classifier_stops_proposing_it(
    classifier: Explains, isolated_engine: Engine, make_account: MakeAccount
) -> None:
    with isolated_engine.begin() as conn:
        e = _new(conn, make_account(conn), counterparty_name="X")
    settle(isolated_engine)
    classifier.on = False
    settle(isolated_engine)
    assert "category" not in _row(isolated_engine, e).derivation
