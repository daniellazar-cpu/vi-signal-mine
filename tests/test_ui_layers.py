"""Layering, not cutting.

The owner's correction, verbatim: *"There are so many UI components you can use
to handle that — expanding windows, sidebars, tooltips, read-mores... no need to
cut where it's meaty, but don't puke on me the whole bible at once in the same
colour, font and size and hope I'll be able to curate something."*

So the tests below check two things a word count cannot: that depth material is
**present but behind a control**, and that layers are **visually distinguished**
rather than set identically. A screen where a finding and a footnote look the
same has failed however few words it has.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vsm.demo import seed_demo_topic
from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore
from vsm.ui.app import create_app

_CSS = Path(__file__).resolve().parents[1] / "vsm" / "ui" / "static" / "app.css"


@pytest.fixture
def insight(tmp_path, monkeypatch):
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    monkeypatch.delenv("VSM_ACCESS_KEY", raising=False)
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    seed_demo_topic(ts, rs, env={})
    topic = ts.list()[0]
    run = [r for r in rs.for_topic(topic.topic_id, "insight")][-1]
    c = TestClient(create_app(topic_store=ts, run_store=rs))
    return c, c.get(f"/runs/{run.run_id}/insight").text


# ------------------------------------------------------- depth is retained --

def test_the_depth_material_is_still_present(insight):
    """Cutting was the wrong instinct. The guide prose and the reason a theme
    cannot be compared are the *why* behind the numbers — the most valuable
    thing on the page — and must survive."""
    _, body = insight
    assert "How to read this" in body
    assert "Box size" in body, "the plot guide was deleted rather than moved"


def test_the_depth_material_is_behind_a_control(insight):
    """Present is not the same as in your face. Every layer-3 block must be
    inside a disclosure the reader opens."""
    _, body = insight
    for phrase in ("Box size",):
        i = body.index(phrase)
        before = body[:i]
        assert before.rfind("<details") > before.rfind("</details>"), (
            f"{phrase!r} is not inside an open <details> element"
        )


def test_the_answer_precedes_the_evidence(insight):
    """Layer 1 first. The old page opened with a plot and left the reader to
    derive the finding from it."""
    _, body = insight
    answer = body.index('class="answer"')
    plot = body.index("forest-plot-wrap")
    assert answer < plot, "the plot comes before the sentence that reads it"


# -------------------------------------------------- terms explain themselves --

def test_internal_tokens_do_not_reach_the_page(insight):
    """`NE` was a status token invented here. The owner's reaction to the
    equivalent — "wtf is Corroborated" — is why this list exists."""
    _, body = insight
    text = re.sub(r"<[^>]*>", " ", body)
    for token in ("say NE", "Dual-lens", "dual-lens gap"):
        assert token not in text, f"{token!r} still reaches the reader"


def test_a_term_carries_its_definition_on_demand(insight):
    """Native popover: the definition costs nothing until asked for. The old
    interface paid for every definition on every page."""
    _, body = insight
    assert 'class="define"' in body, "no on-demand definitions on the page"
    m = re.search(r'popovertarget="([^"]+)"', body)
    assert m, "the trigger is not wired to a popover"
    assert f'popover id="{m.group(1)}"' in body, "the popover target does not exist"


def test_every_definition_trigger_resolves_to_a_popover(insight):
    """A dangling `popovertarget` silently does nothing — the worst failure
    mode, because it looks fine."""
    _, body = insight
    targets = set(re.findall(r'popovertarget="([^"]+)"', body))
    present = set(re.findall(r'popover id="([^"]+)"', body))
    assert targets, "no triggers at all"
    assert targets <= present, f"dangling: {targets - present}"


def test_the_definition_works_without_javascript_support(insight):
    """`popover` needs no script, but an older engine ignores it entirely — so
    the text must also be reachable as a title, and present in the DOM."""
    _, body = insight
    trigger = re.search(r'<button type="button" class="define"[^>]*>', body).group(0)
    assert 'title="' in trigger, "no fallback for an engine without popover"
    assert 'aria-label=' in trigger


# --------------------------------------------------- layers are separated --

@pytest.mark.parametrize("selector,axes", [
    (".l1", ("font-size", "color")),
    (".l2", ("font-size", "color")),
    (".l3-body", ("font-size", "color")),
])
def test_each_layer_declares_its_own_size_and_colour(selector, axes):
    css = _CSS.read_text()
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"{selector} is not defined"
    for axis in axes:
        assert axis in m.group(1), f"{selector} does not set {axis}"


def test_the_layers_are_actually_different_sizes():
    """Three layers set at one size is the defect being fixed."""
    css = _CSS.read_text()

    def size(sel):
        body = re.search(re.escape(sel) + r"\s*\{([^}]*)\}", css).group(1)
        m = re.search(r"font-size:\s*(?:var\([^)]*,\s*)?(\d+)px", body)
        assert m, f"{sel} has no resolvable px size"
        return int(m.group(1))

    assert size(".l1-figure") > size(".l1") > size(".l2"), "layers share a size"
    assert size(".l3-body") <= size(".l2")


def test_layer_three_is_enclosed_not_merely_smaller():
    """Size alone is a weak signal. A layer-3 block is also set apart by a rule,
    which is what says "available, not addressed to you"."""
    css = _CSS.read_text()
    body = re.search(r"\.l3-body\s*\{([^}]*)\}", css).group(1)
    assert "border-left" in body or "background" in body
