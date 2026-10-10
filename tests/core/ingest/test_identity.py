from __future__ import annotations

import dataclasses
from datetime import date

from hypothesis import given
from hypothesis import strategies as st

from app.core.ingest.identity import (
    ContentHash,
    SourceId,
    assign_ordinals,
    canonical_text,
    content_hash,
    identity_of,
)
from app.core.plugins.importer import IncomingRow

D = date(2026, 3, 14)
text = st.one_of(st.none(), st.text(max_size=30))


def row(**kw: object) -> IncomingRow:
    base: dict[str, object] = dict(
        amount_minor=-500,
        currency="EUR",
        booked_on=D,
        source_format="csv:test",
        raw={"line": 1},
    )
    base.update(kw)
    return IncomingRow(**base)  # type: ignore[arg-type]


def h(**kw: object) -> bytes:
    args: dict[str, object] = dict(
        amount_minor=-500,
        currency="EUR",
        booked_on=D,
        counterparty_ref="DE89370400440532013000",
        purpose="Bakery",
        ordinal=0,
    )
    args.update(kw)
    return content_hash(**args)  # type: ignore[arg-type]


# --- canonical_text -------------------------------------------------------


def test_none_and_empty_are_equal() -> None:
    assert canonical_text(None) == canonical_text("") == ""


def test_whitespace_punctuation_case_removed() -> None:
    assert canonical_text("  Hello,\n World-1! ") == "helloworld1"


def test_iban_spacing() -> None:
    assert canonical_text("DE89 3704 0044 0532 0130 00") == canonical_text("de89370400440532013000")


def test_sharp_s_and_nfkc_variants() -> None:
    assert canonical_text("Straße") == canonical_text("STRASSE")
    assert canonical_text("ＡＢＣ１２３") == "abc123"  # full-width
    assert canonical_text("ﬁnal") == "final"  # ligature
    assert canonical_text("é") == canonical_text("é") == "é"


def test_combining_marks_standing_alone_are_dropped() -> None:
    assert canonical_text("á̂".replace("a", "")) == ""


@given(text)
def test_canonical_idempotent_and_alnum(s: str | None) -> None:
    c = canonical_text(s)
    assert canonical_text(c) == c
    assert all(ch.isalnum() for ch in c)


@given(st.text(max_size=30), st.lists(st.sampled_from([" ", "\t", "\n", "-", ".", ",", "/"]), max_size=5))
def test_separator_noise_is_invisible(s: str, noise: list[str]) -> None:
    assert canonical_text(s + "".join(noise)) == canonical_text(s)
    assert canonical_text("".join(noise) + s) == canonical_text(s)


# --- content_hash ---------------------------------------------------------


@given(text, text)
def test_hash_equal_for_text_noise_variants(ref: str | None, purpose: str | None) -> None:
    noisy_ref = None if ref is None else f" {ref.upper()}-.\n"
    noisy_purpose = None if purpose is None else f"\t{purpose.lower()} ,"
    assert h(counterparty_ref=ref, purpose=purpose) == h(counterparty_ref=noisy_ref, purpose=noisy_purpose)


def test_none_equals_empty_in_hash() -> None:
    assert h(purpose=None) == h(purpose="") == h(purpose=" - ")
    assert h(counterparty_ref=None) == h(counterparty_ref="")


@given(st.text(alphabet="abc123", min_size=1, max_size=12), st.integers(min_value=0, max_value=12))
def test_boundary_shift_changes_hash(s: str, k: int) -> None:
    k = k % (len(s) + 1)
    a, b = s[:k], s[k:]
    # Move the boundary one character to the right: same concatenation.
    if not b:
        return
    assert h(counterparty_ref=a, purpose=b) != h(counterparty_ref=a + b[0], purpose=b[1:])


def test_swapping_fields_changes_hash() -> None:
    assert h(counterparty_ref="abc", purpose="def") != h(counterparty_ref="def", purpose="abc")
    assert h(counterparty_ref="abc", purpose="") != h(counterparty_ref="", purpose="abc")


@given(st.integers(-(10**12), 10**12), st.integers(-(10**12), 10**12))
def test_each_hashed_field_matters(a: int, b: int) -> None:
    base = h()
    assert h(amount_minor=-499) != base
    assert h(currency="USD") != base
    assert h(booked_on=date(2026, 3, 15)) != base
    assert h(counterparty_ref="DE00") != base
    assert h(purpose="Other") != base
    assert h(ordinal=1) != base
    assert (h(amount_minor=a) == h(amount_minor=b)) == (a == b)


def test_hash_is_32_bytes() -> None:
    assert len(h()) == 32


