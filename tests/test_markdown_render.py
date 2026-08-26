"""The one markdown converter, exercised construct by construct.

Why this file exists at all: the complaint that produced this work was raw
`**cost**` on a client-facing page. That was never a template bug — it was
three separate half-converters (`_markdown_lite_to_html`, `_md_preview`, and
"just interpolate the authored string") living in `vsm/ui/app.py`, each
covering a different subset of markdown, each leaking a different subset of
source syntax. The structural fix is that there is now exactly one converter,
`vsm.ui.render.markdown_to_html`, and no surface is allowed its own.

Every test below is written to fail if the behaviour it names breaks. A test
that only asserted "the output is non-empty" would pass against the old
converter for every construct it silently dropped, which is precisely how
this defect survived a green suite.
"""

from __future__ import annotations

import re

import pytest

from vsm.ui.render import (
    markdown_excerpt_html,
    markdown_inline_html,
    markdown_paragraphs,
    markdown_sections,
    markdown_to_html,
)

#: (name, markdown in, tag that must appear, source token that must NOT).
#: The second half of each row is the half that matters: producing *a* tag is
#: easy, and the failure mode being guarded is source syntax surviving
#: alongside it.
CONSTRUCTS = [
    ("atx heading", "## A heading", "<h2", "## "),
    ("deep heading", "#### Fourth level", "<h4", "#### "),
    ("setext heading", "A heading\n=========", "<h1", "===="),
    ("bold", "**cost** matters", "<strong>", "**"),
    ("alt bold", "__cost__ matters", "<strong>", "__"),
    ("italic", "an *emerging* theme", "<em>", "*"),
    ("bold italic", "***very strong***", "<strong><em>", "***"),
    ("strikethrough", "~~withdrawn~~", "<del>", "~~"),
    ("code span", "the `hcp_discussion` kind", "<code>", "`"),
    ("code fence", "```\nsome code\n```", "<pre", "```"),
    ("link", "see [the source](https://example.org)", '<a href="https://example.org"', "]("),
    ("autolink", "see <https://example.org>", '<a href="https://example.org"', "&lt;https"),
    ("bare url", "see https://example.org now", '<a href="https://example.org"', "&gt;"),
    ("image", "![a chart](https://example.org/c.png)", "<a href=", "!["),
    ("bullet list", "- one\n- two", "<li>", "- "),
    ("star bullet list", "* one\n* two", "<li>", "* "),
    ("plus bullet list", "+ one\n+ two", "<li>", "+ "),
    ("ordered list", "1. first\n2. second", "<ol", "1. "),
    ("blockquote", "> a quoted sentence", "<blockquote", "&gt; "),
    ("table", "| a | b |\n|---|---|\n| 1 | 2 |", "<table", "|---|"),
    ("thematic break", "before\n\n---\n\nafter", "<hr", "---"),
    ("footnote-ish brackets", "a claim [1]", "<p", "]("),
]


@pytest.mark.parametrize("name, source, must_contain, must_not_contain", CONSTRUCTS)
def test_every_construct_renders_as_markup_and_leaks_no_source(
    name, source, must_contain, must_not_contain
):
    html = markdown_to_html(source)
    assert must_contain in html, f"{name}: expected {must_contain!r} in {html!r}"
    assert must_not_contain not in html, f"{name}: leaked {must_not_contain!r} in {html!r}"


def test_a_fourth_level_heading_does_not_hang_the_converter():
    """The regression this one names precisely.

    The previous converter's paragraph branch collected lines with a guard
    that excluded any line starting with `#`. On a `####` heading — which its
    heading branch did not match — the block collected nothing, the index
    never advanced, and it appended `<p></p>` forever. An LLM writing a
    fourth-level sub-heading hung the report route: not a 500, an unbounded
    loop on a live page.

    `REPORT_SCHEMA` types a section body as an unconstrained string, so this
    is reachable, not theoretical.
    """
    for pathological in ("#### Sub-sub heading", "#hashtag in prose", "##Tight", "#", "######## too deep"):
        html = markdown_to_html(pathological)  # must simply return
        assert "<p></p><p></p>" not in html, pathological
        assert html != ""


def test_headings_are_emitted_at_the_base_level_they_are_given():
    """A whole artifact rendered inside a page must not mint a second `<h1>`.

    The report page used to carry four of them — its own, plus one from each
    of the three markdown artifacts it embedded — and three h2->h1 jumps,
    which flattens the document outline entirely.
    """
    html = markdown_to_html("# Title\n\n## Section\n\n### Detail", base_level=3)
    assert "<h1" not in html and "<h2" not in html
    assert "<h3" in html and "<h4" in html and "<h5" in html


def test_heading_levels_clamp_at_h6_rather_than_emitting_h7():
    html = markdown_to_html("###### Deep", base_level=4)
    assert "<h6" in html and "<h7" not in html


def test_drop_title_removes_only_the_documents_own_leading_h1():
    html = markdown_to_html("# Methodology\n\n## Where\n\nbody", base_level=3, drop_title=True)
    assert "Methodology" not in html
    assert "Where" in html and "body" in html


