import pytest
from fastapi.testclient import TestClient

from vsm.modes.insight import run_insight
from vsm.modes.report import run_report
from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore
from vsm.ui.app import create_app


@pytest.fixture
def env(tmp_path):
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
    ins = run_insight(topic, mine.run_id, rs)
    rep = run_report(topic, ins.run_id, rs)
    return TestClient(create_app(topic_store=ts, run_store=rs)), rs, rep, rows


def test_every_cited_signal_id_is_a_link_to_its_url(env):
    c, rs, rep, rows = env
    body = c.get(f"/runs/{rep.run_id}/report").text
    for row in rows:
        if row["signal_id"] in body:
            assert row["url"] in body, row["signal_id"]


def test_the_source_count_is_visible_on_the_page(env):
    c, rs, rep, _ = env
    body = c.get(f"/runs/{rep.run_id}/report").text.lower()
    # The count is the label now; "corroborated" was invented in this
    # codebase and the owner's reaction to meeting it was "wtf is that".
    assert "independent sources" in body or "3 or more sources" in body


def test_artifacts_download(env):
    c, rs, rep, _ = env
    r = c.get(f"/runs/{rep.run_id}/artifact/provenance_appendix.md")
    assert r.status_code == 200 and len(r.text) > 0


def test_an_artifact_name_cannot_traverse(env):
    c, rs, rep, _ = env
    assert c.get(f"/runs/{rep.run_id}/artifact/../../../etc/passwd").status_code in (400, 404)