# --- IncomingRow / excluded fields ---------------------------------------

EXCLUDED = {
    "end_to_end_id": "E2E-1",
    "mandate_ref": "MREF-9",
    "counterparty_name": "Some Name",
    "instructed_amount_minor": 1234,
    "instructed_currency": "USD",
    "value_on": date(2026, 3, 20),
    "source_format": "camt053",
    "raw": {"other": "payload"},
    "booking_text": "LASTSCHRIFT",
    "counterparty_bic": "COBADEFF",
}


def ordinal_and_identity(r: IncomingRow) -> object:
    return identity_of(r, assign_ordinals([r])[0])


def test_excluded_fields_change_nothing() -> None:
    base = row(counterparty_ref="DE00", purpose="x")
    for name, value in EXCLUDED.items():
        changed = dataclasses.replace(base, **{name: value})
        assert ordinal_and_identity(changed) == ordinal_and_identity(base), name


def test_incoming_row_is_frozen() -> None:
    r = row()
    try:
        r.amount_minor = 1  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("IncomingRow must be frozen")


# --- ordinals -------------------------------------------------------------


def test_ordinals_count_identical_rows_in_order() -> None:
    a = row(purpose="Bakery")
    b = row(purpose="Other")
    assert assign_ordinals([a, b, a, a, b]) == [0, 0, 1, 2, 1]


def test_ordinals_group_on_canonicalised_values() -> None:
    a = row(purpose="Bakery", counterparty_ref="DE89 3704")
    b = row(purpose=" bakery.", counterparty_ref="de893704", end_to_end_id="x")
    assert assign_ordinals([a, b]) == [0, 1]
    assert identity_of(a, 0) != identity_of(b, 1)


def test_ordinals_none_equals_empty() -> None:
    assert assign_ordinals([row(purpose=None), row(purpose="")]) == [0, 1]


def test_ordinals_differ_by_amount_date_currency() -> None:
    rows = [row(), row(amount_minor=-501), row(booked_on=date(2026, 3, 15)), row(currency="USD")]
    assert assign_ordinals(rows) == [0, 0, 0, 0]


def test_source_id_rows_get_zero_and_do_not_count() -> None:
    plain = row()
    withid = row(source_id="A1")
    assert assign_ordinals([withid, plain, withid, plain]) == [0, 0, 0, 1]


@given(st.lists(st.sampled_from(["a", "b", "c"]), max_size=15))
def test_ordinals_deterministic_order_preserving(purposes: list[str]) -> None:
    rows = [row(purpose=p) for p in purposes]
    first = assign_ordinals(rows)
    assert first == assign_ordinals(list(rows))
    assert len(first) == len(rows)
    for p in set(purposes):
        assert [o for o, q in zip(first, purposes, strict=True) if q == p] == list(range(purposes.count(p)))


@given(st.lists(st.sampled_from(["a", "b"]), max_size=10), st.sampled_from(["a", "b"]))
def test_ordinals_stable_when_later_delivery_adds_a_row(purposes: list[str], extra: str) -> None:
    earlier = [row(purpose=p) for p in purposes]
    later = [*earlier, row(purpose=extra)]
    before = assign_ordinals(earlier)
    after = assign_ordinals(later)
    assert after[:-1] == before
    assert after[-1] == purposes.count(extra)
    ids = [identity_of(r, o) for r, o in zip(later, after, strict=True)]
    assert len(set(ids)) == len(ids)  # distinct payments stay distinct
    old_ids = [identity_of(r, o) for r, o in zip(earlier, before, strict=True)]
    assert ids[:-1] == old_ids  # earlier rows keep identity


# --- identity_of ----------------------------------------------------------


@given(st.one_of(st.none(), st.text(min_size=1, max_size=10)), st.integers(0, 5))
def test_identity_is_exactly_one_kind(source_id: str | None, ordinal: int) -> None:
    ident = identity_of(row(source_id=source_id), ordinal)
    if source_id is None:
        assert isinstance(ident, ContentHash)
        assert len(ident.value) == 32
    else:
        assert isinstance(ident, SourceId)
        assert ident.value == source_id


def test_source_id_is_the_identity_not_a_hash_input() -> None:
    a = identity_of(row(source_id="A1"), 0)
    assert a == identity_of(row(source_id="A1", purpose="changed", amount_minor=-1), 7)
    assert a != identity_of(row(source_id="A2"), 0)


def test_content_hash_hex_matches_value() -> None:
    ident = identity_of(row(), 0)
    assert isinstance(ident, ContentHash)
    assert bytes.fromhex(ident.hex()) == ident.value
