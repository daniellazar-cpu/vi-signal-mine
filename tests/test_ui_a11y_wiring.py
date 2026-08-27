"""ARIA that is actually wired, print that actually prints.

Three findings this module holds, all of which the existing suite would have
missed because it asserted the presence of markup and CSS text rather than the
relationship between them:

* a validation error rendered next to its field but not *associated* with it,
  so a screen-reader user tabbing in heard the label and help text and never
  the error;
* a print stylesheet that unhid the ``<details>`` wrapper but left the
  browser's own ``details:not([open]) > :not(summary) { display: none }`` in
  force, so anything collapsed on screen printed as an empty gap;
* the one "current" indicator in the app carried by colour and weight alone.
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

_APP_CSS = Path(__file__).resolve().parents[1] / "vsm" / "ui" / "static" / "app.css"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    seed_demo_topic(ts, rs, env={})
    return TestClient(create_app(topic_store=ts, run_store=rs)), ts, rs


def _attrs(html: str, needle: str) -> str:
    """The opening tag containing `needle`."""
    i = html.index(needle)
    start = html.rindex("<", 0, i)
    return html[start:html.index(">", i) + 1]


def test_a_rejected_topic_name_is_announced_on_the_field_itself(client):
    c, _, _ = client
    r = c.post("/topics", data={"name": "", "spend_band": "conversation"},
               follow_redirects=False)
    body = r.text
    assert 'class="field-error"' in body, "no error rendered at all — fixture is wrong"

    err = re.search(r'<p class="field-error"[^>]*id="([^"]+)"', body)
    assert err, "the error paragraph carries no id, so nothing can point at it"
    err_id = err.group(1)

    tag = _attrs(body, 'id="f-name"')
    described = re.search(r'aria-describedby="([^"]*)"', tag)
    assert described, f"the name input has no aria-describedby: {tag}"
    assert err_id in described.group(1).split(), (
        f"the error {err_id!r} is not in the input's aria-describedby "
        f"({described.group(1)!r}) — it is on the page but not announced"
    )
    assert 'aria-invalid="true"' in tag, f"the field is not marked invalid: {tag}"


def test_the_help_text_is_not_dropped_when_an_error_appears(client):
    """A common way to "fix" this is to point aria-describedby at the error and
    overwrite the help text, trading one silence for another."""
    c, _, _ = client
    body = c.post("/topics", data={"name": "", "spend_band": "conversation"},
                  follow_redirects=False).text
    described = re.search(r'aria-describedby="([^"]*)"', _attrs(body, 'id="f-name"'))
    ids = described.group(1).split()
    assert len(ids) >= 2, f"help text lost when the error appeared: {ids}"
    for i in ids:
        assert f'id="{i}"' in body, f"aria-describedby points at {i!r}, which is not on the page"


def test_a_valid_submission_marks_nothing_invalid(client):
    """The mirror image: `aria-invalid` must not be permanently present."""
    c, _, _ = client
    body = c.get("/topics/new").text
    assert 'aria-invalid="true"' not in body, "a fresh form reports itself invalid"


def test_print_asks_for_collapsed_details_to_be_shown(client):
    """Asserts the *declaration*, and deliberately claims no more than that.

    A closed `<details>` does not render its content slot, so this rule cannot
    guarantee the content prints — Chrome prints it anyway, other engines may
    not, and with no JavaScript there is nothing to force `open`. The
    declaration is still right to have, and the test below keeps the exposure
    bounded by checking the report carries no `<details>` at all.
    """
    css = _APP_CSS.read_text()
    block = css[css.index("@media print"):]
    block = block[:block.index("\n}\n") + 3]
    assert re.search(
        r"details:not\(\[open\]\)\s*>\s*:not\(summary\)\s*\{[^}]*display:\s*block\s*!important",
        block,
    ), "collapsed <details> content still vanishes from a printed page"


def test_the_client_facing_report_contains_no_details_at_all(client):
    """What actually protects the deliverable. Whatever a given engine does with
    a closed `<details>` cannot matter for the report if the report has none —
    so this, not the print rule, is the guarantee that the document a client
    receives prints whole."""
    from pathlib import Path

    report = Path(__file__).resolve().parents[1] / "vsm" / "ui" / "templates" / "report.html"
    assert "<details" not in report.read_text()


def test_there_is_collapsed_details_content_worth_printing(client):
    """The rule above is only worth having if the app actually ships closed
    `<details>`. If this fails, that test has become decoration."""
    c, ts, rs = client
    topic = ts.list()[0]
    insight = [r for r in rs.for_topic(topic.topic_id, "insight")][-1]
    pages = [c.get("/how").text, c.get(f"/runs/{insight.run_id}/insight").text]
    closed = sum(len(re.findall(r"<details(?![^>]*\bopen\b)", p)) for p in pages)
    assert closed > 0, "no closed <details> anywhere — the print rule guards nothing"


def test_the_current_snapshot_is_marked_programmatically(client):
    c, ts, rs = client
    topic = ts.list()[0]
    insight = [r for r in rs.for_topic(topic.topic_id, "insight")][-1]
    body = c.get(f"/runs/{insight.run_id}/insight").text
    assert "dated-frame-current" in body, "no current frame in the strip — fixture is wrong"
    tag = _attrs(body, "dated-frame-current")
    assert 'aria-current="page"' in tag, (
        f"the current snapshot is distinguished by styling alone: {tag}"
    )
    # Scoped to the strip: the nav uses `aria-current` too, so counting across
    # the whole page would compare unrelated things and break for a reason that
    # has nothing to do with this indicator.
    strip = re.search(r'<div class="dated-strip".*?</div>', body, re.S)
    assert strip, "dated strip not found"
    frames = strip.group(0)
    assert frames.count('aria-current="page"') == frames.count("dated-frame-current") == 1, (
        "exactly one snapshot in the strip should be current"
    )
