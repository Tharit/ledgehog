"""The line allocation of a document over transactions (spec/features/documents.md §3, §4)."""

from __future__ import annotations

from datetime import date, timedelta

from app.core.matching import MAX_PARTIAL_LINES, Line, Party, allocate

D = date(2026, 3, 10)


def lines(*amounts: int) -> list[Line]:
    return [Line(n, a) for n, a in enumerate(amounts, start=1)]


def party(key: int, amount: int, day: int = 0, refs: tuple[int, ...] = ()) -> Party:
    return Party(key, D + timedelta(days=day), amount, frozenset(refs))


def assigned(found: object) -> dict[int, int]:
    assert found is not None
    return dict(found.assigned)  # type: ignore[attr-defined]


def test_a_whole_document_match_takes_every_line_however_they_sum() -> None:
    found = allocate(lines(-30, -20), -100, [party(1, -100)])  # the lines sum to -50: shipping is the rest
    assert assigned(found) == {1: 1, 2: 1} and found is not None and found.keeps
    assert assigned(allocate([], -100, [party(1, -100)])) == {}  # a document without lines


def test_the_whole_document_exception_is_for_a_single_transaction_only() -> None:
    assert allocate(lines(-30, -20), -100, [party(1, -100), party(2, -30)]) is None


def test_a_partial_match_needs_lines_that_sum_to_the_total() -> None:
    assert allocate(lines(-30, -20), -60, [party(1, -30)]) is None
    assert assigned(allocate(lines(-30, -20), -50, [party(1, -30)])) == {1: 1}  # line 2 is not yet charged


def test_a_partial_match_is_possible_up_to_twenty_lines() -> None:
    assert MAX_PARTIAL_LINES == 20
    twenty = lines(*[-10] * 20)
    assert assigned(allocate(twenty, -200, [party(1, -30)])) == {1: 1, 2: 1, 3: 1}
    assert allocate(lines(*[-10] * 21), -210, [party(1, -30)]) is None
    # the whole-document match has no such limit
    assert assigned(allocate(lines(*[-10] * 21), -210, [party(1, -210)])) == {n: 1 for n in range(1, 22)}


def test_charges_that_divide_the_lines_exactly() -> None:
    found = allocate(lines(-30, -20), -50, [party(1, -30), party(2, -20, day=1)])
    assert assigned(found) == {1: 1, 2: 2}
    assert allocate(lines(-30, -20), -50, [party(1, -30), party(2, -10, day=1)]) is None  # -10 is no sum
    assert allocate(lines(-30, -20), -50, [party(1, -30), party(2, -30, day=1)]) is None  # a line twice


def test_opposite_sign_lines_take_part_in_the_sums() -> None:
    # items -30 and -20 and a coupon of +10: the total is -40 and a charge of -40 takes all three
    assert assigned(allocate(lines(-30, -20, 10), -40, [party(1, -40)])) == {1: 1, 2: 1, 3: 1}
    # two charges of -20: the first line (-30, with the coupon +10 it makes -20) goes to the earliest
    found = allocate(lines(-30, -20, 10), -40, [party(1, -20), party(2, -20, day=1)])
    assert assigned(found) == {1: 1, 2: 2, 3: 1}
    # all lines take part, the coupon too: a charge of +10 is the coupon's own, -25 is no sum of lines
    assert assigned(allocate(lines(-30, -20, 10), -40, [party(1, 10)])) == {3: 1}
    assert allocate(lines(-30, -20, 10), -40, [party(1, -25)]) is None


def test_the_proposal_goes_line_by_line_to_the_earliest_transaction() -> None:
    # two charges of -10, one of -20 hold four lines of -10; line 1 goes to the earliest charge
    found = allocate(
        lines(-10, -10, -10, -10), -40, [party(3, -20, day=5), party(1, -10, day=0), party(2, -10, day=1)]
    )
    assert assigned(found) == {1: 1, 2: 2, 3: 3, 4: 3}
    # equal days: the lower key first
    found = allocate(lines(-10, -10), -20, [party(2, -10), party(1, -10)])
    assert assigned(found) == {1: 1, 2: 2}
    # the order of the parties given changes nothing
    again = allocate(lines(-10, -10), -20, [party(1, -10), party(2, -10)])
    assert assigned(again) == assigned(found)


def test_a_line_goes_to_none_where_no_charge_takes_it() -> None:
    found = allocate(lines(-10, -20, -30), -60, [party(1, -30)])
    assert found is not None and found.assigned == {1: 1, 2: 1}  # line 3 is not yet charged
    assert found.of(1) == [1, 2]


def test_committed_references_are_kept_first_then_relaxed() -> None:
    ls = lines(-10, -10)
    # without references the first line goes to the earlier charge (1); charge 2 references line 1
    found = allocate(ls, -20, [party(1, -10, day=0), party(2, -10, day=1, refs=(1,))])
    assert found is not None and found.keeps
    assert found.assigned == {1: 2, 2: 1}
    # a reference that cannot be kept (charge 2 is -10 but references both lines): relaxed, not kept
    found = allocate(ls, -20, [party(1, -10, day=0), party(2, -10, day=1, refs=(1, 2))])
    assert found is not None and not found.keeps
    assert found.assigned == {1: 1, 2: 2}


def test_a_single_whole_match_keeps_its_own_references() -> None:
    found = allocate(lines(-30, -20), -100, [party(1, -100, refs=(2,))])
    assert found is not None and found.keeps


def test_no_transaction_is_the_empty_allocation() -> None:
    found = allocate(lines(-30, -20), -50, [])
    assert found is not None and found.assigned == {} and found.keeps


def test_refunds_match_refund_documents_with_their_sign() -> None:
    assert assigned(allocate(lines(10, 20), 30, [party(1, 10)])) == {1: 1}
    assert allocate(lines(10, 20), 30, [party(1, -10)]) is None
    assert allocate(lines(-10, -20), -30, [party(1, 10)]) is None


def test_a_hard_instance_is_fast() -> None:
    # twenty equal lines and several charges: pruning and the failure memory keep it instant
    ls = lines(*[-7] * 20)
    parties = [party(i, -7 * k, day=i) for i, k in enumerate((3, 5, 4, 6, 1), start=1)]
    found = allocate(ls, -140, parties)
    assert found is not None
    assert len(found.assigned) == 19
    assert allocate(ls, -140, [*parties, party(9, -13, day=9)]) is None
