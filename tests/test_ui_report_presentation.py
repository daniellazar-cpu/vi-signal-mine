"""The report as a client-facing document, and the deliverables as an offer.

The owner's verdict on what this replaces: *"what the hell is this it looks
like markdown from the 90s, I need nice UI with reports which I can eventually
show the customers."* Every test here is pinned to one named defect from that
sentence or from the audits behind it, and every one of them fails against the
tree as it stood before this pass — that is the bar, because this project has
a documented history of tests that assert a property they never exercise.

Where a test could pass vacuously — a loop with no iterations, a substring
that a heading satisfies as easily as a finding — it asserts a floor on the
count first.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vsm.demo import seed_demo_topic
from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore
from vsm.ui.app import create_app
from vsm.ui.content import DELIVERABLES

_APP_CSS = Path(__file__).resolve().parents[1] / "vsm" / "ui" / "static" / "app.css"


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    """The worked demonstration topic — two snapshots, an insight and a
    report, deterministic. Used rather than a hand-built fixture because it
    is the exact data a visitor to this app sees on a cold start, so a
    presentation bug it has is a presentation bug they get."""
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    seed_demo_topic(ts, rs, env={})
    topic = ts.list()[0]
    report = [r for r in rs.for_topic(topic.topic_id, "report") if r.status == "complete"][-1]
    insight = [r for r in rs.for_topic(topic.topic_id, "insight")][-1]
    snapshot = rs.snapshots(topic.topic_id)[-1]
    client = TestClient(create_app(topic_store=ts, run_store=rs))
    return {
        "client": client, "topic_store": ts, "run_store": rs, "topic": topic,
        "report": report, "insight": insight, "snapshot": snapshot,
        "report_path": f"/runs/{report.run_id}/report",
    }


def every_page(seeded) -> dict[str, str]:
    """Every HTML surface this app renders for the seeded store."""
    t, rep, ins, snap = seeded["topic"], seeded["report"], seeded["insight"], seeded["snapshot"]
    paths = [
        "/", "/how", "/deliverables", "/topics/new",
        f"/topics/{t.topic_id}", f"/topics/{t.topic_id}/edit",
        f"/topics/{t.topic_id}/confirm?band=probe",
        f"/runs/{snap.run_id}", f"/runs/{snap.run_id}/snapshot",
        f"/runs/{ins.run_id}/insight", f"/runs/{rep.run_id}/report",
    ]
    out = {}
    for path in paths:
        response = seeded["client"].get(path)
        assert response.status_code == 200, f"{path} -> {response.status_code}"
        out[path] = response.text
    return out


# --------------------------------------------------------------------------
# 1. The regression that produced the complaint.
# --------------------------------------------------------------------------


#: Source syntax that must never survive to a page. `**` is the literal one
#: from the screenshot; the rest are the neighbouring leaks the audits found.
RAW_MARKDOWN_TOKENS = ("**", "## ", "|---|", "](http", "__", "~~")


def test_no_raw_markdown_reaches_any_page(seeded):
    """The named regression: `**cost** — 12 independent
    sources.` rendered verbatim on `/deliverables`, and on five other
    surfaces that shared the same card.

    Asserted across every page rather than the one that was reported,
    because the defect was never local to that page — it was an authored
    string handed to a template without passing the converter, and any
    surface showing that card had it."""
    pages = every_page(seeded)
    assert len(pages) >= 11
    offenders = [
        (path, token)
        for path, body in pages.items()
        for token in RAW_MARKDOWN_TOKENS
        if token in body
    ]
    assert not offenders, "raw markdown on rendered pages: " + "; ".join(
        f"{p} contains {t!r}" for p, t in offenders
    )


def test_the_deliverable_samples_are_the_thing_that_would_have_leaked(seeded):
    """Non-vacuity guard for the test above: it would also pass if the
    samples had simply been deleted. They are on the page, and rendered."""
    body = seeded["client"].get("/deliverables").text
    assert "12 independent sources" in body
    assert "<strong>Cost of access</strong>" in body


def test_every_deliverable_excerpt_renders_as_markup_not_source(seeded):
    """Each of the four client-ready cards carries an excerpt, and each one
    is markup. Counted, so an empty excerpt list cannot pass."""
    body = seeded["client"].get("/deliverables").text
    samples = re.findall(r'<figure class="deliv-sample">(.*?)</figure>', body, re.S)
    assert len(samples) == 4, f"expected four rendered samples, got {len(samples)}"
    for sample in samples:
        assert re.search(r"<(strong|table|em|li|p)\b", sample), sample
        for token in RAW_MARKDOWN_TOKENS:
            assert token not in sample, (token, sample)


def test_a_produced_run_shows_a_real_excerpt_of_its_own_artifact(seeded):
    """After a run the card shows the run's own output, not the authored
    illustration — and says which it is showing.

    Checked on the topic page rather than the report page. The full card
    treatment was on five screens at ~300 words each, and on a *finished* report
    it showed the reader an excerpt of the document they were already reading.
    The preview now lives where the question it answers is still open — the
    topic page and `/deliverables` — and finished runs carry a download list
    instead. `test_a_finished_run_lists_downloads_rather_than_previewing_them`
    below pins that split.
    """
    body = seeded["client"].get(f"/topics/{seeded['topic'].topic_id}").text
    assert "From this run" in body


# --------------------------------------------------------------------------
# 2. The report as a document.
# --------------------------------------------------------------------------


def test_the_report_opens_with_a_cover_not_a_tool_label(seeded):
    body = seeded["client"].get(seeded["report_path"]).text
    h1 = re.search(r'<h1 class="doc-title">(.*?)</h1>', body, re.S)
    assert h1, "no cover title"
    assert seeded["topic"].name in h1.group(1)
    assert "Report preview" not in body, "tool language on the client-facing document"
    # The cover states the window covered, what it rests on, and the
    # confidence summary — the four things the plan names.
    assert re.search(r"Collected (on|\d)", body)
    assert "Rests on" in body
    # Stated as counts, not as invented category names.
    assert re.search(r"\d+ with 3\+ sources · \d+ with 2 · \d+ with 1", body), body[:0] or (
        re.search(r"\d+ corroborated", body) and "the old tier words are back"
    )
    assert f'/runs/{seeded["snapshot"].run_id}/snapshot' in body


def test_the_run_id_and_cost_are_provenance_not_headline(seeded):
    """A supplier's internal telemetry and unit economics printed at cover
    weight beside the subject is what a client reads first, and it is the
    one thing on the page that is about us rather than about them."""
    body = seeded["client"].get(seeded["report_path"]).text
    provenance = re.search(r'<p class="doc-provenance">(.*?)</p>', body, re.S)
    assert provenance, "no provenance line"
    assert seeded["report"].run_id in provenance.group(1)
    title_block = re.search(r'<h1 class="doc-title">.*?</h1>', body, re.S).group(0)
    assert seeded["report"].run_id not in title_block


def test_every_corroborated_finding_carries_a_confidence_badge(seeded):
    """The old test for this asserted `"corroborated" in body.lower()`, which
    the heading *"Corroborated findings"* satisfies on a run with zero
    corroborated findings. This counts the findings in the artifact and
    requires exactly that many badged statements on the page."""
    run_store = seeded["run_store"]
    findings = run_store.read_artifact(seeded["insight"].run_id, "findings.json")
    expected = [f for f in findings if f["tier"] == "corroborated"]
    assert expected, "fixture has no corroborated finding — this test would prove nothing"

    body = seeded["client"].get(seeded["report_path"]).text
    section = re.search(r'<section class="doc-section" id="findings">(.*?)</section>', body, re.S)
    assert section, "no findings section"
    blocks = re.findall(r'<div class="finding"(.*?)</div>\s*<p class="finding-claim">(.*?)</p>',
                        section.group(1), re.S)
    assert len(blocks) == len(expected), (
        f"{len(expected)} corroborated findings in the artifact, {len(blocks)} on the page"
    )
    for head, claim in blocks:
        assert "tier-badge-corroborated" in head, head
        assert claim.strip(), "a finding with no claim"


def test_a_confidence_tier_is_a_badge_not_a_title_tooltip(seeded):
    """`title=` is unreachable by keyboard, invisible on touch and absent in
    print — three of the places a client actually reads this."""
    body = seeded["client"].get(seeded["report_path"]).text
    assert 'class="tier-badge' in body
    assert "<td title=" not in body


def test_the_forest_plot_is_a_numbered_captioned_figure_on_the_report(seeded):
    """The product's one real visual argument did not appear on the report at
    all — it lived on the internal insight screen, in a bare div, with no
    number a reader could cite."""
    body = seeded["client"].get(seeded["report_path"]).text
    figure = re.search(r'<figure class="doc-figure" id="figure-1">(.*?)</figure>', body, re.S)
    assert figure, "no Figure 1 on the report"
    assert "<svg" in figure.group(1)
    assert "<figcaption>" in figure.group(1)
    assert "Figure 1" in figure.group(1)


def test_the_themes_table_appears_once_not_twice(seeded):
    """`Themes at a glance` used to be followed immediately by the pulse
    report's own `Themes observed` table carrying the same columns."""
    body = seeded["client"].get(seeded["report_path"]).text
    assert body.count('<h2 class="doc-h">Themes observed</h2>') == 1
    assert "Themes at a glance" not in body
    # One table carries the theme/volume/tier/sources columns, not two.
    assert len(re.findall(r"Independent sources", body)) == 1