def test_an_escaped_pipe_stays_inside_its_cell():
    """A bare `split("|")` hands the table one cell too many and shifts every
    column after it. `report.py` interpolates LLM-authored theme names and
    collected URLs straight into pipe rows."""
    html = markdown_to_html("| a | b |\n|---|---|\n| x \\| y | 2 |")
    assert html.count("<td") == 2
    assert "x | y" in html


def test_a_short_row_is_padded_rather_than_left_ragged():
    html = markdown_to_html("| a | b | c |\n|---|---|---|\n| 1 |")
    assert html.count("<td") == 3


def test_a_numeric_column_is_right_aligned_and_a_text_column_is_not():
    html = markdown_to_html("| theme | volume |\n|---|---|\n| cost | 12 |\n| access | 4 |")
    assert '<td class="num">12</td>' in html
    assert "<td>cost</td>" in html


def test_every_table_carries_a_caption_and_scoped_column_headers():
    html = markdown_to_html("## Themes observed\n\n| a | b |\n|---|---|\n| 1 | 2 |")
    assert "<caption" in html
    assert 'scope="col"' in html
    # The caption is taken from the heading the table sits under, so it says
    # what the table is rather than "Table".
    assert "Themes observed" in html


def test_identifiers_with_underscores_are_not_turned_into_emphasis():
    """`kind_mix` and `venue_mix` keys are exactly the shape that a naive
    `_..._` rule swallows: the first underscore pairs with the next unrelated
    one and eats the space and comma between them."""
    for line in (
        "kind mix: hcp_discussion (3), patient_community (2)",
        "venue mix: a_b, c_d",
        "run_id sig-h2_1 captured",
        "100_000 patients",
    ):
        assert markdown_to_html(line) == f'<p class="doc-p">{line}</p>'


def test_a_backslash_escape_produces_the_literal_and_no_backslash():
    html = markdown_to_html(r"\*not emphasis\* and \_not either\_")
    assert "<em>" not in html
    assert "\\" not in html
    assert "*not emphasis*" in html


def test_html_in_the_source_is_escaped_not_executed():
    html = markdown_to_html("a <script>alert(1)</script> b")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_a_dangerous_link_scheme_is_refused_and_the_label_survives():
    html = markdown_to_html("[click me](javascript:alert(1))")
    assert "javascript:" not in html
    assert "click me" in html
    assert "](" not in html


def test_inline_rendering_produces_no_wrapping_paragraph():
    """A finding's claim ends with its reference marks *inside* the sentence.
    Wrapped in a block, the references detach onto their own line and read as
    a footer rather than as part of the claim."""
    out = markdown_inline_html("**cost** is corroborated")
    assert out == "<strong>cost</strong> is corroborated"
    assert "<p" not in out


def test_sections_split_a_document_at_its_headings_in_order():
    sections = markdown_sections("# T\n\nlead\n\n## A\n\nx\n\n## B\n\ny")
    assert [s["heading"] for s in sections] == ["T", "A", "B"]
    assert sections[1]["body"].strip() == "x"


def test_paragraphs_split_a_section_into_one_string_per_claim():
    assert markdown_paragraphs("first claim.\n\nsecond claim.") == [
        "first claim.",
        "second claim.",
    ]


def test_an_excerpt_renders_markup_and_skips_the_documents_furniture():
    """`_md_preview`, which this replaced, stripped `**` with `.replace()`,
    skipped every line starting with `-`, and returned plain text. Three of
    the four report artifacts are mostly bullets, so their cards could only
    ever show boilerplate — and anything it did not strip (a link, a code
    span) reached the page as source."""
    html = markdown_excerpt_html(
        "# Worth considering\n\nSuggestions, not decisions.\n\n"
        "- One option is to keep watching **cost** for a third independent source.\n"
    )
    assert "<li>" in html and "<strong>cost</strong>" in html
    assert "**" not in html and "- " not in html
    # The one-line preamble is a label, not a sample — it is skipped in
    # favour of the substance below it.
    assert "Suggestions, not decisions" not in html


def test_an_excerpt_of_a_document_with_only_a_short_line_still_shows_it():
    html = markdown_excerpt_html("# Provenance appendix\n\nOne row per cited signal.\n\n| a |\n|---|\n| 1 |")
    assert "One row per cited signal" in html


def test_a_tight_list_item_is_not_wrapped_in_a_paragraph():
    assert markdown_to_html("- one\n- two") == (
        '<ul class="doc-list"><li>one</li><li>two</li></ul>'
    )


def test_a_nested_list_stays_nested():
    html = markdown_to_html("- top\n  - nested")
    assert re.search(r"<li>top<ul[^>]*><li>nested</li></ul></li>", html), html


def test_none_and_empty_input_render_as_nothing_rather_than_the_word_none():
    for empty in (None, "", "   ", "\n\n"):
        assert markdown_to_html(empty) == ""
        assert markdown_excerpt_html(empty) == ""
