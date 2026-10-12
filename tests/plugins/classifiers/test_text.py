from app.core.plugins.text import jaccard, normalise_name, tokens


def test_normalise_name_keeps_punctuation_and_collapses_space() -> None:
    assert normalise_name("  PAYPAL   *Seeed Dev ") == "paypal *seeed dev"
    assert normalise_name("ＡＢＣ") == "abc"
    assert normalise_name(None) == ""


def test_tokens_rules() -> None:
    assert tokens("PayPal *SEEED-Dev", "Order 12345 ab x1y Danke") == {
        "paypal",
        "seeed",
        "dev",
        "order",
        "danke",
    }
    assert tokens(None, None) == frozenset()
    assert tokens("ab", "x2z 99") == frozenset()


def test_jaccard() -> None:
    assert jaccard({"a", "b"}, {"b", "c"}) == 1 / 3
    assert jaccard(set(), set()) == 0.0
    assert jaccard({"a"}, {"a"}) == 1.0
