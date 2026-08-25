from types import SimpleNamespace

import pytest

from vsm.errors import GuardViolation
from vsm.guards.cost import estimate_run_usd
from vsm.modes.mine import run_mine
from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore


class _FakeMiner:
    """Stands in for LiveSignalMining. Returns two rows on distinct domains,
    and one venue that was queried but nothing came back from."""

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
        # `campaign_id` is stamped onto every row here from this same
        # parameter — exactly what the vendored `build_row` does — rather
        # than hardcoded, so a test can pin that `run_mine` preserves it.
        stamped_rows = [{**row, "campaign_id": campaign_id} for row in self.rows]

        class _Outcome:
            rows = stamped_rows
            cost_usd = self.cost
            provider = "fake"
            provenance = {"provider": "fake", "detail": "stands in for LiveSignalMining"}
            queries_run = ["q1", "q2"]
            # "pubmed.ncbi.nlm.nih.gov" was queried and nothing came back —
            # a venue that answered with nothing, distinct from one that was
            # never queried at all (venues_restricted, below).
            venues_attempted = ["agajournals.org", "reddit.com", "pubmed.ncbi.nlm.nih.gov"]
            venues_collected = ["agajournals.org", "reddit.com"]
            venues_restricted = []
            denied = []
            deferrals = []
            notes = []
            calls = []
            coverage = []
            plan = [{"query": "q1", "kind": "gold"}]

        return _Outcome()


class _FakeClusterClient:
    """Stands in for AnthropicClient: answers the lexicon call and, like the
    real client, only reflects the call's cost in `.spend.usd` *after* the
    call completes — `spend.usd` starts at zero and accumulates on each
    `complete_structured`, exactly like the real cumulative `LlmSpend`
    ledger. A fake that pre-loaded the total instead would not exercise
    `run_mine`'s before/after delta read at all: the "before" and "after"
    snapshots would be identical and the charge would silently be zero."""

    def __init__(self, *, spend_usd, clusters=None):
        self.spend = SimpleNamespace(usd=0.0)
        self._spend_usd = spend_usd
        self._clusters = clusters if clusters is not None else [
            {"cluster_id": "c1", "label": "OIC", "terms": ["naldemedine"],
             "areas": ["gastroenterology"], "queries": ["naldemedine reviews"]},
        ]

    def complete_structured(self, *, system, user, schema, max_output_tokens, on_progress=None):
        self.spend = SimpleNamespace(usd=round(self.spend.usd + self._spend_usd, 6))
        return SimpleNamespace(ok=True, data={"clusters": self._clusters}, reason="")


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
    # `campaign_id` is the vendored miner's own name for the same value
    # `run_mine` calls `topic_id` — production keeps them equal only because
    # `run_mine` copies the row dict wholesale, so pin that they still agree
    # after enrichment.
    assert all(r["campaign_id"] == r["topic_id"] == topic.topic_id for r in rows)


def test_mine_completes_and_records_its_cost(stores):
    ts, rs = stores
    run = run_mine(_topic(ts), rs, miner=_FakeMiner(cost=0.0315), cluster_count=1)
    assert run.status == "complete"
    assert run.cost_usd == pytest.approx(0.0315)


def test_a_pre_sweep_cap_breach_stops_cleanly_with_no_rows(stores):
    """Not an exception at the pipeline: a status that says we stopped paying
    rather than that it broke, and no rows — nothing was collected because
    the estimate alone already breached the cap, so the sweep was never
    attempted. Contrast with
    `test_a_sweep_that_costs_more_than_estimated_stops_but_keeps_what_it_collected`,
    where the sweep *did* run and its rows must survive."""
    ts, rs = stores
    topic = ts.create(name="OIC", therapeutic_area="gi", spend_band="deep")
    run = run_mine(topic, rs, miner=_FakeMiner(cost=99.0), cluster_count=1, cap_usd=0.05)
    assert run.status == "stopped_on_budget"
    assert rs.read_artifact(run.run_id, "signals.json") == []
    cost = rs.read_artifact(run.run_id, "cost.json")
    assert cost["stopped"] is True
    assert "cap" in cost["reason"].lower()


