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
    seed_demo_topic(ts, real, env={})
    # A handful of extra topics, so a per-topic cost shows up as a multiple.
    for i in range(5):
        ts.create(topic_id=f"top-extra{i}", name=f"Extra {i}",
                  therapeutic_area="", spend_band="probe")
    rs = CountingRunStore(real)
    return TestClient(create_app(topic_store=ts, run_store=rs)), ts, rs


def test_the_index_asks_each_topic_for_its_runs_exactly_once(counted):
    client, ts, rs = counted
    n_topics = len(ts.list())
    assert n_topics >= 6, "fixture needs several topics for this to mean anything"

    assert client.get("/").status_code == 200

    total = rs.calls.get("for_topic", 0) + rs.calls.get("snapshots", 0)
    assert total == n_topics, (
        f"{total} run-listing calls for {n_topics} topics — "
        f"{rs.calls}. Each one is O(all runs in the store) on a flat "
        f"key-value backend."
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
    client.get("/")
    snapshots = sum(len(rs._real.snapshots(t.topic_id)) for t in ts.list())
    assert rs.calls.get("read_artifact", 0) <= snapshots, (
        f"{rs.calls.get('read_artifact', 0)} artifact reads for {snapshots} snapshots"
    )
