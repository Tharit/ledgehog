"""Splitting along a document's lines (spec/features/documents.md §6)."""

from __future__ import annotations

from fractions import Fraction

from hypothesis import given
from hypothesis import strategies as st

from app.core.resolution.allocation import DocLine, lines_for_entry, split_along_lines


def lines(*amounts: int) -> list[DocLine]:
    return [DocLine(i, a) for i, a in enumerate(amounts, 1)]


def split(entry: int, doc_lines: list[DocLine], total: int, **kw) -> list[tuple[int, int]] | None:  # noqa: ANN003
    return split_along_lines(
        entry,
        "EUR",
        kw.get("instructed"),
        kw.get("instructed_currency"),
        doc_lines,
        total,
        kw.get("currency", "EUR"),
    )


def test_original_takes_first_line_and_remainder() -> None:
    # lines -400 -300 -200, shipping -100 in the total
    assert split(-1000, lines(-400, -300, -200), -1000) == [(1, -500), (2, -300), (3, -200)]


def test_no_split_for_one_line() -> None:
    assert split(-1000, lines(-1000), -1000) is None
    assert split(-1000, [], -1000) is None


def test_no_split_when_total_does_not_match() -> None:
    assert split(-1000, lines(-400, -600), -999) is None
    assert split(-1000, lines(-400, -600), 1000) is None
    assert split(-1000, lines(-400, -600), -1000, currency="USD") is None


def test_no_split_when_original_share_is_zero_or_flips() -> None:
    assert split(-1000, lines(-100, -1000), -1000) is None  # remainder 0 -> share 0
    assert split(-1000, lines(-100, -1200), -1000) is None  # share +200
    assert split(1000, lines(100, 1200), 1000) is None


def test_refund_splits_with_its_sign() -> None:
    assert split(1000, lines(400, 300, 200), 1000) == [(1, 500), (2, 300), (3, 200)]


def test_instructed_currency_converts_proportionally() -> None:
    # 1100 USD document, charged 1000 EUR: line 550 USD -> 500 EUR
    got = split(-1000, lines(-550, -550), -1100, instructed=-1100, instructed_currency="USD", currency="USD")
    assert got == [(1, -500), (2, -500)]


def test_instructed_rounding_is_half_even() -> None:
    # 1 * 5/2 ... entry -5 over total -2: line -1 -> -2.5 -> -2 (even); line -3 -> -7.5 -> -8
    got = split(-5, lines(-1, -1), -2, instructed=-2, instructed_currency="USD", currency="USD")
    assert got == [(1, -3), (2, -2)]


def test_own_currency_wins_when_both_would_match() -> None:
    got = split_along_lines(-1000, "EUR", -1000, "EUR", lines(-400, -600), -1000, "EUR")
    assert got == [(1, -400), (2, -600)]


def test_lines_are_taken_in_line_order() -> None:
    got = split(-1000, [DocLine(3, -200), DocLine(1, -400), DocLine(2, -300)], -1000)
    assert got == [(1, -500), (2, -300), (3, -200)]


def test_lines_for_entry() -> None:
    ls = lines(-1, -2, -3)
    assert lines_for_entry(ls, 2) == [DocLine(2, -2)]
    assert lines_for_entry(ls, None) == ls


@st.composite
def cases(draw: st.DrawFn) -> tuple[int, list[DocLine], int, bool]:
    entry = draw(st.integers(-100_000, 100_000).filter(bool))
    sign = 1 if entry > 0 else -1
    n = draw(st.integers(2, 6))
    amounts = [sign * draw(st.integers(0, 50_000)) for _ in range(n)]
    instructed = draw(st.booleans())
    if instructed:
        total = sign * draw(st.integers(1, 200_000))
    else:
        total = entry
    return entry, lines(*amounts), total, instructed


@given(cases())
def test_properties(case: tuple[int, list[DocLine], int, bool]) -> None:
    entry, doc_lines, total, instructed = case
    got = (
        split_along_lines(entry, "EUR", total, "USD", doc_lines, total, "USD")
        if instructed
        else split_along_lines(entry, "EUR", None, None, doc_lines, total, "EUR")
    )
    if got is None:
        return
    assert sum(a for _, a in got) == entry
    assert [n for n, _ in got] == [line.line_no for line in doc_lines]
    first = got[0][1]
    assert first != 0 and (first > 0) == (entry > 0)
    for (_, amount), line in zip(got[1:], doc_lines[1:], strict=True):
        if instructed:
            exact = Fraction(line.amount * entry, total)
            assert abs(amount - exact) <= Fraction(1, 2)
            if abs(amount - exact) == Fraction(1, 2):
                assert amount % 2 == 0  # half-even
        else:
            assert amount == line.amount