def test_coverage_records_venues_that_answered_and_that_did_not(stores):
    """A silent filter is indistinguishable from finding nothing — and a set
    difference this test doesn't force to actually differ would pass even
    if `venues_empty` were hardcoded to `[]`."""
    ts, rs = stores
    run = run_mine(_topic(ts), rs, miner=_FakeMiner(), cluster_count=1)
    coverage = rs.read_artifact(run.run_id, "coverage.json")
    assert set(coverage["venues_attempted"]) >= set(coverage["venues_collected"])
    assert coverage["venues_empty"] == ["pubmed.ncbi.nlm.nih.gov"]


def test_a_lexicon_call_that_alone_breaches_the_cap_stops_before_any_sweep(stores):
    """The estimate needs a cluster count, and the cluster count comes from
    the lexicon call — so that call cannot be gated in advance, only
    accounted for the moment it returns. A lexicon call that alone exhausts
    the budget must stop the run cleanly rather than proceed to a sweep it
    cannot afford, and the real money it already spent must still show up in
    the record rather than reading as a free run."""
    ts, rs = stores
    topic = _topic(ts)
    run = run_mine(
        topic, rs,
        client=_FakeClusterClient(spend_usd=10.0),
        miner=_FakeMiner(),
        cluster_count=1,
        cap_usd=1.0,
    )
    assert run.status == "stopped_on_budget"
    assert rs.read_artifact(run.run_id, "signals.json") == []
    cost = rs.read_artifact(run.run_id, "cost.json")
    assert cost["stopped"] is True
    assert "lexicon" in cost["reason"].lower()
    # Real spend, already incurred — reported, not swallowed into a zero
    # just because the cap declined to accept it after the fact.
    assert cost["model_usd"] == pytest.approx(10.0)
    assert run.cost_usd == pytest.approx(10.0)


def test_a_sweep_that_costs_more_than_estimated_stops_but_keeps_what_it_collected(stores):
    """The second, more interesting breach: the estimate clears the cap
    comfortably, the sweep runs, and only afterwards does its real cost turn
    out to exceed what was budgeted. Unlike a pre-sweep breach, rows were
    actually collected here and must not be discarded — checked below, not
    just asserted in prose. This is the one test in the file where the
    pipeline's *second* ``BudgetExceeded`` catch site — the one that fires on
    the actual cost, not the estimate — is the one that fires."""
    ts, rs = stores
    topic = _topic(ts)
    estimate = estimate_run_usd(topic.band(), cluster_count=1).total_usd
    run = run_mine(
        topic, rs,
        miner=_FakeMiner(cost=99.0),
        cluster_count=1,
        cap_usd=estimate + 0.03,  # clears the estimate; the actual cost will not
    )
    assert run.status == "stopped_on_budget"
    rows = rs.read_artifact(run.run_id, "signals.json")
    assert rows, "the sweep ran and collected rows — they must survive the stop"
    assert {r["signal_id"] for r in rows} == {"sig-a", "sig-b"}
    assert all(r["topic_id"] == topic.topic_id for r in rows)
    cost = rs.read_artifact(run.run_id, "cost.json")
    assert cost["stopped"] is True
    assert "cap" in cost["reason"].lower()
    assert cost["estimate_usd"] == pytest.approx(estimate)
    # The real bill, not the estimate and not zero — the sweep already spent it.
    assert cost["actual_usd"] == pytest.approx(99.0)
    assert run.cost_usd == pytest.approx(99.0)


# --- Spec D14: only `probe` is allowed to run on Vercel --------------------


def test_a_disallowed_band_on_vercel_refuses_before_starting_a_run(stores, monkeypatch):
    """The guard runs before `store.start()`, not after: a disallowed band
    on Vercel must leave no run row and spend nothing, not start a run that
    then fails partway. Checked here by asserting the topic's run list is
    still empty after the raise, not just that a GuardViolation was raised —
    a guard placed after `store.start()` would also satisfy the raise alone."""
    ts, rs = stores
    monkeypatch.setenv("VERCEL", "1")
    topic = _topic(ts, band="standard")
    with pytest.raises(GuardViolation, match="probe"):
        run_mine(topic, rs, miner=_FakeMiner(), cluster_count=1)
    assert rs.for_topic(topic.topic_id) == []


def test_the_probe_band_still_runs_on_vercel(stores, monkeypatch):
    ts, rs = stores
    monkeypatch.setenv("VERCEL", "1")
    topic = _topic(ts, band="probe")
    run = run_mine(topic, rs, miner=_FakeMiner(), cluster_count=1)
    assert run.status == "complete"