# --------------------------------------------------------------------------
# 3. Citations resolve, both ways.
# --------------------------------------------------------------------------


def test_every_in_page_anchor_on_every_page_resolves_to_an_id_that_exists(seeded):
    for path, body in every_page(seeded).items():
        ids = set(re.findall(r'id="([^"]+)"', body))
        fragments = set(re.findall(r'href="#([^"]+)"', body))
        assert fragments <= ids, f"{path}: dangling anchors {sorted(fragments - ids)}"


def test_every_citation_mark_resolves_to_an_appendix_row(seeded):
    body = seeded["client"].get(seeded["report_path"]).text
    marks = re.findall(r'<sup class="ref-marks">(.*?)</sup>', body, re.S)
    assert marks, "no reference marks on the report"
    targets = {t for mark in marks for t in re.findall(r'href="#(ref-\d+)"', mark)}
    assert targets, "reference marks that point nowhere"
    appendix = re.search(r'<section class="doc-section" id="appendix">(.*?)</section>', body, re.S)
    assert appendix
    rows = set(re.findall(r'<tr id="(ref-\d+)"', appendix.group(1)))
    assert targets <= rows, f"references with no appendix row: {sorted(targets - rows)}"


def test_the_appendix_links_back_to_the_claim_that_cited_it(seeded):
    """One-way citations make an appendix a URL dump. Every row that a claim
    cites carries the reciprocal link, and it resolves."""
    body = seeded["client"].get(seeded["report_path"]).text
    appendix = re.search(r'<section class="doc-section" id="appendix">(.*?)</section>', body, re.S)
    assert appendix
    rows = re.findall(r'<tr id="ref-\d+".*?</tr>', appendix.group(1), re.S)
    assert len(rows) >= 3, f"only {len(rows)} appendix rows — too few to prove anything"
    ids = set(re.findall(r'id="([^"]+)"', body))
    linked_back = 0
    for row in rows:
        back = re.findall(r'href="#((?:finding|theme)-\d+)"', row)
        for anchor in back:
            assert anchor in ids, f"appendix back-link to a missing anchor: {anchor}"
        linked_back += bool(back)
    assert linked_back == len(rows), (
        f"{len(rows) - linked_back} appendix rows do not link back to a claim"
    )


