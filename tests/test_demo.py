"""vsm.demo.seed_demo_topic — the cold-start fix for "the app does not work".

With no database configured, a topic created on the live deployment lives
only in the container that created it (see vsm/storage.py and vsm/demo.py's
own module docstring). ``seed_demo_topic`` makes sure a cold, empty,
ephemeral container is never actually empty: on startup it seeds one
fully-worked topic — two dated snapshots, an INSIGHT run and a REPORT run —
so every screen is explorable immediately, no matter which container answers
the request.

Each test here asks the question the task warned about: would this fail if
the behaviour it names were broken?
"""

from __future__ import annotations

from vsm.analysis.momentum import NO_BASELINE
from vsm.demo import seed_demo_topic
from vsm.mining.signals import any_synthetic
from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore


def _stores(tmp_path):
    return TopicStore(tmp_path / "db"), RunStore(tmp_path / "db", tmp_path / "var")


def test_seeds_one_topic_with_two_snapshots_an_insight_run_and_a_report_run(tmp_path):
    ts, rs = _stores(tmp_path)
    # env={} forces "no database URL resolves", regardless of whatever the
    # machine actually running this test happens to have exported — the
    # test must not depend on the developer's shell.
    seed_demo_topic(ts, rs, env={})

    topics = ts.list()
    assert len(topics) == 1
    topic = topics[0]

    snapshots = rs.snapshots(topic.topic_id)
    assert len(snapshots) == 2
    assert all(r.status == "complete" for r in snapshots)

    insight_runs = rs.for_topic(topic.topic_id, "insight")
    assert len(insight_runs) == 1
    assert insight_runs[0].status == "complete"
    assert insight_runs[0].parent_run_id == snapshots[-1].run_id

    report_runs = rs.for_topic(topic.topic_id, "report")
    assert len(report_runs) == 1
    assert report_runs[0].status == "complete"
    assert report_runs[0].parent_run_id == insight_runs[0].run_id


def test_every_seeded_row_is_flagged_synthetic(tmp_path):
    """The safety rail must carry through: nothing seeded here may ever be
    mistaken for a real collected sweep."""
    ts, rs = _stores(tmp_path)
    seed_demo_topic(ts, rs, env={})
    topic = ts.list()[0]
    snapshots = rs.snapshots(topic.topic_id)

    for snap in snapshots:
        rows = rs.read_artifact(snap.run_id, "signals.json")
        assert rows, "a seeded snapshot must not be empty"
        assert any_synthetic(rows)
        assert rs.read_artifact(snap.run_id, "coverage.json")["synthetic"] is True

    insight_run = rs.for_topic(topic.topic_id, "insight")[0]
    report_run = rs.for_topic(topic.topic_id, "report")[0]
    pulse = rs.read_artifact(report_run.run_id, "pulse_report.md").lower()
    assert "fabricated" in pulse and "not collected from the web" in pulse
    assert rs.read_artifact(insight_run.run_id, "themes.json")


def test_the_second_snapshot_has_a_real_momentum_baseline(tmp_path):
    """Two snapshots exist specifically so momentum is not "no prior
    snapshot" everywhere — this is what would fail if seeding only ever
    produced one."""
    ts, rs = _stores(tmp_path)
    seed_demo_topic(ts, rs, env={})
    topic = ts.list()[0]
    insight_run = rs.for_topic(topic.topic_id, "insight")[0]

    momentum_rows = rs.read_artifact(insight_run.run_id, "momentum.json")
    assert momentum_rows
    assert any(m["reason"] != NO_BASELINE for m in momentum_rows)


def test_the_insight_run_has_a_measured_dual_lens_divergence(tmp_path):
    """The forest plot must show a real, non-"NE" divergence on the seeded
    topic — an all-NE result would mean nobody could actually see the plot
    do anything from a fresh container."""
    ts, rs = _stores(tmp_path)
    seed_demo_topic(ts, rs, env={})
    topic = ts.list()[0]
    insight_run = rs.for_topic(topic.topic_id, "insight")[0]

    gaps = rs.read_artifact(insight_run.run_id, "duallens.json")
    assert gaps
    assert any(g["divergence"] is not None for g in gaps)


def test_is_a_noop_when_a_topic_already_exists(tmp_path):
    """Never overwrite, never duplicate: a store that already holds
    something — seeded earlier, or created by a real visitor — must be left
    exactly alone."""
    ts, rs = _stores(tmp_path)
    existing = ts.create(name="Real topic", therapeutic_area="gi", spend_band="probe")

    seed_demo_topic(ts, rs, env={})

    topics = ts.list()
    assert [t.topic_id for t in topics] == [existing.topic_id]
    assert rs.for_topic(existing.topic_id) == []  # no runs were added to it either


def test_calling_it_twice_on_an_empty_store_seeds_only_once(tmp_path):
    ts, rs = _stores(tmp_path)
    seed_demo_topic(ts, rs, env={})
    seed_demo_topic(ts, rs, env={})
    assert len(ts.list()) == 1


def test_is_a_noop_when_a_database_url_is_configured(tmp_path):
    """A real database means topics persist for real — seeding a synthetic
    demonstration topic into it would leave fabricated rows sitting there
    forever next to genuine ones. Checked against an otherwise-empty store,
    so the only thing that could explain a topic appearing is this guard
    failing to fire."""
    ts, rs = _stores(tmp_path)
    seed_demo_topic(ts, rs, env={"DATABASE_URL": "postgresql://example/db"})
    assert ts.list() == []


def test_is_a_noop_for_each_recognised_database_env_var(tmp_path):
    for var in ("POSTGRES_URL_NON_POOLING", "POSTGRES_URL", "DATABASE_URL"):
        ts, rs = _stores(tmp_path)
        seed_demo_topic(ts, rs, env={var: "postgresql://example/db"})
        assert ts.list() == [], f"seeded despite {var} being set"


def test_the_seeded_topics_own_spend_band_is_probe(tmp_path):
    """Only the probe band is allowed to run on Vercel
    (vsm.platform.assert_band_allowed) — a seeded topic in a wider band
    would refuse to run its own next sweep in production, which is a
    strange first thing for a visitor to hit."""
    ts, rs = _stores(tmp_path)
    seed_demo_topic(ts, rs, env={})
    assert ts.list()[0].spend_band == "probe"
