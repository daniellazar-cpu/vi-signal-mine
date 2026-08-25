import pytest

from vsm.modes.mine import run_mine
from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore


class _FakeMiner:
    """Stands in for LiveSignalMining. Returns two rows on distinct domains."""

    def __init__(self, rows=None, cost=0.0315):
        self.rows = rows if rows is not None else [
            {"signal_id": "sig-a", "venue": "agajournals.org",
             "url": "https://agajournals.org/a", "theme": "tolerability",
             "collection_tier": "B", "collection_method": "serp_result",
             "captured_at": "2026-08-25T00:00:00+00:00", "sentiment": None},
            {"signal_id": "sig-b", "venue": "reddit.com",
             "url": "https://reddit.com/r/x/b", "theme": "cost",
             "collection_tier": "B", "collection_method": "serp_result",
             "captured_at": "2026-08-25T00:00:00+00:00", "sentiment": None},
        ]
        self.cost = cost

    def run(self, *, campaign_id, clusters, queries_per_cluster=None):
        # Matches LiveSignalMining.run exactly: keyword-only, campaign_id
        # required, and the config lives on the constructor, not here.
        class _Outcome:
            rows = self.rows
            cost_usd = self.cost
            queries_run = ["q1", "q2"]
            venues_attempted = ["agajournals.org", "reddit.com"]
            venues_collected = ["agajournals.org", "reddit.com"]
            venues_restricted = []
            denied = []
            deferrals = []
            notes = []
            calls = []
            plan = [{"query": "q1", "kind": "gold"}]
            provenance = {"provider": "fake"}

        return _Outcome()


@pytest.fixture
def stores(tmp_path):
    return TopicStore(tmp_path / "db"), RunStore(tmp_path / "db", tmp_path / "var")


def _topic(ts, band="standard"):
    return ts.create(name="OIC", therapeutic_area="gastroenterology", spend_band=band,
                     molecule="naldemedine")


def test_mine_writes_its_five_artifacts(stores):
    ts, rs = stores
    topic = _topic(ts)
    run = run_mine(topic, rs, miner=_FakeMiner(), cluster_count=1)
    for name in ("signals.json", "provenance.json", "coverage.json", "cost.json", "plan.json"):
        assert (rs.artifacts_dir(run.run_id) / name).exists(), name


def test_mine_stamps_every_row_with_the_topic_and_snapshot(stores):
    """Without these a row cannot be placed in a series, and momentum has
    nothing to compare against."""
    ts, rs = stores
    topic = _topic(ts)
    run = run_mine(topic, rs, miner=_FakeMiner(), cluster_count=1)
    rows = rs.read_artifact(run.run_id, "signals.json")
    assert rows and all(r["topic_id"] == topic.topic_id for r in rows)
    assert all(r["snapshot_at"] == run.started_at for r in rows)


def test_mine_completes_and_records_its_cost(stores):
    ts, rs = stores
    run = run_mine(_topic(ts), rs, miner=_FakeMiner(cost=0.0315), cluster_count=1)
    assert run.status == "complete"
    assert run.cost_usd == pytest.approx(0.0315)


def test_a_cap_breach_stops_cleanly_with_partial_rows(stores):
    """Not an exception at the pipeline: partial rows, a recorded deferral, and
    a status that says we stopped paying rather than that it broke."""
    ts, rs = stores
    topic = ts.create(name="OIC", therapeutic_area="gi", spend_band="deep")
    run = run_mine(topic, rs, miner=_FakeMiner(cost=99.0), cluster_count=1, cap_usd=0.05)
    assert run.status == "stopped_on_budget"
    assert rs.read_artifact(run.run_id, "signals.json") == []
    cost = rs.read_artifact(run.run_id, "cost.json")
    assert cost["stopped"] is True
    assert "cap" in cost["reason"].lower()


def test_coverage_records_venues_that_answered_and_that_did_not(stores):
    """A silent filter is indistinguishable from finding nothing."""
    ts, rs = stores
    run = run_mine(_topic(ts), rs, miner=_FakeMiner(), cluster_count=1)
    coverage = rs.read_artifact(run.run_id, "coverage.json")
    assert set(coverage["venues_attempted"]) >= set(coverage["venues_collected"])
    assert "venues_empty" in coverage