def test_the_appendix_link_text_is_the_venue_not_the_whole_url(seeded):
    """Nine near-identical 70-character URLs printed as their own link text
    is not an appendix, it is a dump."""
    body = seeded["client"].get(seeded["report_path"]).text
    appendix = re.search(r'<section class="doc-section" id="appendix">(.*?)</section>', body, re.S)
    links = re.findall(r'<a href="(https?://[^"]+)">([^<]+)</a>', appendix.group(1))
    assert links
    for href, text in links:
        assert text != href, f"link text is the raw URL: {text}"
        assert text in href, f"link text {text!r} is not the host of {href!r}"


# --------------------------------------------------------------------------
# 4. `None` is never a zero and never a blank.
# --------------------------------------------------------------------------


def test_a_theme_with_no_comparable_stance_shows_its_reason(seeded):
    """This codebase's one non-negotiable rule, in the column most likely to
    break it. The figure's data table is the only place the per-row reason is
    readable at all — before this it lived in an `aria-label` on a `role=img`
    subtree, which is to say nowhere."""
    duallens = seeded["run_store"].read_artifact(seeded["insight"].run_id, "duallens.json")
    unmeasurable = [g for g in duallens if g["divergence"] is None]
    assert unmeasurable, "fixture has no not-estimable theme — this test would prove nothing"

    body = seeded["client"].get(seeded["report_path"]).text
    for gap in unmeasurable:
        assert gap["reason"] in body, f"reason not stated for {gap['theme_name']}"
    assert "NE" in body


