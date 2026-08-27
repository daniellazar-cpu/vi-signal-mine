"""The index stops rendering somewhere, and says so.

Measured at ~677 bytes of HTML per row: 400 topics is a 269KB document. The
query cost is already flat (`for_topics`), so this is about document weight, and
the honest fix for an internal tool that already has search and filters is a cap
that announces itself — not pagination machinery whose page state has to be
carried through sort, filter and search.

The failure mode being guarded is a cap that renders the first fifty and says
nothing, which is indistinguishable from having only fifty.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore
from vsm.ui.app import create_app


def _names(body: str) -> list[str]:
    return re.findall(r'class="topic-name-link"[^>]*>([^<]+)<', body)


@pytest.fixture
def many(tmp_path, monkeypatch):
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    monkeypatch.delenv("VSM_ACCESS_KEY", raising=False)
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    for i in range(120):
        ts.create(topic_id=f"top-{i:04d}", name=f"Topic {i:03d}",
                  therapeutic_area="Oncology", spend_band="probe")
    return TestClient(create_app(topic_store=ts, run_store=rs)), ts


def test_a_long_list_is_capped(many):
    client, ts = many
    body = client.get("/topics").text
    assert len(_names(body)) == 50, len(_names(body))


def test_the_cap_says_how_much_it_is_hiding(many):
    """Silently truncating reads as "this is all there is"."""
    client, ts = many
    body = client.get("/topics").text
    assert "Showing the first 50 of 120" in body
    assert "120 topics" in body, "the true total is not stated"


def test_the_cap_offers_the_whole_list(many):
    client, _ = many
    body = client.get("/topics").text
    m = re.search(r'href="(/topics\?[^"]*all=1)"', body)
    assert m, "no escape hatch from the cap"
    assert len(_names(client.get(m.group(1).replace("&amp;", "&")).text)) == 120


def test_show_all_confirms_it_is_showing_all(many):
    client, _ = many
    body = client.get("/topics?all=1").text
    assert "Showing all 120 topics" in body


def test_the_escape_hatch_keeps_the_search_and_sort(many):
    """Escaping the cap must not silently reset the view."""
    client, _ = many
    # A search that still exceeds the cap, so the escape hatch is actually
    # rendered — a skip here would mean this never checked anything.
    body = client.get("/topics?q=Topic&sort=name&show=all").text
    assert len(_names(body)) == 50, "fixture no longer exceeds the cap under search"
    m = re.search(r'href="(/topics\?[^"]*all=1)"', body)
    assert m, "no escape hatch rendered"
    href = m.group(1)
    assert "q=Topic" in href and "sort=name" in href, href
    # And following it must keep both.
    kept = client.get(href.replace("&amp;", "&")).text
    assert len(_names(kept)) == 120
    assert 'value="Topic"' in kept, "the search box lost its query"


def test_a_short_list_says_nothing_about_a_cap(many, tmp_path, monkeypatch):
    """A message about truncation on a list of three is noise."""
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    ts = TopicStore(tmp_path / "short")
    rs = RunStore(tmp_path / "short", tmp_path / "shortvar")
    for i in range(3):
        ts.create(topic_id=f"top-s{i}", name=f"Short {i}",
                  therapeutic_area="", spend_band="probe")
    client = TestClient(create_app(topic_store=ts, run_store=rs))
    body = client.get("/topics").text
    assert "Showing the first" not in body
    assert "Showing all" not in body
    assert "3 topics" in body


def test_the_cap_applies_after_filtering_not_before(many):
    """Capping the list and *then* filtering it would show a handful of rows and
    claim they are all that match — the subtlest way to get this wrong."""
    client, ts = many
    body = client.get("/topics?show=empty").text          # all 120 are never-run
    assert len(_names(body)) == 50
    assert "of 120" in body


def test_the_capped_document_stays_small(many):
    """The reason the cap exists at all."""
    client, _ = many
    assert len(client.get("/topics").text) < 60_000
    assert len(client.get("/topics?all=1").text) > 60_000, "fixture too small to prove anything"
