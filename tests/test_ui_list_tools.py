"""Search, sort, filter — and deleting a topic.

The list had become noisy: sixty topics, most of them verification runs, with
no way to tell the real ones apart and no way to remove them. Both halves of
that are covered here.

Everything is server-side and expressed in the URL on purpose. A list that only
sorts once JavaScript runs cannot be shared, bookmarked, printed, or driven by a
screen reader, and this is a tool whose output people are meant to pass around.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from vsm.demo import seed_demo_topic
from vsm.errors import NoSuchTopic
from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore
from vsm.ui.app import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    seed_demo_topic(ts, rs, env={})          # one topic with real runs
    ts.create(topic_id="top-empty1", name="Never run alpha",
              therapeutic_area="Oncology", spend_band="probe")
    ts.create(topic_id="top-empty2", name="Never run beta",
              therapeutic_area="Cardiology", spend_band="probe", brand="Zephyrex")
    single = ts.create(topic_id="top-single", name="One sweep only",
                       therapeutic_area="", spend_band="probe")
    r = rs.start(single.topic_id, "mine")
    rs.finish(r.run_id, "complete", 0.25)
    rs.write_artifact(r.run_id, "signals.json", [{"i": i} for i in range(7)])
    return TestClient(create_app(topic_store=ts, run_store=rs)), ts, rs


def _names(body: str) -> list[str]:
    return re.findall(r'class="topic-name-link"[^>]*>([^<]+)<', body)


# ------------------------------------------------------------------ search --

def test_search_narrows_by_name(app):
    c, _, _ = app
    names = _names(c.get("/topics?q=never+run").text)
    assert names and all("Never run" in n for n in names), names


def test_search_matches_brand_not_only_name(app):
    """Someone hunting for a competitor's topic types the brand, not the title
    they gave it months ago."""
    c, _, _ = app
    assert _names(c.get("/topics?q=Zephyrex").text) == ["Never run beta"]


def test_search_matches_therapeutic_area(app):
    c, _, _ = app
    assert _names(c.get("/topics?q=oncology").text) == ["Never run alpha"]


def test_search_is_all_words_not_any(app):
    """"never beta" must not return every topic containing either word — with
    sixty topics an any-match search is no narrower than no search."""
    c, _, _ = app
    assert _names(c.get("/topics?q=never+beta").text) == ["Never run beta"]


def test_search_reports_how_much_it_hid(app):
    c, ts, _ = app
    body = c.get("/topics?q=Zephyrex").text
    assert f"of {len(ts.list())} topics" in body


# -------------------------------------------------------------------- sort --

def test_sort_by_name_is_alphabetical(app):
    c, _, _ = app
    names = _names(c.get("/topics?sort=name").text)
    assert names == sorted(names, key=str.lower), names


def test_oldest_is_the_exact_reverse_of_newest(app):
    c, _, _ = app
    assert _names(c.get("/topics?sort=oldest").text) == list(reversed(_names(c.get("/topics?sort=recent").text)))


def test_sort_by_activity_puts_the_most_watched_first(app):
    c, ts, rs = app
    order = _names(c.get("/topics?sort=activity").text)
    counts = []
    for name in order:
        topic = next(t for t in ts.list() if t.name == name)
        counts.append(len(rs.snapshots(topic.topic_id)))
    assert counts == sorted(counts, reverse=True), dict(zip(order, counts))


def test_an_unknown_sort_shows_the_list_rather_than_an_error(app):
    """These are shareable URLs; a stale bookmark should degrade, not 400."""
    c, ts, _ = app
    r = c.get("/topics?sort=by-vibes&show=nonsense")
    assert r.status_code == 200
    assert len(_names(r.text)) == len(ts.list())


# ------------------------------------------------------------------ filter --

def test_filter_empty_shows_only_topics_never_mined(app):
    c, _, _ = app
    assert sorted(_names(c.get("/topics?show=empty").text)) == ["Never run alpha", "Never run beta"]


def test_filter_watched_excludes_them(app):
    c, _, _ = app
    names = _names(c.get("/topics?show=watched").text)
    assert names and not any("Never run" in n for n in names), names


def test_filter_trend_needs_two_snapshots(app):
    """The distinction that matters analytically: momentum and anomaly mean
    nothing on a single snapshot, so "has a trend" is not "has been run"."""
    c, ts, rs = app
    for name in _names(c.get("/topics?show=trend").text):
        topic = next(t for t in ts.list() if t.name == name)
        assert len(rs.snapshots(topic.topic_id)) >= 2, name
    assert "One sweep only" not in _names(c.get("/topics?show=trend").text)


def test_filtering_to_nothing_is_not_the_first_run_screen(app):
    """Telling someone with sixty topics how to create their first one is not
    help. The empty *result* state is a different thing from the empty *store*
    state, and conflating them is the classic version of this bug."""
    c, _, _ = app
    body = c.get("/topics?q=zzzznotathing").text
    assert "Nothing matches this view" in body
    assert "Show all" in body
    assert "step-num" not in body, "showed the first-run walkthrough instead"


def test_the_current_sort_and_filter_are_marked_for_assistive_tech(app):
    c, _, _ = app
    body = c.get("/topics?sort=name&show=empty").text
    on = re.findall(r'<a class="chip chip-on"[^>]*aria-current="true"', body)
    assert len(on) == 2, "the active sort and filter should both be marked"


def test_the_links_preserve_the_other_two_settings(app):
    """Changing the sort must not silently drop the search — the commonest way
    a filter toolbar wastes someone's time."""
    c, _, _ = app
    body = c.get("/topics?q=never&show=empty&sort=name").text
    for href in re.findall(r'class="chip[^"]*"[^>]*href="([^"]+)"', body):
        assert "q=never" in href, href


