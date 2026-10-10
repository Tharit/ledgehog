"""Known-answer tests for the content hash and canonical text (spec §5.2).

These digests protect STORED hashes: every `source_transaction.content_hash` already in a
database is a function of exactly these rules. If one of these tests fails, the change
alters the identity of history and needs a rehash migration from `raw` (spec §5.2 as being
amended), not an edit of the expected value here.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.ingest.identity import canonical_text, content_hash

D = date(2026, 3, 14)

# (amount, counterparty_ref, purpose, ordinal) -> lowercase hex digest, currency EUR, booked_on D
GOLDEN: list[tuple[str, tuple[int, str | None, str | None, int], str]] = [
    (
        "plain row, no text",
        (-500, None, None, 0),
        "df311c38d18ec77cb425b11bef8e69fda9f1b49cd4317887a519121753d1e9d0",
    ),
    (
        "IBAN with spaces",
        (-500, "DE89 3704 0044 0532 0130 00", "rent", 0),
        "aa94807e987c09bbef9ef83dad7c4ab54c17f6dd8ebb6fa5137a5da0be1dc5cd",
    ),
    (
        "IBAN without spaces: same digest",
        (-500, "DE89370400440532013000", "rent", 0),
        "aa94807e987c09bbef9ef83dad7c4ab54c17f6dd8ebb6fa5137a5da0be1dc5cd",
    ),
    (
        "sharp s folds to ss",
        (-500, "Straße", "", 0),
        "31d17562857aba0d5b8cf50d4806e8d7c5c77e0230acb4930cb4e074d77c4dab",
    ),
    (
        "upper case equals it",
        (-500, "STRASSE", "", 0),
        "31d17562857aba0d5b8cf50d4806e8d7c5c77e0230acb4930cb4e074d77c4dab",
    ),
    (
        "counterparty 'ab', purpose 'c'",
        (-500, "ab", "c", 0),
        "bf7b40ba838ac1ac9fa03a6b5b2ed69d65d92a42a0ad07ed9e5bbbc58aadbab6",
    ),
    (
        "counterparty 'a', purpose 'bc': the boundary matters",
        (-500, "a", "bc", 0),
        "9e02b97bd97557c81f882bbc69e8b86714327b516ea4496906c2c03f9ca553c8",
    ),
    (
        "ordinal 1",
        (-500, "ab", "c", 1),
        "d0f04ca528c90a39f2e6997af4b30409be509d25c69694c1fb8e98caf5b34c45",
    ),
    (
        "empty text equals absent text",
        (-500, "", None, 0),
        "df311c38d18ec77cb425b11bef8e69fda9f1b49cd4317887a519121753d1e9d0",
    ),
]


@pytest.mark.parametrize(("label", "args", "digest"), GOLDEN, ids=[g[0] for g in GOLDEN])
def test_content_hash_is_frozen(
    label: str, args: tuple[int, str | None, str | None, int], digest: str
) -> None:
    amount, ref, purpose, ordinal = args
    assert content_hash(amount, "EUR", D, ref, purpose, ordinal).hex() == digest


def test_the_boundary_and_the_ordinal_change_the_digest() -> None:
    digests = {
        g[2]
        for g in GOLDEN
        if g[0]
        in (
            "counterparty 'ab', purpose 'c'",
            "counterparty 'a', purpose 'bc': the boundary matters",
            "ordinal 1",
        )
    }
    assert len(digests) == 3


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("DE89 3704 0044 0532 0130 00", "de89370400440532013000"),
        ("Straße 5!", "strasse5"),
        ("Ｆｕｌｌ-Width １２", "fullwidth12"),
        ("é", "é"),  # composes under NFKC, survives
        ("a⃝ b", "ab"),  # a mark that does not compose is dropped
        (None, ""),
        ("  ", ""),
    ],
)
def test_canonical_text_is_frozen(raw: str | None, canonical: str) -> None:
    assert canonical_text(raw) == canonical