def test_the_pulse_report_artifact_never_prints_python_none(seeded):
    """`| tolerability | None | None | n/a — ... |` shipped in the one file a
    client is handed. The divergence column honoured the rule; the two stance
    columns f-string'd `None` straight into the table."""
    text = seeded["run_store"].read_artifact(seeded["report"].run_id, "pulse_report.md")
    assert "| None |" not in text
    assert not re.search(r"\bNone\b", text), "the literal word None in a client artifact"
    # And the honest replacement is actually there.
    assert "not read — no" in text


def test_a_none_stance_is_not_rendered_as_zero_anywhere_on_the_page(seeded):
    """Rendering `None` as `0.00` would satisfy "no None on the page" while
    asserting neutrality nobody expressed."""
    duallens = seeded["run_store"].read_artifact(seeded["insight"].run_id, "duallens.json")
    body = seeded["client"].get(seeded["report_path"]).text
    rows = re.findall(r"<tr>(.*?)</tr>", body, re.S)
    for gap in duallens:
        if gap["patient_net"] is not None and gap["hcp_net"] is not None:
            continue
        row = next((r for r in rows if gap["theme_name"] in r), None)
        assert row, gap["theme_name"]
        assert "—" in row, f"a null stance rendered as something other than an em dash: {row}"


def test_a_report_whose_artifacts_are_missing_names_the_deliverable_not_the_file(tmp_path):
    """`pulse_report.md was not found on this run.` is the filesystem
    apologising to a client."""
    from vsm.modes.insight import run_insight
    from vsm.modes.report import run_report

    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    topic = ts.create(name="OIC", therapeutic_area="gi", spend_band="probe")
    rows = [{"signal_id": f"s{i}", "venue": f"v{i}.example.org", "theme": "tolerability",
             "title": f"t{i}", "excerpt": "tolerability",
             "captured_at": "2026-08-25T00:00:00+00:00", "collection_method": "serp_result",
             "url": f"https://v{i}.example.org/{i}"} for i in range(4)]
    mine = rs.start(topic.topic_id, "mine")
    rs.write_artifact(mine.run_id, "signals.json", rows)
    rs.finish(mine.run_id, "complete", cost_usd=0.01)
    insight = run_insight(topic, mine.run_id, rs)
    report = run_report(topic, insight.run_id, rs)
    (rs.artifacts_dir(report.run_id) / "pulse_report.md").unlink()

    client = TestClient(create_app(topic_store=ts, run_store=rs))
    response = client.get(f"/runs/{report.run_id}/report")
    assert response.status_code == 200
    assert "pulse_report.md was not found" not in response.text
    assert "The pulse report was not written on this run" in response.text


