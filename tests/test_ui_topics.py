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
    for path in ("/", "/how", "/topics/new", f"/topics/{t.topic_id}/edit",
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
    c, _, _ = client
    body = c.get("/").text
    assert "Create a topic" in body
    assert "Run a snapshot" in body
    assert "Run it again next week" in body


def test_the_page_requests_nothing_from_the_network(client):
    """No CDN, no external font, no build step — it must work on a plane."""
    c, ts, _ = client
    ts.create(name="OIC", therapeutic_area="gi", spend_band="probe")
    body = c.get("/").text
    assert "//fonts.googleapis" not in body
    assert "https://cdn" not in body
    assert "http://" not in body.replace("http://www.w3.org", "")
