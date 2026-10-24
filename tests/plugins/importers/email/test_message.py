"""Reading one message (email.md §3, §4): inner messages, dates, identity, text, PDFs."""

from __future__ import annotations

from datetime import date

from app.plugins.importers.email.message import (
    body_text,
    header_date,
    identity_of,
    inner_messages,
    message_date,
    normalise_message_id,
    parse_message,
    pdf_parts,
)
from tests.plugins.importers.email.helpers import FAMILY, make_message


def parsed(msg):  # type: ignore[no-untyped-def]
    return parse_message(msg.as_bytes())


def test_a_message_without_rfc822_parts_is_its_own_inner_message():
    outer = parsed(make_message())
    assert inner_messages(outer) == [outer]


def test_every_first_level_rfc822_part_is_an_inner_message_in_order():
    a, b = make_message(subject="A", message_id="<a@s>"), make_message(subject="B", message_id="<b@s>")
    outer = parsed(make_message(sender=FAMILY, html=None, text="see", attached=[a, b]))
    assert [str(m["Subject"]) for m in inner_messages(outer)] == ["A", "B"]


def test_only_the_first_level_counts_a_forward_inside_a_forward_is_part_of_the_inner_one():
    deep = make_message(subject="deep", message_id="<deep@s>")
    middle = make_message(sender=FAMILY, subject="middle", message_id="<mid@s>", html=None, attached=[deep])
    outer = parsed(make_message(sender=FAMILY, html=None, text="see", attached=[middle]))
    assert [str(m["Subject"]) for m in inner_messages(outer)] == ["middle"]


def test_an_inline_quoted_forward_is_the_message_itself():
    outer = parsed(
        make_message(sender=FAMILY, text="---------- Forwarded message ----------\nFrom: shop\nTotal 5")
    )
    assert inner_messages(outer) == [outer]


def test_identity_is_the_message_id_without_brackets_or_whitespace_else_the_hash_of_the_bytes():
    assert normalise_message_id("  <abc@x> \n") == "abc@x"
    assert normalise_message_id("<>") is None and normalise_message_id(None) is None
    assert identity_of(parsed(make_message(message_id="<abc@x>"))) == "abc@x"
    raw = make_message(message_id=None).as_bytes()
    a, b = identity_of(parse_message(raw), raw), identity_of(parse_message(raw + b"x"), raw + b"x")
    assert len(a) == 64 and a != b and a == identity_of(parse_message(raw), raw)


def test_the_date_is_the_calendar_date_in_the_headers_own_offset_never_converted():
    assert header_date(make_message(sent="Thu, 1 Jan 2026 23:30:00 -0500")) == date(
        2026, 1, 1
    )  # UTC: the 2nd
    assert header_date(make_message(sent="Fri, 2 Jan 2026 00:30:00 +0200")) == date(
        2026, 1, 2
    )  # UTC: the 1st


def test_the_date_falls_back_from_the_inner_to_the_outer_to_the_arrival():
    arrived = date(2026, 1, 9)
    inner = make_message(sent="Mon, 5 Jan 2026 10:00:00 +0000")
    no_date = make_message(sent=None)
    outer = make_message(sent="Tue, 6 Jan 2026 10:00:00 +0000")
    assert message_date(inner, outer, arrived) == date(2026, 1, 5)
    assert message_date(no_date, outer, arrived) == date(2026, 1, 6)
    assert message_date(no_date, make_message(sent=None), arrived) == arrived
    assert message_date(make_message(sent="not a date"), make_message(sent="also not"), arrived) == arrived


def test_an_inline_forward_carries_the_date_it_was_forwarded():
    forward = parsed(
        make_message(sender=FAMILY, sent="Wed, 14 Jan 2026 08:00:00 +0000", text="Fwd: order of 3 Jan")
    )
    assert message_date(forward, forward, date(2026, 1, 14)) == date(2026, 1, 14)


def test_the_text_is_the_html_body_through_the_converter_else_plain():
    both = parsed(
        make_message(html="<p>A&amp;B</p><table><tr><td>x</td><td>1.00</td></tr></table>", text="plain")
    )
    assert body_text(both) == "A&B\n\nx\t1.00"
    assert (
        body_text(parsed(make_message(html=None, text="just   plain\r\n\r\n\r\n\r\nend  ")))
        == "just   plain\n\nend"
    )
    assert body_text(parsed(make_message(html="<p>only html</p>", text=None))) == "only html"


def test_an_html_body_without_text_falls_back_to_plain_and_no_text_is_none():
    assert body_text(parsed(make_message(html='<img src="x"><script>x</script>', text="plain"))) == "plain"
    assert (
        body_text(parsed(make_message(html=None, text=None, pdfs=[("a.pdf", "application", "pdf")]))) is None
    )


def test_pdfs_are_pdf_parts_or_octet_streams_named_pdf_at_most_three():
    msg = parsed(
        make_message(
            pdfs=[
                ("a.pdf", "application", "pdf"),
                ("b.PDF", "application", "octet-stream"),
                ("c.bin", "application", "octet-stream"),
                ("d.pdf", "application", "pdf"),
                ("e.pdf", "application", "pdf"),
            ]
        )
    )
    found = pdf_parts(msg)
    assert [p.name for p in found] == ["a.pdf", "b.PDF", "d.pdf"]
    assert found[0].data.startswith(b"%PDF-1.4")


def test_pdfs_of_an_inner_message_are_its_own_not_the_outers():
    inner = make_message(pdfs=[("inner.pdf", "application", "pdf")], message_id="<i@s>")
    outer = parsed(
        make_message(
            sender=FAMILY, html=None, text="x", pdfs=[("outer.pdf", "application", "pdf")], attached=[inner]
        )
    )
    (only,) = inner_messages(outer)
    assert [p.name for p in pdf_parts(only)] == ["inner.pdf"]