# ------------------------------------------------------------------ delete --

def test_the_confirm_page_counts_what_will_go(app):
    c, ts, rs = app
    topic = next(t for t in ts.list() if t.name == "One sweep only")
    body = c.get(f"/topics/{topic.topic_id}/delete").text
    assert "One sweep only" in body
    assert "Snapshots" in body and ">1<" in body

    
def test_the_confirm_page_changes_nothing(app):
    """It is a GET. A crawler, a link preview, or a prefetch must not delete."""
    c, ts, _ = app
    before = {t.topic_id for t in ts.list()}
    for tid in list(before):
        c.get(f"/topics/{tid}/delete")
    assert {t.topic_id for t in ts.list()} == before


def test_deleting_removes_the_topic_its_runs_and_its_artifacts(app):
    c, ts, rs = app
    topic = next(t for t in ts.list() if t.name == "One sweep only")
    run = rs.for_topic(topic.topic_id)[0]
    art = rs.artifacts_dir(run.run_id)
    assert art.exists()

    r = c.post(f"/topics/{topic.topic_id}/delete", follow_redirects=False)
    assert r.status_code == 303
    # Back to the list it was deleted from, not the dashboard.
    assert r.headers["location"] == "/topics"

    with pytest.raises(NoSuchTopic):
        ts.get(topic.topic_id)
    assert rs.for_topic(topic.topic_id) == []
    assert not art.exists(), "artifacts survived the topic that owned them"


def test_deleting_one_topic_leaves_the_others_alone(app):
    c, ts, rs = app
    victim = next(t for t in ts.list() if t.name == "Never run alpha")
    survivors = {t.topic_id for t in ts.list()} - {victim.topic_id}
    runs_before = {tid: len(rs.for_topic(tid)) for tid in survivors}

    c.post(f"/topics/{victim.topic_id}/delete", follow_redirects=False)

    assert {t.topic_id for t in ts.list()} == survivors
    assert {tid: len(rs.for_topic(tid)) for tid in survivors} == runs_before


def test_deleting_a_missing_topic_is_404_not_500(app):
    c, _, _ = app
    assert c.post("/topics/top-nothing/delete", follow_redirects=False).status_code == 404
    assert c.get("/topics/top-nothing/delete").status_code == 404


def test_a_double_submit_is_404_on_the_second(app):
    """The back button plus a second click. The topic is already gone, and
    saying so is better than a cheerful redirect that implies work happened."""
    c, ts, _ = app
    topic = next(t for t in ts.list() if t.name == "Never run beta")
    assert c.post(f"/topics/{topic.topic_id}/delete", follow_redirects=False).status_code == 303
    assert c.post(f"/topics/{topic.topic_id}/delete", follow_redirects=False).status_code == 404
