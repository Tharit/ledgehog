"""Properties of the line allocation: whatever it returns sums exactly and uses each line once; it finds an
allocation whenever a brute-force search does; the references it keeps are kept."""

from __future__ import annotations

from datetime import date, timedelta
from itertools import product

from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.matching import Line, Party, allocate

D = date(2026, 3, 10)


@st.composite
def worlds(draw: st.DrawFn) -> tuple[list[Line], int, list[Party]]:
    amounts = draw(st.lists(st.sampled_from([-30, -20, -10, -5, 5, 10, 20]), min_size=0, max_size=7))
    lines = [Line(n, a) for n, a in enumerate(amounts, start=1)]
    total = sum(amounts) if draw(st.booleans()) else draw(st.sampled_from([-60, -30, 0, 15]))
    parties = []
    for key in range(1, draw(st.integers(0, 3)) + 1):
        refs = draw(st.lists(st.integers(1, max(len(lines), 1)), max_size=2).map(frozenset))
        parties.append(
            Party(
                key,
                D + timedelta(days=draw(st.integers(0, 3))),
                draw(st.sampled_from([-60, -50, -40, -30, -20, -10, 0, 10, 20])),
                refs if lines else frozenset(),
            )
        )
    return lines, total, parties


def brute(lines: list[Line], total: int, parties: list[Party]) -> bool:
    """Is there any allocation: the whole-document match, or lines summing to the total divided exactly?"""
    if len(parties) == 1 and parties[0].amount == total:
        return True
    if sum(ln.amount for ln in lines) != total:
        return False
    for pick in product(range(len(parties) + 1), repeat=len(lines)):
        sums = [0] * len(parties)
        for ln, p in zip(lines, pick, strict=True):
            if p < len(parties):
                sums[p] += ln.amount
        if sums == [p.amount for p in parties]:
            return True
    return False


@given(worlds())
@settings(max_examples=300, deadline=None)
def test_an_allocation_sums_exactly_and_uses_each_line_once(
    world: tuple[list[Line], int, list[Party]],
) -> None:
    lines, total, parties = world
    found = allocate(lines, total, parties)
    if found is None:
        return
    by_number = {ln.number: ln.amount for ln in lines}
    assert set(found.assigned) <= set(by_number)  # a mapping: each line at most once
    assert set(found.assigned.values()) <= {p.key for p in parties}
    if len(parties) == 1 and parties[0].amount == total:
        assert set(found.assigned) == set(by_number)  # the whole-document match takes every line
        return
    for p in parties:
        assert sum(by_number[n] for n in found.of(p.key)) == p.amount
    if found.keeps:
        for p in parties:
            assert all(found.assigned.get(r) == p.key for r in p.refs if r in by_number)
    else:  # said not kept: some reference is not kept
        assert any(found.assigned.get(r) != p.key for p in parties for r in p.refs if r in by_number)


@given(worlds())
@settings(max_examples=300, deadline=None)
def test_an_allocation_is_found_whenever_one_exists(world: tuple[list[Line], int, list[Party]]) -> None:
    lines, total, parties = world
    if not parties:
        return
    assert (allocate(lines, total, parties) is not None) == brute(lines, total, parties)
