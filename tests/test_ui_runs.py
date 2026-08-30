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


def test_a_first_sweep_says_there_is_no_baseline_in_words(env):
    """Not an empty chart. An empty chart reads as 'nothing is happening'.

    The assertion was `"no prior snapshot" in body`, which pinned the state to
    the internal word: "snapshot" is banned from anything a reader sees (it is
    "sweep"), and that string was reaching the page as a raw `reason` field
    from `vsm/analysis/momentum.py`. The state itself is what matters, so the
    test now requires it to be named — in a real empty state, in the product's
    own vocabulary — rather than requiring one particular sentence.
    """
    c, ts, rs, topic = env
    snap = _snapshot(rs, topic, _rows(2, 1))
    ins = run_insight(topic, snap.run_id, rs)
    body = c.get(f"/runs/{ins.run_id}/insight").text
    assert "first sweep of this topic" in body.lower()
    assert 'class="empty-state"' in body, "the state is drawn, not named"
    assert "no prior snapshot" not in body.lower(), "the internal word is back"


def test_a_finished_run_renders_without_scripting(env):
    c, ts, rs, topic = env
    snap = _snapshot(rs, topic, _rows(1, 1))
    body = c.get(f"/runs/{snap.run_id}").text
    assert "complete" in body.lower()


def test_the_method_behind_the_gap_sits_beside_the_gap(env):
    """The method belongs beside the figure, not on a help page — and behind a
    disclosure rather than in front of the reader.

    Two earlier versions of this test pinned `PLOT_GUIDE` strings ("Why some
    rows say NE", then "Box size" and "How to read this"). `NE` went first
    because it was an internal token surfaced raw; the rest went with the
    forest plot itself, since "Box size" and "Whisker" describe marks the gap
    figure does not have. A legend for a retired chart is not method. What the
    reader actually needs — how a mention is attributed to clinicians or to
    patients — is asserted instead, in the same place and behind the same kind
    of control.
    """
    c, ts, rs, topic = env
    snap = _snapshot(rs, topic, _rows(2, 2))
    ins = run_insight(topic, snap.run_id, rs)
    body = c.get(f"/runs/{ins.run_id}/insight").text
    assert "<details" in body and "told apart" in body
    assert "taken from the site a mention came from" in body
    assert "say NE" not in body, "the raw token is back"


def test_the_source_count_carries_its_meaning_where_it_is_shown(env):
    """A reader must never meet a confidence signal with no way to learn what
    it means. The old fix attached a definition of the word "corroborated";
    the better fix was to stop using the word — the count *is* the label — and
    to put what the count licenses behind the (i) beside it."""
    c, ts, rs, topic = env
    snap = _snapshot(rs, topic, _rows(2, 2))
    ins = run_insight(topic, snap.run_id, rs)
    body = c.get(f"/runs/{ins.run_id}/insight").text
    assert "Three or more independent sources" in body or "3+ sources" in body, (
        "the reader has no way to learn what the count licenses"
    )


def test_the_stance_view_never_shows_a_blended_number(env):
    """The type has nowhere to put one; the template must not compute one either."""
    c, ts, rs, topic = env
    snap = _snapshot(rs, topic, _rows(2, 2))
    ins = run_insight(topic, snap.run_id, rs)
    body = c.get(f"/runs/{ins.run_id}/insight").text.lower()
    assert "overall sentiment" not in body
    assert "hcp" in body and "patient" in body
