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


def test_production_with_live_keys_and_no_gate_answers_503(client, monkeypatch):
    """The one combination that is actually dangerous.

    Vercel gates preview deployments only on this plan, so a production URL is
    reachable by anyone holding it. What makes that matter is the live keys
    behind it, which can spend real money — so this is the case that refuses.
    """
    monkeypatch.setenv("VERCEL_ENV", "production")
    monkeypatch.setenv("VSM_OFFLINE", "0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-live-looking-key")
    monkeypatch.delenv("VSM_ACCESS_KEY", raising=False)
    r = client.get("/")
    assert r.status_code == 503
    # The refusal has to say what would fix it, or it is just a dead page.
    assert "VSM_ACCESS_KEY" in r.text
    assert "VSM_OFFLINE" in r.text


def test_the_503_covers_a_static_file_too(client, monkeypatch):
    """The exact case a per-route dependency would miss: a mounted
    sub-application, not a route this app's router dispatches directly."""
    monkeypatch.setenv("VERCEL_ENV", "production")
    monkeypatch.setenv("VSM_OFFLINE", "0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-live-looking-key")
    monkeypatch.delenv("VSM_ACCESS_KEY", raising=False)
    assert client.get("/static/app.css").status_code == 503


def test_production_serves_when_offline_because_there_is_nothing_to_spend(
    client, monkeypatch
):
    """A fresh deployment with no secrets is inert, so it may be clicked.

    This is the case the first version of this guard got wrong: it refused all
    production traffic, which made the URL a person naturally lands on
    permanently dead. A dead URL reads as a broken deployment, not a protected
    one — and there is nothing to protect when no outbound call is possible.
    """
    monkeypatch.setenv("VERCEL_ENV", "production")
    monkeypatch.setenv("VSM_OFFLINE", "1")
    monkeypatch.delenv("VSM_ACCESS_KEY", raising=False)
    assert client.get("/").status_code == 200


def test_production_serves_when_an_access_key_gates_it(client, monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "production")
    monkeypatch.setenv("VSM_OFFLINE", "0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-live-looking-key")
    monkeypatch.setenv("VSM_ACCESS_KEY", "a-shared-secret")
    assert client.get("/").status_code == 200


def test_a_preview_deployment_serves_normally(client, monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "preview")
    assert client.get("/").status_code == 200
    assert client.get("/static/app.css").status_code == 200


def test_local_serves_normally_with_no_vercel_env_set(client, monkeypatch):
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    assert client.get("/").status_code == 200
