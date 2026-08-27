"""How many times the index asks the store for the same thing.

On a store with a secondary index this is a performance note. On a flat
key-value store it is a correctness-of-service question: `for_topic` there has
to list every run blob and read each one's *content* to discover which topic it
belongs to, so one call is O(all runs in the store) round trips.

`_topic_row` called `snapshots()` **and** `for_topic()`, and `snapshots()` is
itself a filter over `for_topic()` — so each row paid that cost twice, once per
topic on the index. Measured on production: **13,144** content GETs for one page
render, and the home page hit the 60-second function ceiling and returned 504.

These tests count calls rather than time anything, so they fail for the reason
they are named and hold on any backend.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from vsm.demo import seed_demo_topic
from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore
from vsm.ui.app import create_app


class CountingRunStore:
    """Delegates everything, counting the calls that fan out."""

    def __init__(self, real: RunStore) -> None:
        self._real = real
        self.calls: dict[str, int] = {}

    def __getattr__(self, item):
        return getattr(self._real, item)

    def _count(self, name):
        self.calls[name] = self.calls.get(name, 0) + 1

    def for_topic(self, topic_id: str, mode: str | None = None):
        self._count("for_topic")
        return self._real.for_topic(topic_id, mode)

    def for_topics(self, topic_ids):
        self._count("for_topics")
        return self._real.for_topics(topic_ids)

    def snapshots(self, topic_id: str):
        self._count("snapshots")
        return self._real.snapshots(topic_id)

    def read_artifact(self, run_id: str, name: str):
        self._count("read_artifact")
        return self._real.read_artifact(run_id, name)


@pytest.fixture
def counted(tmp_path, monkeypatch):
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    ts = TopicStore(tmp_path / "db")
    real = RunStore(tmp_path / "db", tmp_path / "var")
    # The demo seed has to run first — it is a no-op on a store that already
    # holds a topic.
    seed_demo_topic(ts, real, env={})
    for i in range(5):
        ts.create(topic_id=f"top-extra{i}", name=f"Extra {i}",
                  therapeutic_area="", spend_band="probe")
    # Then the newest topic gets a completed report of its own. `list()` is
    # newest-first, so this one is examined *first* — which is what makes
    # "stops at the first match" distinguishable from "scans everything and
    # keeps the last". With the only report on the oldest topic the two
    # behaviours are indistinguishable, and a test that cannot tell them apart
    # is decoration, not coverage.
    ts.create(topic_id="top-newest", name="Newest with a report",
              therapeutic_area="", spend_band="probe")
    rep = real.start("top-newest", "report")
    real.finish(rep.run_id, "complete", 0.0)
    rs = CountingRunStore(real)
    return TestClient(create_app(topic_store=ts, run_store=rs)), ts, rs


def test_the_index_asks_for_every_topic_s_runs_in_one_call(counted):
    """The property that decides whether this page scales.

    Per-topic, a render costs one round trip per topic: on Postgres a query
    each, on a flat key-value store a fan-out each. Measured on the deployment
    with Postgres, asking per topic grew the index linearly — 0.96s at 10
    topics, 1.84s at 40, about 30ms per topic, so a few hundred topics would
    have put it back into seconds. One call is a constant number of round trips
    however long the list gets.
    """
    client, ts, rs = counted
    n_topics = len(ts.list())
    assert n_topics >= 6, "fixture needs several topics for this to mean anything"

    assert client.get("/topics").status_code == 200

    per_topic = rs.calls.get("for_topic", 0) + rs.calls.get("snapshots", 0)
    assert rs.calls.get("for_topics", 0) == 1, f"expected one batched call: {rs.calls}"
    assert per_topic == 0, (
        f"{per_topic} per-topic run lookups for {n_topics} topics — {rs.calls}"
    )


def test_the_derived_snapshot_filter_matches_the_backend_s_own(counted):
    """The index now filters `for_topic` itself instead of calling
    `snapshots()`. If those two ever disagree, the index silently reports a
    different snapshot count and a different sparkline from every other screen.
    """
    _, ts, rs = counted
    for topic in ts.list():
        all_runs = rs._real.for_topic(topic.topic_id)
        derived = [r for r in all_runs if r.mode == "mine" and r.status == "complete"]
        assert derived == rs._real.snapshots(topic.topic_id), topic.topic_id


def test_the_index_reads_one_signals_artifact_per_snapshot_not_more(counted):
    """The other per-row cost. Volumes come from `signals.json`, one read per
    snapshot — if this starts scaling with topics, the sparkline is re-reading
    other topics' data."""
    client, ts, rs = counted
    client.get("/topics")
    snapshots = sum(len(rs._real.snapshots(t.topic_id)) for t in ts.list())
    assert rs.calls.get("read_artifact", 0) <= snapshots, (
        f"{rs.calls.get('read_artifact', 0)} artifact reads for {snapshots} snapshots"
    )


def test_the_deliverables_page_stops_at_the_first_topic_with_a_report(counted):
    """It shows a link to one example report. It used to scan *every* topic and
    keep the last match, paying a full run-store fan-out per topic and throwing
    all but one away — 10.3 seconds on production for a page that displays no
    run data at all.

    Asserted as "stops at the first match" rather than "scans fewer than all",
    because in this fixture the only topic with a report happens to be the
    oldest, so scanning every topic *is* correct here. The bug was continuing
    past a match, and that is what this pins.
    """
    client, ts, rs = counted
    order = ts.list()                      # the order the page iterates
    first_with_report = next(
        (i for i, t in enumerate(order)
         if any(r.mode == "report" and r.status == "complete"
                for r in rs._real.for_topic(t.topic_id))),
        None,
    )
    assert first_with_report is not None, "fixture has no completed report"

    rs.calls.clear()
    assert client.get("/deliverables").status_code == 200
    assert rs.calls.get("for_topic", 0) == first_with_report + 1, (
        f"scanned {rs.calls.get('for_topic', 0)} topics; the first with a "
        f"report is at index {first_with_report}, so it should have stopped there"
    )


def test_the_index_settles_snapshots_once_and_reuses_them(counted):
    """The index needs each topic's runs twice — once to know which snapshots
    to prefetch, once to build the row. It must fetch them once."""
    client, ts, rs = counted
    client.get("/topics")
    assert rs.calls.get("for_topics", 0) == 1, rs.calls
    assert rs.calls.get("for_topic", 0) == 0, rs.calls


def test_for_topics_agrees_with_for_topic_on_the_real_store(counted):
    """Backend-independent version of the same guard: the index builds its rows
    from the batched call and every other screen from the single one. If they
    ever disagree, the index quietly contradicts the pages it links to."""
    _, ts, rs = counted
    ids = [t.topic_id for t in ts.list()]
    batched = rs._real.for_topics(ids)
    assert set(batched) == set(ids)
    for tid in ids:
        assert batched[tid] == rs._real.for_topic(tid), tid
