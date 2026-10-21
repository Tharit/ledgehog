from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine

from app.core.model.queue import configure_model_queue
from app.core.resolution.registry import configure_classifiers, current_factory, unconfigure_classifiers
from tests.core.model.rig import Rig, make_rig


@pytest.fixture
def rig(isolated_engine: Engine) -> Iterator[Rig]:
    """The model wired as startup wires it, against a fake endpoint; the globals are restored."""
    previous = current_factory()
    r = make_rig(isolated_engine)
    try:
        yield r
    finally:
        configure_model_queue(None)
        if previous is None:
            unconfigure_classifiers()
        else:
            configure_classifiers(previous)
