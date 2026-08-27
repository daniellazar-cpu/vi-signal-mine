"""Hierarchy and progressive disclosure, using the category's own components.

Two corrections from the owner are encoded here. First: *"no need to cut where
it's meaty, but don't puke on me the whole bible at once in the same colour,
font and size"* — so depth must be **present but behind a control**, and levels
must be **visually distinguished**. Second: *"it's not such a niche, you should
re-invent the wheel — think about other products and common rules and align"* —
so the components are the ones every analytics product already uses
(scorecard, card, the (i) tooltip, a delta against a named baseline), not a
bespoke scheme invented here.

The original of this file asserted a home-grown `l1`/`l2`/`l3` system. The
properties it was checking were right; the vocabulary was not.
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


def test_the_finding_precedes_the_evidence(insight):
    """Statement first, then the chart. The old page opened with a plot and
    left the reader to derive the finding from it — the "insight statement"
    pattern every analytics product leads a card with."""
    _, body = insight
    lead = body.index('class="card-lead"')
    plot = body.index("forest-plot-wrap")
    assert lead < plot, "the plot comes before the sentence that reads it"


def test_the_headline_numbers_come_before_the_chart_too(insight):
    """Scorecard, then chart, then table — GA4's anatomy, and the order a
    reader scans in."""
    _, body = insight
    assert body.index('class="scorecard"') < body.index("forest-plot-wrap")


# -------------------------------------------------- terms explain themselves --

def test_internal_tokens_do_not_reach_the_page(insight):
    """`NE` was a status token invented here. The owner's reaction to the
    equivalent — "wtf is Corroborated" — is why this list exists."""
    _, body = insight
    text = re.sub(r"<[^>]*>", " ", body)
    for token in ("say NE", "Dual-lens", "dual-lens gap"):
        assert token not in text, f"{token!r} still reaches the reader"


def test_a_term_carries_its_definition_on_demand(insight):
    """The (i) beside a label, which is the affordance this category already
    uses. The definition costs nothing until asked for; the old interface paid
    for every definition on every page."""
    _, body = insight
    assert 'class="info"' in body, "no (i) affordances on the page"
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
    trigger = re.search(r'<button type="button" class="info"[^>]*>', body).group(0)
    assert 'title="' in trigger, "no fallback for an engine without popover"
    assert 'aria-label=' in trigger


# --------------------------------------------------- layers are separated --

@pytest.mark.parametrize("selector,axes", [
    (".metric-value", ("font-size", "color")),
    (".metric-label", ("font-size", "color")),
    (".disclosure-body", ("font-size", "color")),
])
def test_each_level_declares_its_own_size_and_colour(selector, axes):
    css = _CSS.read_text()
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"{selector} is not defined"
    for axis in axes:
        assert axis in m.group(1), f"{selector} does not set {axis}"


def test_the_levels_are_actually_different_sizes():
    """Three levels set at one size is the defect being fixed."""
    css = _CSS.read_text()

    def size(sel):
        body = re.search(re.escape(sel) + r"\s*\{([^}]*)\}", css).group(1)
        m = re.search(r"font-size:\s*(?:var\([^)]*,\s*)?(\d+)px", body)
        assert m, f"{sel} has no resolvable px size"
        return int(m.group(1))

    assert size(".metric-value") > size(".card-lead") > size(".metric-label"), (
        "the levels share a size"
    )
    assert size(".disclosure-body") >= size(".metric-label")


def test_a_card_is_enclosed_not_merely_spaced():
    """Enclosure is the third axis. A card is bounded by a rule, which is what
    separates one section's content from the next without a heading having to
    do all the work."""
    css = _CSS.read_text()
    card = re.search(r"\.card\s*\{([^}]*)\}", css).group(1)
    assert "border" in card


def test_a_delta_always_names_its_baseline():
    """A change with no "vs what" is the commonest lie in this category, so the
    macro takes the baseline as a required argument."""
    macros = (Path(__file__).resolve().parents[1] / "vsm" / "ui" / "templates"
              / "_macros.html").read_text()
    assert "{% macro delta(pct, baseline_label) %}" in macros
    assert "delta-base" in macros


def test_the_components_are_the_conventional_ones():
    """The point of the second correction: someone opening this file should
    recognise the vocabulary from any other analytics product."""
    css = _CSS.read_text()
    for name in (".page-header", ".scorecard", ".metric", ".card", ".card-header",
                 ".info", ".tooltip", ".delta", ".disclosure", ".empty-state"):
        assert re.search(re.escape(name) + r"\s*[,{ ]", css), f"{name} is missing"
    for invented in (".l1 ", ".l2 ", ".l3 ", ".answer ", ".define "):
        assert invented not in css, f"the bespoke {invented.strip()} survived"


# ------------------------------------------------------------ page header --

@pytest.fixture
def screens(tmp_path, monkeypatch):
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    monkeypatch.delenv("VSM_ACCESS_KEY", raising=False)
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    seed_demo_topic(ts, rs, env={})
    topic = ts.list()[0]
    by = {m: [r for r in rs.for_topic(topic.topic_id, m)] for m in ("mine", "insight", "report")}
    c = TestClient(create_app(topic_store=ts, run_store=rs))
    return c, {
        "topic": f"/topics/{topic.topic_id}",
        "snapshot": f"/runs/{by['mine'][-1].run_id}/snapshot",
        "insight": f"/runs/{by['insight'][-1].run_id}/insight",
        "run": f"/runs/{by['mine'][-1].run_id}",
    }


@pytest.mark.parametrize("screen", ["topic", "snapshot", "insight", "run"])
def test_every_working_screen_uses_the_conventional_header(screens, screen):
    c, paths = screens
    body = c.get(paths[screen]).text
    assert 'class="page-header"' in body, f"{screen} still has a bespoke head"
    assert 'class="page-title"' in body


@pytest.mark.parametrize("screen", ["topic", "snapshot", "insight", "run"])
def test_the_five_field_definition_grid_is_gone(screens, screen):
    """It opened every screen with the same facts at the same weight as the
    content. One meta line replaces it."""
    c, paths = screens
    body = c.get(paths[screen]).text
    assert 'class="title-block"' not in body, f"{screen} still renders the grid"
    assert body.count('class="page-meta"') >= 1


def test_the_title_does_not_repeat_the_breadcrumb(screens):
    """The breadcrumb above already names the topic. The h1 used to repeat it,
    which is what made the title wrap to two lines on every run screen."""
    c, paths = screens
    body = c.get(paths["insight"]).text
    title = re.search(r'<h1 class="page-title">(.*?)</h1>', body, re.S).group(1)
    assert "Tirzepatide" not in title, f"title repeats the topic: {title!r}"
    assert "Insight" in title


@pytest.mark.parametrize("screen", ["topic", "snapshot", "insight", "run"])
def test_the_word_band_never_reaches_the_reader(screens, screen):
    """`band` means two unrelated things — how wide a sweep is, and what kind of
    venue a site is. Two meanings on one word is how a vocabulary rots, so the
    word is banned outright and the plain label used instead."""
    c, paths = screens
    text = re.sub(r"<[^>]*>", " ", c.get(paths[screen]).text)
    assert "probe band" not in text and " band" not in text, f"{screen} still says band"
    assert "sweep" in text


def test_internal_mode_words_are_replaced_with_what_the_step_does(screens):
    c, paths = screens
    text = re.sub(r"<[^>]*>", " ", c.get(paths["run"]).text)
    assert "Mine run" not in text
    assert "Collection" in text


def test_the_ui_and_the_artifacts_share_one_vocabulary():
    """A term translated on the screen and not in the file a client receives is
    worse than translating neither: the deliverable then disagrees with the
    screen about what the same figure is called."""
    import vsm.modes.vocabulary as vocab
    from vsm.ui.content import MODE_LABELS
    from vsm.ui.render import _SWEEP_SIZE

    assert _SWEEP_SIZE is vocab.SWEEP_SIZE
    assert MODE_LABELS is vocab.MODE_LABEL


def test_band_does_not_survive_into_a_generated_document():
    """The client-facing methodology and worth-considering documents used the
    word too. Same problem, one layer deeper."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "vsm" / "modes" / "report.py").read_text()
    # Only prose strings matter; the code may still name the field.
    for phrase in ("Spend band:", "the spend band on"):
        assert phrase not in src, f"{phrase!r} still reaches a client document"
