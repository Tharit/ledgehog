from app.core.plugins.text import jaccard, normalise_name, purpose_tokens


def test_normalise_name_keeps_punctuation_and_collapses_space() -> None:
    assert normalise_name("  PAYPAL   *Seeed Dev ") == "paypal *seeed dev"
    assert normalise_name("ＡＢＣ") == "abc"
    assert normalise_name(None) == ""


def test_purpose_tokens_rules() -> None:
    assert purpose_tokens("Order 12345 ab x1y Danke-Schön ÄÖ") == {"order", "danke", "schön"}
    assert purpose_tokens("ＤＡＮＫＥ  Danke") == {"danke"}  # NFKC, casefolded
    assert purpose_tokens(None) == frozenset()
    assert purpose_tokens("x2z 99 ab") == frozenset()


def test_jaccard() -> None:
    assert jaccard({"a", "b"}, {"b", "c"}) == 1 / 3
    assert jaccard(set(), set()) == 0.0
    assert jaccard({"a"}, {"a"}) == 1.0
