import pytest
from fastapi.testclient import TestClient

from vsm.modes.insight import run_insight
from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore
from vsm.ui.app import create_app


@pytest.fixture
def env(tmp_path):
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    topic = ts.create(name="OIC", therapeutic_area="gastroenterology", spend_band="probe")
    return TestClient(create_app(topic_store=ts, run_store=rs)), ts, rs, topic


def _rows(n_hcp, n_patient):
    rows = [{"signal_id": f"h{i}", "venue": "studentdoctor.net", "theme": "tolerability",
             "title": f"t{i}", "excerpt": "tolerability", "captured_at": "2026-08-25T00:00:00+00:00",
             "collection_method": "serp_result", "url": f"https://studentdoctor.net/{i}"}
            for i in range(n_hcp)]
    rows += [{"signal_id": f"p{i}", "venue": "patient.info", "theme": "tolerability",
              "title": f"p{i}", "excerpt": "tolerability", "captured_at": "2026-08-25T00:00:00+00:00",
              "collection_method": "serp_result", "url": f"https://patient.info/{i}"}
             for i in range(n_patient)]
    return rows


def _snapshot(rs, topic, rows):
    run = rs.start(topic.topic_id, "mine")
    rs.write_artifact(run.run_id, "signals.json", rows)
    rs.write_artifact(run.run_id, "coverage.json", {"venues_attempted": [], "venues_collected": [], "venues_empty": []})
    rs.finish(run.run_id, "complete", cost_usd=0.01)
    return run


def test_the_snapshot_view_lists_its_signals(env):
    c, ts, rs, topic = env
    snap = _snapshot(rs, topic, _rows(2, 1))
    body = c.get(f"/runs/{snap.run_id}/snapshot").text
    assert "studentdoctor.net" in body and "patient.info" in body


def test_the_insight_view_leads_with_the_dual_lens_gap(env):
    """It is the output nobody thinks to ask for, so it does not go below the
    fold behind a chart they already know how to read."""
    c, ts, rs, topic = env
    snap = _snapshot(rs, topic, _rows(2, 2))
    ins = run_insight(topic, snap.run_id, rs)
    body = c.get(f"/runs/{ins.run_id}/insight").text
    gap_at = body.lower().find("dual-lens")
    momentum_at = body.lower().find("momentum")
    assert gap_at != -1 and momentum_at != -1 and gap_at < momentum_at


def test_first_snapshot_says_no_prior_snapshot_in_words(env):
    """Not an empty chart. An empty chart reads as 'nothing is happening'."""
    c, ts, rs, topic = env
    snap = _snapshot(rs, topic, _rows(2, 1))
    ins = run_insight(topic, snap.run_id, rs)
    body = c.get(f"/runs/{ins.run_id}/insight").text
    assert "no prior snapshot" in body.lower()


def test_a_finished_run_renders_without_scripting(env):
    c, ts, rs, topic = env
    snap = _snapshot(rs, topic, _rows(1, 1))
    body = c.get(f"/runs/{snap.run_id}").text
    assert "complete" in body.lower()


def test_the_plot_legend_appears_beside_the_forest_plot(env):
    """PLOT_GUIDE belongs beside the plot, not on a help page — and behind a
    disclosure rather than in front of the reader.

    The summary no longer says "Why some rows say NE": `NE` was an internal
    token surfaced raw, and naming the fact ("can't be compared") is the point
    of the vocabulary pass. The structural requirement this test was written for
    is unchanged — the guide is on this page, and it is inside a `<details>`.
    """
    c, ts, rs, topic = env
    snap = _snapshot(rs, topic, _rows(2, 2))
    ins = run_insight(topic, snap.run_id, rs)
    body = c.get(f"/runs/{ins.run_id}/insight").text
    assert "Box size" in body                      # a PLOT_GUIDE mark label
    assert "<details" in body and "How to read this" in body
    assert "say NE" not in body, "the raw token is back"


def test_a_tier_key_is_present_where_tiers_are_shown(env):
    """A reader must never meet 'corroborated' with no way to learn what it
    means — the tier's own definition rides along as a title attribute."""
    c, ts, rs, topic = env
    snap = _snapshot(rs, topic, _rows(2, 2))
    ins = run_insight(topic, snap.run_id, rs)
    body = c.get(f"/runs/{ins.run_id}/insight").text
    assert "Three or more independent sources" in body


def test_the_stance_view_never_shows_a_blended_number(env):
    """The type has nowhere to put one; the template must not compute one either."""
    c, ts, rs, topic = env
    snap = _snapshot(rs, topic, _rows(2, 2))
    ins = run_insight(topic, snap.run_id, rs)
    body = c.get(f"/runs/{ins.run_id}/insight").text.lower()
    assert "overall sentiment" not in body
    assert "hcp" in body and "patient" in body
