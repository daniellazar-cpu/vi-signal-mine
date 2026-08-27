"""The surfaces an audit found absent rather than wrong.

Three gaps, each of which a visitor reaches without doing anything unusual:

* a mistyped or stale URL returned FastAPI's default ``{"detail":"Not Found"}``
  — raw JSON, no navigation, no way back — while every 404 the routes raise
  themselves was already a designed page. The one 404 most likely to be reached
  was the only one that looked broken;
* ``/favicon.ico`` 404ed, which browsers request from the site root on every
  page load whether or not the page links an icon;
* ``TAGLINE`` was defined, exported and rendered nowhere.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from vsm.demo import seed_demo_topic
from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore
from vsm.ui.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    monkeypatch.delenv("VSM_ACCESS_KEY", raising=False)
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    seed_demo_topic(ts, rs, env={})
    return TestClient(create_app(topic_store=ts, run_store=rs))


# ------------------------------------------------------------- unrouted 404 --

@pytest.mark.parametrize("path", [
    "/nonsense", "/topics/../etc", "/runs", "/report", "/deliverables/extra",
    "/topics/top-abc/nope",
])
def test_an_unrouted_path_renders_the_app_s_own_error_page(client, path):
    r = client.get(path)
    assert r.status_code == 404, path
    assert "text/html" in r.headers["content-type"], f"{path} answered with {r.headers['content-type']}"
    body = r.text
    assert '{"detail"' not in body, f"{path} still returns raw JSON"
    assert "Page not found" in body, path


def test_the_error_page_is_a_way_back_not_a_dead_end(client):
    """The whole point. A 404 that cannot be navigated out of is the dead end
    the owner reported the app being full of."""
    body = client.get("/nonsense").text
    assert 'href="/"' in body, "no link home"
    assert "Signal Mine" in body, "no app chrome — the visitor cannot tell where they are"


def test_a_stale_topic_link_explains_itself(client):
    """The likeliest real case: a link shared into a chat, then the topic
    deleted. Blaming the address is wrong; it may have been valid."""
    body = client.get("/topics/top-deletedlongago").text
    assert "deleted" in body.lower() or "no topic" in body.lower()


def test_a_missing_static_asset_is_not_answered_with_a_page(client):
    """A stylesheet request that 404s must not receive HTML. Nothing renders it,
    and a browser asked to parse a page as CSS logs a confusing error."""
    r = client.get("/static/does-not-exist.css")
    assert r.status_code == 404
    assert "text/html" not in r.headers.get("content-type", "")


def test_a_wrong_method_is_explained_rather_than_dumped(client):
    r = client.get("/topics/new")
    assert r.status_code == 200
    r = client.request("DELETE", "/topics")
    assert r.status_code == 405
    assert '{"detail"' not in r.text


# ----------------------------------------------------------------- favicon --

def test_favicon_ico_is_served(client):
    """Requested from the site root by every browser, linked or not."""
    r = client.get("/favicon.ico")
    assert r.status_code == 200
    assert "svg" in r.headers["content-type"]


def test_every_page_links_an_icon(client):
    for path in ("/", "/how", "/deliverables", "/topics/new", "/nonsense"):
        body = client.get(path).text
        assert 'rel="icon"' in body, path


def test_the_icon_is_drawn_and_self_hosted(client):
    """No CDN, no emoji-in-a-box, and it has to survive 16px."""
    r = client.get("/static/icon.svg")
    assert r.status_code == 200
    svg = r.text
    assert "<svg" in svg and "http" not in svg.replace("http://www.w3.org/2000/svg", "")
    assert "#4F31F5" in svg, "the icon does not use the one accent colour"
    # A stroke thin enough to vanish at 16px is the classic mistake here.
    import re
    widths = [float(w) for w in re.findall(r'stroke-width="([0-9.]+)"', svg)]
    assert widths and min(widths) >= 1.5, f"stroke too thin for 16px: {widths}"


# ----------------------------------------------------------------- tagline --

def test_the_tagline_is_actually_shown_somewhere(client):
    """It was defined, exported, and rendered nowhere. Either it says something
    worth saying on a surface, or it should not exist."""
    from vsm.ui.content import TAGLINE

    seen = any(TAGLINE in client.get(p).text for p in ("/", "/how", "/deliverables"))
    assert seen, f"TAGLINE is still dead content: {TAGLINE!r}"


# ------------------------------------------------------- shareable metadata --

def test_every_page_has_a_description(client):
    """A link pasted into chat used to render as a bare URL. These reports are
    shared, so the preview card is part of the deliverable."""
    import re

    for path in ("/", "/how", "/deliverables", "/topics/new"):
        body = client.get(path).text
        m = re.search(r'<meta name="description" content="([^"]*)"', body)
        assert m and m.group(1).strip(), f"{path} has no description"


def test_the_preview_card_carries_the_page_s_own_title(client):
    import re

    for path in ("/", "/how", "/deliverables"):
        body = client.get(path).text
        title = re.search(r"<title>([^<]*)</title>", body).group(1).strip()
        og = re.search(r'<meta property="og:title" content="([^"]*)"', body).group(1).strip()
        assert og == title, f"{path}: og:title {og!r} != title {title!r}"


def test_no_og_image_is_advertised_that_cannot_render(client):
    """An `og:image` pointing at the SVG would be declined by most platforms.
    A text-only card that always works beats a broken thumbnail."""
    body = client.get("/").text
    assert 'property="og:image"' not in body
