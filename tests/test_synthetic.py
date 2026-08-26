"""The safety rail for the offline demonstration miner.

Fabricated rows on real, well-known gold-list domains are exactly the
"plausible enough to survive review" danger this codebase has fought
throughout (see vsm/mining/fake.py's module docstring and vsm/mining/tiers.py).
So the marker has to ride on the *data* — every row the fake miner produces,
and every artifact built from a snapshot that contains one — never only on a
UI badge a downloaded file does not carry with it.

Each test below asks the question the task warned about: would this fail if
the behaviour it names were broken? In particular, every "marker present"
test has a matching "marker absent for a live-shaped run" test, because a
flag that is always on proves nothing.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest

from vsm.config import Settings
from vsm.errors import ConfigError
from vsm.mining.fake import DeterministicMiner
from vsm.mining.miner import LiveSignalMining, MiningOutcome
from vsm.mining.queries import gold_under_delivered, plan_queries
from vsm.mining.signals import Hit, any_synthetic, build_row
from vsm.mining.venues import GOLD_DOMAINS, kind_of
from vsm.modes.insight import run_insight
from vsm.modes.mine import run_mine
from vsm.modes.report import run_report
from vsm.runs.store import RunStore
from vsm.topics.model import BANDS
from vsm.topics.store import TopicStore

CLUSTER = {"cluster_id": "c1", "label": "Demo Topic", "terms": ["Demo Topic"]}


# --------------------------------------------------------------------------- #
# vsm.mining.signals.build_row — the flag itself                              #
# --------------------------------------------------------------------------- #


def _hit() -> Hit:
    return Hit(url="https://example.org/a", title="A", description="Some text.")


def test_synthetic_key_is_absent_by_default():
    """The pattern topic_id/snapshot_at already established: a caller that
    never asks for the marker gets a row byte-identical to before it existed
    — this is what keeps a live row, and every parity fixture that never
    passes this kwarg, unaffected."""
    row = build_row(
        campaign_id="t1", cluster=CLUSTER, hit=_hit(),
        captured_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
    )
    assert "synthetic" not in row


def test_synthetic_key_lands_true_when_asked_for():
    row = build_row(
        campaign_id="t1", cluster=CLUSTER, hit=_hit(),
        captured_at=datetime(2026, 8, 25, tzinfo=timezone.utc), synthetic=True,
    )
    assert row["synthetic"] is True


def test_synthetic_false_explicitly_still_omits_the_key():
    """``synthetic=False`` is the default's own value, not a different one —
    a caller that passes it explicitly must get the same absent-key shape,
    or the marker would sometimes be "off" and sometimes "False", and a
    downstream ``row.get("synthetic")`` check has to treat both the same
    anyway. Pin that they really are the same row."""
    kwargs = dict(
        campaign_id="t1", cluster=CLUSTER, hit=_hit(),
        captured_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
    )
    assert build_row(**kwargs, synthetic=False) == build_row(**kwargs)


def test_any_synthetic_is_false_for_an_all_live_shaped_list():
    rows = [build_row(campaign_id="t1", cluster=CLUSTER, hit=_hit(),
                       captured_at=datetime(2026, 8, 25, tzinfo=timezone.utc))
            for _ in range(3)]
    assert any_synthetic(rows) is False


def test_any_synthetic_is_true_when_a_single_row_is_marked():
    """One fabricated row is enough — a snapshot is not partially trustworthy."""
    live = [build_row(campaign_id="t1", cluster=CLUSTER, hit=_hit(),
                       captured_at=datetime(2026, 8, 25, tzinfo=timezone.utc))]
    fake = [build_row(campaign_id="t1", cluster=CLUSTER, hit=_hit(),
                       captured_at=datetime(2026, 8, 25, tzinfo=timezone.utc), synthetic=True)]
    assert any_synthetic(live + fake) is True


# --------------------------------------------------------------------------- #
# vsm.mining.fake.DeterministicMiner                                          #
# --------------------------------------------------------------------------- #


def test_run_signature_matches_the_live_miner_exactly():
    """Task requirement, verified rather than eyeballed: same parameter
    names, same kinds (keyword-only), in the same order."""
    live = inspect.signature(LiveSignalMining.run).parameters
    fake = inspect.signature(DeterministicMiner.run).parameters
    assert list(live) == list(fake)
    for name in live:
        assert live[name].kind == fake[name].kind, name


def test_run_returns_a_real_mining_outcome():
    outcome = DeterministicMiner().run(campaign_id="t1", clusters=[CLUSTER])
    assert type(outcome) is MiningOutcome


def test_every_row_is_marked_synthetic():
    outcome = DeterministicMiner().run(campaign_id="t1", clusters=[CLUSTER])
    assert outcome.rows
    assert all(row.get("synthetic") is True for row in outcome.rows)


def test_every_row_draws_from_the_real_gold_list():
    """The whole point of adapting the parent's fixture-hosts approach: a
    row's venue must resolve on the real registry, not a reserved
    ``.example`` host with no venue kind."""
    outcome = DeterministicMiner().run(campaign_id="t1", clusters=[CLUSTER])
    assert {row["venue"] for row in outcome.rows} <= GOLD_DOMAINS
    # And genuinely spread across kinds, not parked on one — otherwise the
    # "spread across venue kinds" claim would be true only of the registry,
    # never of what this miner actually draws.
    kinds = {kind_of(row["venue"]) for row in outcome.rows}
    assert len(kinds) >= 2


def test_every_url_is_obviously_non_resolving():
    outcome = DeterministicMiner().run(campaign_id="t1", clusters=[CLUSTER])
    for row in outcome.rows:
        assert "/synthetic-demo/not-fetched-" in row["url"]


def test_deterministic_in_campaign_id_cluster_and_query():
    """A re-run must be byte-identical — no wall clock, no randomness."""
    first = DeterministicMiner().run(campaign_id="t1", clusters=[CLUSTER])
    second = DeterministicMiner().run(campaign_id="t1", clusters=[CLUSTER])
    assert first.rows == second.rows
    assert first.plan == second.plan


def test_a_different_campaign_id_produces_different_rows():
    """The determinism claim is about reruns of the *same* input, not that
    the miner ignores its input — pin that campaign_id actually matters, or
    the determinism test above would also pass against a hardcoded fixture."""
    a = DeterministicMiner().run(campaign_id="topic-a", clusters=[CLUSTER])
    b = DeterministicMiner().run(campaign_id="topic-b", clusters=[CLUSTER])
    assert a.rows != b.rows


def test_walks_the_same_plan_plan_queries_would_build():
    """The core rehearsal claim: the offline miner's plan is not an
    approximation of vsm.mining.queries.plan_queries — it is the *same*
    call, walked in the same order."""
    expected = plan_queries(CLUSTER, 4)
    outcome = DeterministicMiner(queries_per_cluster=4).run(campaign_id="t1", clusters=[CLUSTER])
    # Every gold query in the expected plan appears, in order, in what was
    # actually run. (The open tail is conditional — see the next test — so
    # it is not asserted unconditionally here.)
    expected_gold = [q.text for q in expected if q.kind == "gold"]
    assert outcome.queries_run[: len(expected_gold)] == expected_gold


def test_the_open_tail_is_not_run_when_the_gold_list_delivers_enough():
    """gold_under_delivered's own threshold — asserted against the miner's
    real output, not assumed. The default 4-query, 3-rows-per-query shape
    reliably clears MIN_GOLD_ROWS from the very first gold query, so the
    tail must be absent from what actually ran."""
    outcome = DeterministicMiner(queries_per_cluster=4).run(campaign_id="t1", clusters=[CLUSTER])
    plan = plan_queries(CLUSTER, 4)
    open_queries = {q.text for q in plan if q.kind == "open"}
    assert open_queries, "the plan must actually contain an open tail for this test to mean anything"
    assert not (open_queries & set(outcome.queries_run))


def test_cost_is_zero_no_real_spend_took_place():
    outcome = DeterministicMiner().run(campaign_id="t1", clusters=[CLUSTER])
    assert outcome.cost_usd == 0.0


def test_no_clusters_produces_no_rows_and_does_not_raise():
    outcome = DeterministicMiner().run(campaign_id="t1", clusters=[])
    assert outcome.rows == []


def test_produces_a_measurable_dual_lens_divergence():
    """The end-to-end acceptance bar: run the fake miner's rows through the
    real INSIGHT passes (offline, client=None — exactly what VSM_OFFLINE=1
    wires up) and confirm at least one theme's dual-lens gap is a real
    number, not every theme reading NE. This is what "not all NE" means in
    practice — a divergence of 0.0 with client=None (no stance classifier
    ran) is still a measured comparison, not a missing one; NE means no
    hcp-class or patient-class signal existed for that theme at all."""
    from vsm.analysis.authorclass import VenueResolver
    from vsm.analysis.cluster import cluster_themes
    from vsm.analysis.duallens import dual_lens
    from vsm.analysis.stance import stance_for_themes

    outcome = DeterministicMiner(queries_per_cluster=4).run(campaign_id="t1", clusters=[CLUSTER])
    themes = cluster_themes(outcome.rows, client=None)
    stances = stance_for_themes(themes, outcome.rows, VenueResolver(), client=None)
    gaps = dual_lens(themes, stances)
    assert any(g.divergence is not None for g in gaps)


# --------------------------------------------------------------------------- #
# vsm.mining.get_miner                                                        #
# --------------------------------------------------------------------------- #


def test_get_miner_returns_the_fake_when_offline():
    from vsm.mining import get_miner

    settings = Settings(offline=True)
    miner = get_miner(settings, band=BANDS["standard"])
    assert isinstance(miner, DeterministicMiner)


def test_get_miner_fake_is_sized_by_the_spend_band():
    """A demonstration at the deep band must rehearse a deep-band sweep, not
    a probe-band one wearing a deep label."""
    from vsm.mining import get_miner

    settings = Settings(offline=True)
    deep = get_miner(settings, band=BANDS["deep"])
    probe = get_miner(settings, band=BANDS["probe"])
    assert deep.queries_per_cluster == BANDS["deep"].queries_per_cluster
    assert probe.queries_per_cluster == BANDS["probe"].queries_per_cluster
    assert deep.queries_per_cluster != probe.queries_per_cluster


def test_get_miner_live_without_a_key_raises_never_falls_back():
    from vsm.mining import get_miner

    settings = Settings(offline=False, miner_mode="live", brightdata_api_key=None)
    with pytest.raises(ConfigError):
        get_miner(settings, band=BANDS["probe"])


def test_get_miner_live_with_a_key_returns_a_configured_live_miner():
    from vsm.mining import get_miner
    from vsm.modes.mine import config_for

    settings = Settings(offline=False, miner_mode="live", brightdata_api_key="bd-fake")
    miner = get_miner(settings, band=BANDS["deep"])
    assert isinstance(miner, LiveSignalMining)
    assert miner.config == config_for(BANDS["deep"])
    assert miner.catalogue  # the gold-list catalogue, not an empty one


# --------------------------------------------------------------------------- #
# propagation into MINE / INSIGHT / REPORT artifacts                          #
# --------------------------------------------------------------------------- #


@pytest.fixture
def stores(tmp_path):
    return TopicStore(tmp_path / "db"), RunStore(tmp_path / "db", tmp_path / "var")


class _LiveShapedMiner:
    """Stands in for a real collected sweep: distinct real gold-list domains,
    no synthetic marker anywhere — the "must not be permanently on" half of
    every test below."""

    def run(self, *, campaign_id, clusters, queries_per_cluster=None):
        cluster = clusters[0]
        rows = []
        for i, (venue, theme) in enumerate(
            [("reddit.com", "real theme a"), ("inspire.com", "real theme a"),
             ("pubmed.ncbi.nlm.nih.gov", "real theme b")]
        ):
            hit = Hit(
                url=f"https://{venue}/real-post-{i}", title=theme,
                description="A real excerpt of real content, not fabricated.",
            )
            rows.append(
                build_row(
                    campaign_id=campaign_id, cluster=cluster, hit=hit,
                    captured_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
                )
            )
        return MiningOutcome(
            rows=rows, provider="stub-live", cost_usd=0.01,
            venues_collected=sorted({r["venue"] for r in rows}),
        )


def test_mine_marks_coverage_and_cost_synthetic_when_the_sweep_is_fake(stores):
    ts, rs = stores
    topic = ts.create(name="Demo Topic", therapeutic_area="", spend_band="standard")
    run = run_mine(topic, rs, miner=DeterministicMiner(queries_per_cluster=4), cluster_count=1)
    assert rs.read_artifact(run.run_id, "coverage.json")["synthetic"] is True
    assert rs.read_artifact(run.run_id, "cost.json")["synthetic"] is True


def test_mine_marks_coverage_and_cost_not_synthetic_for_a_live_shaped_sweep(stores):
    """The marker must not be permanently on: a real-shaped sweep must not
    carry it."""
    ts, rs = stores
    topic = ts.create(name="Demo Topic", therapeutic_area="", spend_band="standard")
    run = run_mine(topic, rs, miner=_LiveShapedMiner(), cluster_count=1)
    assert rs.read_artifact(run.run_id, "coverage.json")["synthetic"] is False
    assert rs.read_artifact(run.run_id, "cost.json")["synthetic"] is False


def test_insight_artifacts_are_all_marked_when_the_snapshot_is_synthetic(stores):
    ts, rs = stores
    topic = ts.create(name="Demo Topic", therapeutic_area="", spend_band="standard")
    mine = run_mine(topic, rs, miner=DeterministicMiner(queries_per_cluster=4), cluster_count=1)
    insight = run_insight(topic, mine.run_id, rs, client=None)

    entities = rs.read_artifact(insight.run_id, "entities.json")
    assert entities["synthetic"] is True
    # anomaly.json is legitimately empty on a first snapshot (no baseline to
    # compare against — see vsm/analysis/anomaly.py) so it is checked
    # separately, without requiring non-emptiness; every other artifact here
    # is guaranteed non-empty by the fixture's rows and is checked for real.
    for name in ("themes.json", "stance.json", "duallens.json", "momentum.json",
                 "findings.json"):
        items = rs.read_artifact(insight.run_id, name)
        assert items, name
        assert all(item.get("synthetic") is True for item in items), name
    assert all(
        item.get("synthetic") is True
        for item in rs.read_artifact(insight.run_id, "anomaly.json")
    )


def test_insight_artifacts_carry_no_marker_for_a_live_shaped_snapshot(stores):
    ts, rs = stores
    topic = ts.create(name="Demo Topic", therapeutic_area="", spend_band="standard")
    mine = run_mine(topic, rs, miner=_LiveShapedMiner(), cluster_count=1)
    insight = run_insight(topic, mine.run_id, rs, client=None)

    entities = rs.read_artifact(insight.run_id, "entities.json")
    assert "synthetic" not in entities
    for name in ("themes.json", "stance.json", "duallens.json", "momentum.json",
                 "findings.json"):
        items = rs.read_artifact(insight.run_id, name)
        assert items, name
        assert not any("synthetic" in item for item in items), name
    assert not any(
        "synthetic" in item for item in rs.read_artifact(insight.run_id, "anomaly.json")
    )


def test_pulse_report_and_methodology_state_the_synthetic_run_plainly(stores):
    """The failure this prevents: a demonstration pulse_report.md downloaded
    and handed to a client with no way to tell it apart from a real one."""
    ts, rs = stores
    topic = ts.create(name="Demo Topic", therapeutic_area="", spend_band="standard")
    mine = run_mine(topic, rs, miner=DeterministicMiner(queries_per_cluster=4), cluster_count=1)
    insight = run_insight(topic, mine.run_id, rs, client=None)
    report = run_report(topic, insight.run_id, rs, client=None)

    pulse = rs.read_artifact(report.run_id, "pulse_report.md").lower()
    methodology = rs.read_artifact(report.run_id, "methodology.md").lower()
    assert "fabricated" in pulse and "not collected from the web" in pulse
    assert "fabricated" in methodology and "not collected from the web" in methodology


def test_a_live_shaped_report_carries_no_synthetic_marker(stores):
    """The other half: the marker must not be permanently on. A report built
    from real-shaped rows must say nothing about fabrication anywhere."""
    ts, rs = stores
    topic = ts.create(name="Demo Topic", therapeutic_area="", spend_band="standard")
    mine = run_mine(topic, rs, miner=_LiveShapedMiner(), cluster_count=1)
    insight = run_insight(topic, mine.run_id, rs, client=None)
    report = run_report(topic, insight.run_id, rs, client=None)

    for name in ("pulse_report.md", "methodology.md", "provenance_appendix.md",
                 "worth_considering.md"):
        text = rs.read_artifact(report.run_id, name).lower()
        assert "fabricated" not in text
        assert "synthetic" not in text