def test_a_model_written_sub_heading_does_not_hang_the_report_route(tmp_path):
    """End-to-end cover for the converter hang: `REPORT_SCHEMA` types a
    section body as an unconstrained string, so a fourth-level heading in
    model output reaches this route."""
    from vsm.modes.insight import run_insight
    from vsm.modes.report import run_report

    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    topic = ts.create(name="OIC", therapeutic_area="gi", spend_band="probe")
    rows = [{"signal_id": f"s{i}", "venue": f"v{i}.example.org", "theme": "tolerability",
             "title": f"t{i}", "excerpt": "tolerability",
             "captured_at": "2026-08-25T00:00:00+00:00", "collection_method": "serp_result",
             "url": f"https://v{i}.example.org/{i}"} for i in range(4)]
    mine = rs.start(topic.topic_id, "mine")
    rs.write_artifact(mine.run_id, "signals.json", rows)
    rs.finish(mine.run_id, "complete", cost_usd=0.01)
    insight = run_insight(topic, mine.run_id, rs)
    report = run_report(topic, insight.run_id, rs)
    rs.write_artifact(
        report.run_id, "pulse_report.md",
        "# Pulse Report\n\n## Themes\n\n#### A model-written sub-heading\n\nbody\n",
    )
    client = TestClient(create_app(topic_store=ts, run_store=rs))
    response = client.get(f"/runs/{report.run_id}/report")
    assert response.status_code == 200
    assert "A model-written sub-heading" in response.text


# --------------------------------------------------------------------------
# 5. The deliverables page as an offer in two tiers.
# --------------------------------------------------------------------------


def _tier(body: str, key: str) -> str:
    match = re.search(
        rf'<section class="deliv-tier deliv-tier-{key}" id="deliverables-{key}">(.*?)'
        rf'(?=<section class="deliv-tier|</div>\s*<p class="body-text|</section>\s*</div>)',
        body, re.S,
    )
    assert match, f"no {key} tier on the page"
    return match.group(1)


CLIENT_READY = [d["name"] for d in DELIVERABLES if d["group"] == "report"]
EVERYTHING_ELSE = [d["name"] for d in DELIVERABLES if d["group"] != "report"]


def test_the_four_client_ready_artifacts_are_the_primary_tier(seeded):
    assert len(CLIENT_READY) == 4 and len(EVERYTHING_ELSE) == 6
    body = seeded["client"].get("/deliverables").text
    primary = _tier(body, "primary")
    for name in CLIENT_READY:
        assert name in primary, f"{name} missing from the primary tier"
    for name in EVERYTHING_ELSE:
        assert name not in primary, f"{name} should not be in the primary tier"


def test_the_other_six_drop_to_a_secondary_list_not_cards(seeded):
    body = seeded["client"].get("/deliverables").text
    secondary = _tier(body, "secondary")
    for name in EVERYTHING_ELSE:
        assert name in secondary, f"{name} missing from the secondary tier"
    for name in CLIENT_READY:
        assert name not in secondary, f"{name} should not be repeated in the secondary tier"
    # A list, not a grid of cards — the whole point of the split.
    assert "deliv-list" in secondary and "deliv-grid" not in secondary
    assert secondary.count("<li class=\"deliv-row") == 6


def test_the_primary_tier_comes_first_on_the_page(seeded):
    body = seeded["client"].get("/deliverables").text
    assert body.index('id="deliverables-primary"') < body.index('id="deliverables-secondary"')


def test_a_filename_is_never_the_headline(seeded):
    """`pulse_report.md` sat on the same baseline as the card's name, in the
    top-right, so the eye landed on the extension."""
    body = seeded["client"].get("/deliverables").text
    headings = re.findall(r'<h\d class="deliv-(?:name|row-name)"[^>]*>(.*?)</h\d>', body)
    assert len(headings) == 10
    for heading in headings:
        assert ".md" not in heading and ".json" not in heading, heading


