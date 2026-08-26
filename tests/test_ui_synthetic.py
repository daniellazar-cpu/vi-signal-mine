"""The synthetic-run banner: unmissable on every screen built over a
fabricated sweep, absent everywhere else. Not a subtle badge — the failure
this prevents is a demonstration deliverable downloaded and handed to a
client with no visible sign it was never collected."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from vsm.mining.fake import DeterministicMiner
from vsm.modes.insight import run_insight
from vsm.modes.mine import run_mine
from vsm.modes.report import run_report
from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore
from vsm.ui.app import create_app

_BANNER_MARK = "synthetic-banner"


@pytest.fixture
def synthetic_flow(tmp_path):
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    topic = ts.create(name="Demo Topic", therapeutic_area="", spend_band="standard")
    mine = run_mine(topic, rs, miner=DeterministicMiner(queries_per_cluster=4), cluster_count=1)
    insight = run_insight(topic, mine.run_id, rs, client=None)
    report = run_report(topic, insight.run_id, rs, client=None)
    client = TestClient(create_app(topic_store=ts, run_store=rs))
    return client, rs, mine, insight, report


@pytest.fixture
def live_shaped_flow(tmp_path):
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    topic = ts.create(name="Live Topic", therapeutic_area="gi", spend_band="probe")
    rows = [
        {"signal_id": f"s{i}", "venue": f"v{i}.example.org", "theme": "tolerability",
         "title": f"t{i}", "excerpt": "tolerability",
         "captured_at": "2026-08-25T00:00:00+00:00", "collection_method": "serp_result",
         "url": f"https://v{i}.example.org/{i}"}
        for i in range(4)
    ]
    mine = rs.start(topic.topic_id, "mine")
    rs.write_artifact(mine.run_id, "signals.json", rows)
    rs.finish(mine.run_id, "complete", cost_usd=0.01)
    insight = run_insight(topic, mine.run_id, rs)
    report = run_report(topic, insight.run_id, rs)
    client = TestClient(create_app(topic_store=ts, run_store=rs))
    return client, rs, mine, insight, report


def test_banner_appears_on_the_run_screen(synthetic_flow):
    client, _rs, mine, _ins, _rep = synthetic_flow
    body = client.get(f"/runs/{mine.run_id}").text
    assert _BANNER_MARK in body


def test_banner_appears_on_the_snapshot_screen(synthetic_flow):
    client, _rs, mine, _ins, _rep = synthetic_flow
    body = client.get(f"/runs/{mine.run_id}/snapshot").text
    assert _BANNER_MARK in body


def test_banner_appears_on_the_insight_screen(synthetic_flow):
    client, _rs, _mine, insight, _rep = synthetic_flow
    body = client.get(f"/runs/{insight.run_id}/insight").text
    assert _BANNER_MARK in body


def test_banner_appears_on_the_report_screen(synthetic_flow):
    client, _rs, _mine, _ins, report = synthetic_flow
    body = client.get(f"/runs/{report.run_id}/report").text
    assert _BANNER_MARK in body


def test_banner_is_absent_on_a_live_shaped_run_screen(live_shaped_flow):
    client, _rs, mine, _ins, _rep = live_shaped_flow
    body = client.get(f"/runs/{mine.run_id}").text
    assert _BANNER_MARK not in body


def test_banner_is_absent_on_a_live_shaped_snapshot_screen(live_shaped_flow):
    client, _rs, mine, _ins, _rep = live_shaped_flow
    body = client.get(f"/runs/{mine.run_id}/snapshot").text
    assert _BANNER_MARK not in body


def test_banner_is_absent_on_a_live_shaped_insight_screen(live_shaped_flow):
    client, _rs, _mine, insight, _rep = live_shaped_flow
    body = client.get(f"/runs/{insight.run_id}/insight").text
    assert _BANNER_MARK not in body


def test_banner_is_absent_on_a_live_shaped_report_screen(live_shaped_flow):
    client, _rs, _mine, _ins, report = live_shaped_flow
    body = client.get(f"/runs/{report.run_id}/report").text
    assert _BANNER_MARK not in body


def test_topic_mine_route_wires_get_miner_and_actually_collects_rows(tmp_path):
    """End-to-end through the route ui/app.py wires — this is the exact gap
    the task named: run_mine was being called with no miner, so outcome was
    always None and every sweep produced zero signals. Under VSM_OFFLINE=1
    (this suite's default posture — see tests/conftest.py's socket guard and
    vsm.config.Settings.offline defaulting True) the topic-mine POST must
    now come back with a real, non-empty snapshot."""
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    topic = ts.create(name="Wiring Check", therapeutic_area="", spend_band="standard")
    client = TestClient(create_app(topic_store=ts, run_store=rs))

    resp = client.post(f"/topics/{topic.topic_id}/mine", data={}, follow_redirects=False)
    assert resp.status_code == 303
    run_id = resp.headers["location"].rsplit("/", 1)[-1]
    rows = rs.read_artifact(run_id, "signals.json")
    assert rows, "the sweep must have actually collected rows, not zero"
    assert all(r.get("synthetic") for r in rows)
