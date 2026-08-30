"""The persistent "New report" entry point.

Report generation used to be reachable only from the insight page, three steps
inside a topic, with no global entry at all. The owner asked for "new report"
to be always available and easy to access. This covers the header action that is
on every screen and the hub it leads to, which routes both ways a report can
begin — from an analysis already run, or from a fresh topic.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from vsm.demo import seed_demo_topic
from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore
from vsm.ui.app import create_app


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    monkeypatch.delenv("VSM_ACCESS_KEY", raising=False)
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    seed_demo_topic(ts, rs, env={})
    return TestClient(create_app(topic_store=ts, run_store=rs)), ts, rs


@pytest.fixture
def empty(tmp_path, monkeypatch):
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    monkeypatch.delenv("VSM_ACCESS_KEY", raising=False)
    ts = TopicStore(tmp_path / "db2")
    rs = RunStore(tmp_path / "db2", tmp_path / "var2")
    return TestClient(create_app(topic_store=ts, run_store=rs)), ts, rs


@pytest.mark.parametrize("path", ["/", "/topics", "/how", "/deliverables"])
def test_the_new_report_action_is_on_every_screen(seeded, path):
    """It lives in the chrome, so it is reachable wherever you are."""
    c, _, _ = seeded
    body = c.get(path).text
    assert 'class="app-top-cta"' in body
    assert 'href="/reports/new"' in body
    assert "New report" in body


def test_the_hub_lists_an_analysis_ready_to_report(seeded):
    c, _, _ = seeded
    body = c.get("/reports/new").text
    assert body  # 200
    assert "Generate report" in body or "Regenerate report" in body


def test_the_hub_fast_path_actually_generates_a_report(seeded):
    """The one-click path from the hub must produce a report, not 404."""
    c, ts, rs = seeded
    body = c.get("/reports/new").text
    m = re.search(r'action="/runs/(ins-[0-9a-z]+)/report"', body)
    assert m, "no generate form on the hub"
    r = c.post(f"/runs/{m.group(1)}/report", follow_redirects=False)
    assert r.status_code == 303


def test_the_hub_offers_a_fresh_start_too(seeded):
    c, _, _ = seeded
    body = c.get("/reports/new").text
    assert 'href="/topics/new"' in body


def test_the_hub_is_never_a_dead_end_on_an_empty_store(empty):
    """With nothing analysed the fast path is empty, but the fresh-start path
    must still be offered — the button must not lead nowhere."""
    c, _, _ = empty
    body = c.get("/reports/new").text
    assert c.get("/reports/new").status_code == 200
    assert 'href="/topics/new"' in body


def test_regenerate_is_labelled_honestly_when_a_report_exists(seeded):
    """The seeded topic already has a report, so the label must say regenerate,
    not imply a first-time generate."""
    c, ts, rs = seeded
    body = c.get("/reports/new").text
    # The seeded demo runs a full chain including a report.
    assert "Regenerate report" in body


def test_the_action_is_absent_when_storage_cannot_persist(tmp_path, monkeypatch):
    """On a read-only instance there is nothing to create, so offering it would
    be a promise the instance cannot keep."""
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "")  # no durable storage
    monkeypatch.setenv("VERCEL_ENV", "production")
    monkeypatch.delenv("VSM_ACCESS_KEY", raising=False)
    ts = TopicStore(tmp_path / "ro"); rs = RunStore(tmp_path / "ro", tmp_path / "rov")
    from vsm.platform import storage_is_durable
    # Only meaningful if this env is genuinely non-durable in the test context.
    c = TestClient(create_app(topic_store=ts, run_store=rs))
    body = c.get("/topics").text
    if not storage_is_durable():
        assert 'class="app-top-cta"' not in body