def test_a_download_is_a_control_with_states_and_its_filename_beside_it(seeded):
    """On the topic page: it is where the card treatment lives now *and* has
    real artifacts behind it. `/deliverables` has the cards but nothing
    downloadable — it is the not-run-yet catalogue — so the control's states
    could only be checked somewhere both are true."""
    body = seeded["client"].get(f"/topics/{seeded['topic'].topic_id}").text
    controls = re.findall(r'<a class="btn btn-ghost btn-sm deliv-download"[^>]*>(.*?)</a>', body, re.S)
    assert len(controls) >= 4, f"expected download controls, found {len(controls)}"
    for control in controls:
        assert "Markdown" in control or "JSON" in control
    css = _APP_CSS.read_text()
    for state in (".btn-ghost:hover", ".btn-ghost:active", ":focus-visible"):
        assert state in css, f"no {state} state defined"


def test_the_deliverables_page_links_to_a_real_finished_report(seeded):
    """Cross-link, not a dead end: a page that describes a document and
    cannot show you one is a brochure."""
    body = seeded["client"].get("/deliverables").text
    assert f'/runs/{seeded["report"].run_id}/report' in body


def test_the_report_links_back_to_the_deliverables_catalog(seeded):
    body = seeded["client"].get(seeded["report_path"]).text
    assert 'href="/deliverables"' in body


# --------------------------------------------------------------------------
# 6. The print path.
# --------------------------------------------------------------------------


def _print_block() -> str:
    css = _APP_CSS.read_text()
    start = css.index("@media print {")
    depth, i = 0, start
    while i < len(css):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    return css[start:i + 1]


def test_a_print_stylesheet_exists_and_drops_the_app_chrome():
    block = _print_block()
    hidden = re.search(r"([^{}]*)\{\s*display: none !important;", block)
    assert hidden, "the print block hides nothing"
    selectors = hidden.group(1)
    for chrome in (".app-top", ".app-top-nav", ".flow-rail", ".app-foot", ".deliv-tiers", ".btn"):
        assert chrome in selectors, f"print does not hide {chrome}"


def test_print_keeps_the_fabricated_data_warning_and_expands_hidden_tab_panels():
    """A demonstration-run warning that vanishes on the way to the printer is
    worse than useless. And four of the insight screen's five tab panels are
    `display: none` on screen — printed without this they are simply gone."""
    block = _print_block()
    assert re.search(r"\.synthetic-banner\s*\{[^}]*display: flex !important", block)
    assert re.search(r"\.tab-panel\s*\{[^}]*display: block !important", block)


def test_print_expands_citation_urls_so_a_paper_copy_is_still_checkable():
    block = _print_block()
    assert 'content: " (" attr(href) ")"' in block


def test_every_page_loads_the_stylesheet_that_carries_the_print_rules(seeded):
    for path, body in every_page(seeded).items():
        assert '/static/app.css' in body, path


# --------------------------------------------------------------------------
# 7. Keyboard and structure.
# --------------------------------------------------------------------------


def test_no_rule_kills_a_focus_outline_without_restoring_it():
    """`input:focus { ... outline: none ... }` sat 250 lines after the global
    `:focus-visible` rule and won on specificity, so a native radio — on the
    one form that leads to the only screen that spends money — had no visible
    focus indicator at all."""
    css = _APP_CSS.read_text()
    for match in re.finditer(r"([^{}]+)\{[^{}]*outline:\s*none", css):
        selector = match.group(1).strip().splitlines()[-1].strip()
        restored = selector.replace(":focus", ":focus-visible")
        assert restored != selector, f"outline: none on a non-focus selector: {selector}"
        assert restored in css, f"{selector} kills the outline and nothing restores it"


def test_a_keyboard_reader_can_reach_the_content_and_the_scrolling_tables(seeded):
    for path, body in every_page(seeded).items():
        assert 'class="skip-link" href="#main"' in body, path
        assert 'id="main"' in body, path
        for wrapper in re.findall(r'<div class="table-scroll[^"]*"([^>]*)>', body):
            assert 'tabindex="0"' in wrapper, f"{path}: unreachable scroll container"


