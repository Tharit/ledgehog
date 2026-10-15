"""The loaders carry what the matcher reads off a source: end-to-end id, instructed amount and currency."""

from __future__ import annotations

from app.core.resolution.load import load_unconfirmed
from app.core.units.stored import load_stored_unit
from tests.core.units.scene import Scene


def test_loaders_carry_end_to_end_id_and_the_instructed_amount(scene: Scene) -> None:
    _src, (e,) = scene.movement(-1000, instructed=(-1100, "USD"), end_to_end_id="E2E-1")
    with scene.engine.connect() as conn:
        (loaded,) = [u for u in load_unconfirmed(conn) if u.input.entry_id == e]
        stored = load_stored_unit(conn, e)
    assert (loaded.input.end_to_end_id, loaded.input.instructed_amount, loaded.input.instructed_currency) == (
        "E2E-1",
        -1100,
        "USD",
    )
    assert stored is not None
    src = stored.sources[_src]
    assert (src.end_to_end_id, src.instructed_amount, src.instructed_currency) == ("E2E-1", -1100, "USD")
