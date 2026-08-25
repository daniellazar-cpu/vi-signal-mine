"""Spec D15's production-refusal guard, wired as ASGI middleware in
``vsm/ui/app.py``. The one property worth pinning at the HTTP layer — beyond
``tests/test_platform.py``'s direct unit tests of ``assert_serveable`` — is
that the middleware actually wraps *every* route, including a mounted static
file. A per-route dependency would pass a test that only ever hits `/`; this
asserts the static mount specifically because that is exactly the kind of
route a per-route guard would silently miss.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore
from vsm.ui.app import create_app


@pytest.fixture
def client(tmp_path):
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    return TestClient(create_app(topic_store=ts, run_store=rs))


def test_a_production_deployment_answers_503_on_the_home_page(client, monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "production")
    r = client.get("/")
    assert r.status_code == 503
    assert "production" in r.text.lower()


def test_a_production_deployment_answers_503_on_a_static_file_too(client, monkeypatch):
    """The exact case a per-route dependency would miss: a mounted
    sub-application, not a route this app's router dispatches directly."""
    monkeypatch.setenv("VERCEL_ENV", "production")
    r = client.get("/static/app.css")
    assert r.status_code == 503


def test_a_preview_deployment_serves_normally(client, monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "preview")
    assert client.get("/").status_code == 200
    assert client.get("/static/app.css").status_code == 200


def test_local_serves_normally_with_no_vercel_env_set(client, monkeypatch):
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    assert client.get("/").status_code == 200
