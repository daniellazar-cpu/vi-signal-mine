import pytest
from fastapi.testclient import TestClient

from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore
from vsm.ui.app import create_app


@pytest.fixture
def client(tmp_path):
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    return TestClient(create_app(topic_store=ts, run_store=rs)), ts, rs


def test_empty_state_explains_that_momentum_needs_two_snapshots(client):
    c, _, _ = client
    body = c.get("/").text
    assert "two snapshots" in body.lower() or "more than once" in body.lower()


def test_a_topic_appears_on_the_list(client):
    c, ts, _ = client
    ts.create(name="OIC pulse", therapeutic_area="gastroenterology", spend_band="standard")
    assert "OIC pulse" in c.get("/").text


def test_creating_a_topic_redirects_to_the_list(client):
    c, ts, _ = client
    r = c.post("/topics", data={"name": "New", "therapeutic_area": "gi",
                                "spend_band": "probe"}, follow_redirects=False)
    assert r.status_code in (302, 303)
    assert [t.name for t in ts.list()] == ["New"]


def test_the_confirm_screen_shows_the_estimate_and_the_cap(client):
    c, ts, _ = client
    t = ts.create(name="OIC", therapeutic_area="gi", spend_band="standard")
    body = c.get(f"/topics/{t.topic_id}/confirm?band=standard").text
    assert "$" in body
    assert "cap" in body.lower()
    for item in ("serp", "discover", "unlocker", "model"):
        assert item in body.lower()


def test_a_single_snapshot_shows_no_trend_line(client):
    """One point is not a trend, and drawing it as one would be the first lie
    the tool tells."""
    c, ts, rs = client
    t = ts.create(name="OIC", therapeutic_area="gi", spend_band="probe")
    run = rs.start(t.topic_id, "mine")
    rs.write_artifact(run.run_id, "signals.json", [])
    rs.finish(run.run_id, "complete", cost_usd=0.01)
    body = c.get("/").text
    assert "<polyline" not in body


def test_every_page_renders_with_strictundefined(client):
    """StrictUndefined turns a typo'd variable into a 500. Walk every GET."""
    c, ts, _ = client
    t = ts.create(name="OIC", therapeutic_area="gi", spend_band="probe")
    for path in ("/", "/how", "/deliverables", "/topics/new",
                 f"/topics/{t.topic_id}", f"/topics/{t.topic_id}/edit",
                 f"/topics/{t.topic_id}/confirm?band=probe"):
        assert c.get(path).status_code == 200, path


def test_how_page_renders_a_glossary_term_and_a_mode_name(client):
    """content.py's GLOSSARY and MODES are finished copy; /how must actually
    render them, not just have a route that returns something."""
    c, _, _ = client
    body = c.get("/how").text
    assert "Momentum" in body  # a GLOSSARY term
    assert "Insight" in body  # a MODES name
    assert "corroborated" in body.lower()  # a TIERS key


def test_the_empty_state_contains_the_three_first_run_steps(client):
    """FIRST_RUN_STEPS replaces the old empty-state paragraph: three
    numbered steps that teach, not a paragraph reporting emptiness."""
    from vsm.ui.content import FIRST_RUN_STEPS

    c, _, _ = client
    body = c.get("/").text
    # Assert against the content module, never a literal: copy is edited far
    # more often than markup, and a test that pins the words fails on every
    # wording change while proving nothing about the rendering.
    assert len(FIRST_RUN_STEPS) == 3
    for heading, _detail in FIRST_RUN_STEPS:
        assert heading in body, f"first-run step missing from the empty state: {heading}"
    assert "Run it again next week" in body


def test_the_page_requests_nothing_from_the_network(client):
    """No CDN, no external font, no build step — it must work on a plane."""
    c, ts, _ = client
    ts.create(name="OIC", therapeutic_area="gi", spend_band="probe")
    body = c.get("/").text
    assert "//fonts.googleapis" not in body
    assert "https://cdn" not in body
    assert "http://" not in body.replace("http://www.w3.org", "")


# --- The deliverables surface (the moat, made visible) ----------------------


def test_deliverables_page_renders_every_group_and_an_artifact_filename(client):
    """/deliverables is the page someone reads to decide whether the tool is
    worth running — every DELIVERABLE_GROUPS label must actually render, and
    at least one real filename must be on the page, not just a route that
    returns 200."""
    from vsm.ui.content import DELIVERABLE_GROUPS, DELIVERABLES

    c, _, _ = client
    body = c.get("/deliverables").text
    for _key, label, _desc in DELIVERABLE_GROUPS:
        assert label in body, f"group label missing from /deliverables: {label}"
    assert DELIVERABLES[0]["file"] in body


def test_a_never_run_topic_lists_the_deliverables_pending(client):
    """The owner asked for this explicitly: a topic that has never been run
    must show the same deliverables list with nothing filled in yet, so a
    user can see the shape of the output before spending money."""
    from vsm.ui.content import DELIVERABLES

    c, ts, _ = client
    t = ts.create(name="Never run", therapeutic_area="gi", spend_band="probe")
    body = c.get(f"/topics/{t.topic_id}").text
    assert "Not run yet" in body
    assert DELIVERABLES[0]["name"] in body


def test_confirm_screen_shows_the_pre_run_deliverables_too(client):
    """Same requirement, the other place the owner named: confirm-spend, the
    screen right before money is spent."""
    c, ts, _ = client
    t = ts.create(name="OIC", therapeutic_area="gi", spend_band="probe")
    body = c.get(f"/topics/{t.topic_id}/confirm?band=probe").text
    assert "Not run yet" in body


# --- Only the topic name is required -----------------------------------


def test_posting_only_a_name_creates_a_topic(client):
    """A molecule is not always relevant, and neither is anything else on
    the form — only `name` may be required."""
    c, ts, _ = client
    r = c.post("/topics", data={"name": "Bare topic"}, follow_redirects=False)
    assert r.status_code in (302, 303)
    created = ts.list()
    assert [t.name for t in created] == ["Bare topic"]
    assert created[0].spend_band in ("probe", "standard", "deep")


def test_the_topic_form_marks_exactly_one_field_required(client):
    """A molecule is not always relevant, and the form must not imply
    otherwise — `name` is the only required field, visually distinct from
    every optional one."""
    c, _, _ = client
    body = c.get("/topics/new").text
    assert body.count("Required") == 1
    assert "Optional" in body