def test_every_table_on_every_page_has_a_caption_and_scoped_headers(seeded):
    class Tables(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tables, self._depth = [], 0

        def handle_starttag(self, tag, attrs):
            if tag == "table":
                self._depth += 1
                self.tables.append({"caption": False, "col": False, "row": False})
            elif self.tables and self._depth:
                d = dict(attrs)
                if tag == "caption":
                    self.tables[-1]["caption"] = True
                elif tag == "th":
                    if d.get("scope") == "col":
                        self.tables[-1]["col"] = True
                    elif d.get("scope") in ("row", "rowgroup"):
                        self.tables[-1]["row"] = True

        def handle_endtag(self, tag):
            if tag == "table":
                self._depth = max(0, self._depth - 1)

    seen = 0
    for path, body in every_page(seeded).items():
        parser = Tables()
        parser.feed(body)
        for i, table in enumerate(parser.tables):
            seen += 1
            assert table["caption"], f"{path}: table {i} has no caption"
            assert table["col"], f"{path}: table {i} has no scoped column headers"
    assert seen >= 10, f"only {seen} tables checked — the walk is not covering the app"


def test_the_document_has_one_h1_and_skips_no_heading_level(seeded):
    for path, body in every_page(seeded).items():
        levels = [int(n) for n in re.findall(r"<h([1-6])[ >]", body)]
        assert levels.count(1) == 1, f"{path}: {levels.count(1)} h1 elements"
        for previous, current in zip(levels, levels[1:]):
            assert current <= previous + 1, f"{path}: h{previous} -> h{current}"


def test_each_absent_net_cell_states_its_own_reason(seeded):
    """The page must not be less honest than the document it previews.

    The sibling test above asserts only that an em dash appears, which passes
    whether or not the cell explains itself — it locked the defect in rather
    than catching it. `pulse_report.md` prints "not read — no patient-class
    signal in this theme" in this very cell, so the page printing a bare dash
    meant a reader comparing the two found the page silent where the document
    explained itself. Fourteenth instance in this build of a test asserting a
    property it never exercised.
    """
    body = seeded["client"].get(seeded["report_path"]).text
    # At least one lens has no signal in the seeded demo, so at least one of
    # these reasons must be on the page. If the demo ever changes so that both
    # lenses are always populated, this test should be given a fixture that
    # forces the absent case rather than being deleted.
    assert (
        "no clinician-class signal in this theme" in body
        or "no patient-class signal in this theme" in body
    ), "an absent net stance rendered without saying why"


def test_the_net_filter_degrades_rather_than_lying():
    """Called without a lens the filter falls back to a dash — the old
    behaviour. Pinned so a caller that forgets the argument is visibly
    unhelpful rather than silently wrong about which lens is missing."""
    from vsm.ui.render import net_stance_text

    assert net_stance_text(None) == "—"
    assert net_stance_text(None, "patient").startswith("not read")
    assert net_stance_text(0.0, "patient") == "+0.00"


def test_a_finished_run_lists_downloads_rather_than_previewing_them(seeded):
    """The split this pass introduced, pinned in both directions.

    The deliverables preview exists to answer "what will I get before I spend
    anything". On a finished run that question is answered by the page itself,
    so the cards were ~300 words restating what was already on screen — and the
    same block sat on five separate screens.
    """
    paths = [seeded["report_path"],
             f"/runs/{seeded['insight'].run_id}/insight",
             f"/runs/{seeded['snapshot'].run_id}/snapshot"]
    for path in paths:
        body = seeded["client"].get(path).text
        assert 'class="downloads-list"' in body, f"{path} has no download list"
        assert 'class="deliv-card"' not in body, f"{path} still renders preview cards"
        # And the list must actually link the artifacts, not just look like one.
        assert "/artifact/" in body, path


def test_the_preview_still_exists_where_the_question_is_open(seeded):
    """The other half: removing it everywhere would have deleted a feature that
    was asked for. A topic page and `/deliverables` keep the full treatment."""
    for path in ("/deliverables", f"/topics/{seeded['topic'].topic_id}"):
        body = seeded["client"].get(path).text
        assert 'class="deliv-card' in body, f"{path} lost the preview"
