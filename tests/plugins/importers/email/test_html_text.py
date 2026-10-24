"""The converter (email.md §4), ported from the spike's cases."""

from __future__ import annotations

from app.plugins.importers.email.html_text import html_to_text

HTML = """<!doctype html><html><head><title>T</title><style>.a{color:red}</style></head>
<body class="x" style="margin:0"><!-- c --><script>var x=1;</script>
<img src="http://t/p.gif" alt="Shop Logo" width="1">
<p style="a">Order <b class="k">#123</b> &amp; thanks &euro;</p>
<table><tr><td href="u">Widget</td><td>2</td><td>3.50</td></tr></table>
<a href="http://x/y?z">Total 7.00 EUR</a></body></html>"""

AMAZON = (
    '<span role="region" aria-label="{amount=43.55, currencyCode={smallestAmount=0.01, code=EUR}}" '
    'style="font-size:18px">43<sup style="font-size:10px">55</sup><sup style="font-size:10px">€</sup> </span>'
)


def test_the_sample_loses_presentation_and_keeps_text_cells_alt_and_decoded_entities():
    text = html_to_text(HTML)
    assert "Widget\t2\t3.50" in text
    assert "[Shop Logo]" in text
    assert "Order #123 & thanks €" in text
    assert "Total 7.00 EUR" in text
    assert "<" not in text and "var x" not in text and "&amp;" not in text
    assert "color:red" not in text and "T\n" not in text.split("\n")[0:1]


def test_superscript_is_marked_caret_and_subscript_underscore():
    assert "43^55^€" in html_to_text(AMAZON)
    assert "m^2" in html_to_text("m<sup>2</sup>")
    assert "H_2O" in html_to_text("H<sub>2</sub>O")


def test_a_dropped_element_drops_its_markers_too():
    assert "^" not in html_to_text("<script>a<sup>b</script>x")
    assert html_to_text("<style>b<sup>c</style>x") == "x"


def test_blocks_become_lines_list_items_dashes_and_blank_lines_collapse():
    text = html_to_text(
        "<div>a</div><div></div><div></div><div></div><ul><li>one</li><li>two</li></ul><p>b<br>c</p>"
    )
    assert text == "a\n\n- one\n\n- two\n\nb\nc"  # the spike's: runs of 3+ newlines become one blank line


def test_empty_cells_go_and_whitespace_including_nbsp_collapses():
    assert (
        html_to_text("<table><tr><td>a</td><td> &nbsp; </td><td></td><td>b   c</td></tr></table>") == "a\tb c"
    )


def test_an_image_without_alt_leaves_nothing():
    assert html_to_text('<img src="x"><img alt="  " src="y">z') == "z"


def test_other_tags_are_dropped_and_nothing_is_interpreted():
    assert html_to_text('<a href="http://x">link</a> <span>text</span> <b>bold</b>') == "link text bold"
