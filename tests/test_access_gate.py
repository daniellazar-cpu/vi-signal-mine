"""The gate `production_is_safe` claimed to have.

`VSM_ACCESS_KEY` was read in exactly one place — to decide whether serving was
*permitted* — and nothing ever checked a request against it. So the one
combination the guard exists to make safe, live API keys behind a shared secret,
put no secret in front of anything: a visitor with the URL could start sweeps
that spend real money.

`tests/test_platform.py::test_production_serves_when_an_access_key_gates_it`
named the property and asserted only that serving was allowed. It locked the
hole in rather than catching it, which is the sixteenth instance of that pattern
in this build.
"""

from __future__ import annotations

import base64

import pytest
from starlette.testclient import TestClient

from vsm.demo import seed_demo_topic
from vsm.platform import RequireAccessKey
from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore
from vsm.ui.app import create_app

_KEY = "a-shared-secret"


def _auth(password: str, user: str = "anyone") -> dict[str, str]:
    raw = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {raw}"}


@pytest.fixture
def gated(tmp_path, monkeypatch):
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    monkeypatch.setenv("VSM_ACCESS_KEY", _KEY)
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    seed_demo_topic(ts, rs, env={})
    inner = create_app(topic_store=ts, run_store=rs)
    return TestClient(RequireAccessKey(inner)), ts, rs


@pytest.fixture
def ungated(tmp_path, monkeypatch):
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    monkeypatch.delenv("VSM_ACCESS_KEY", raising=False)
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    seed_demo_topic(ts, rs, env={})
    return TestClient(RequireAccessKey(create_app(topic_store=ts, run_store=rs)))


def test_without_the_key_nothing_is_served(gated):
    client, _, _ = gated
    r = client.get("/")
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Basic ")


def test_the_right_key_gets_in(gated):
    client, _, _ = gated
    assert client.get("/", headers=_auth(_KEY)).status_code == 200


def test_any_username_works_because_the_secret_is_shared(gated):
    client, _, _ = gated
    # A username may not contain a colon (RFC 7617 splits at the first one), so
    # "a:b" is not a username — it is a username plus part of a password.
    for user in ("", "anyone", "daniel.lazar@vi.co", "Vi Labs"):
        assert client.get("/", headers=_auth(_KEY, user)).status_code == 200, user


def test_a_key_containing_a_colon_still_works(tmp_path, monkeypatch):
    """The real consequence of RFC 7617's first-colon split, and the one worth
    testing: everything after the first colon is the password, so a generated
    key with a colon in it must not be silently truncated."""
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    key = "vi:signal:mine:9f2a"
    monkeypatch.setenv("VSM_ACCESS_KEY", key)
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    seed_demo_topic(ts, rs, env={})
    client = TestClient(RequireAccessKey(create_app(topic_store=ts, run_store=rs)))

    assert client.get("/", headers=_auth(key)).status_code == 200
    # And a prefix of it must not get in.
    assert client.get("/", headers=_auth("vi")).status_code == 401


def test_a_wrong_key_is_refused(gated):
    client, _, _ = gated
    for wrong in ("", "wrong", _KEY + "x", _KEY[:-1], _KEY.upper()):
        assert client.get("/", headers=_auth(wrong)).status_code == 401, wrong


def test_a_malformed_authorization_header_is_refused_not_crashed(gated):
    client, _, _ = gated
    for value in ("Basic", "Basic !!!not-base64!!!", "Bearer " + _KEY,
                  "Basic " + base64.b64encode(b"no-colon").decode(),
                  "Basic " + base64.b64encode(b"\xff\xfe").decode()):
        r = client.get("/", headers={"Authorization": value})
        assert r.status_code == 401, value


@pytest.mark.parametrize("path", [
    "/", "/how", "/deliverables", "/topics/new", "/static/app.css",
    "/nonsense-that-does-not-exist", "/runs/min-nope/report",
])
def test_the_gate_covers_every_surface_including_static_and_404s(gated, path):
    """A gate that only wraps the pages someone remembered to decorate is not a
    gate. Static assets and error pages are behind it too."""
    client, _, _ = gated
    assert client.get(path).status_code == 401, path


def test_mutating_routes_are_gated_too(gated):
    """The reason this exists: an ungated POST can spend money."""
    client, ts, _ = gated
    topic = ts.list()[0]
    for method, path in [("post", "/topics"),
                         ("post", f"/topics/{topic.topic_id}/mine"),
                         ("post", f"/topics/{topic.topic_id}/delete")]:
        r = getattr(client, method)(path, data={})
        assert r.status_code == 401, path


def test_with_no_key_set_the_app_is_wide_open_as_before(ungated):
    """Local development must be untouched. The gate is inert unless the
    variable is set, which is also what keeps the whole existing suite valid."""
    assert ungated.get("/").status_code == 200


def test_the_key_is_read_per_request_not_captured_at_import(gated, monkeypatch):
    """On a serverless host the module can be imported before the environment
    is fully populated. A gate that cached an empty key at construction would be
    permanently open — the failure mode is silent and total."""
    client, _, _ = gated
    assert client.get("/").status_code == 401
    monkeypatch.delenv("VSM_ACCESS_KEY", raising=False)
    assert client.get("/").status_code == 200
    monkeypatch.setenv("VSM_ACCESS_KEY", _KEY)
    assert client.get("/").status_code == 401


def test_the_challenge_says_what_to_type(gated):
    """A browser prompt with no explanation is a dead end. The body names the
    key and says the username does not matter."""
    client, _, _ = gated
    body = client.get("/").text.lower()
    assert "access key" in body and "password" in body and "username" in body


def test_the_refusal_is_not_cacheable(gated):
    """A shared cache holding a 401 — or worse, a page fetched with someone
    else's credentials — is the classic way a gate like this leaks."""
    client, _, _ = gated
    assert "no-store" in client.get("/").headers.get("cache-control", "")


def test_comparison_is_constant_time():
    """Structural: a plain `==` on a secret leaks it a character at a time
    through response timing. Asserted on the source because timing itself is
    not measurable reliably in a test."""
    import inspect

    src = inspect.getsource(RequireAccessKey.__call__)
    assert "compare_digest" in src, "the key is compared with something else"
    assert "== expected" not in src and "expected ==" not in src
