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


def test_seeding_is_deterministic_across_two_independent_cold_starts(tmp_path):
    """The actual fix for "sometimes it works, sometimes it's a dead end":
    on a platform with no shared database, every serverless container that
    starts cold seeds its own copy of this worked example into storage no
    other container can see. If seeding drew ids from ``uuid4()`` or
    timestamps from the real clock (as it used to), a link minted by
    container A would name an id container B never produced — "No run with
    id ..." on whichever container happens to answer the next click.

    Proven here by seeding into two *entirely separate* store directories
    (nothing shared, no coordination possible — the same relationship two
    real serverless containers have to each other) and asserting the topic
    id, every run id, every timestamp and every artifact's exact bytes come
    out identical. Before the fix this failed on every single run — two
    calls to ``seed_demo_topic`` never produced the same topic id twice, let
    alone the same run ids or artifact bytes.
    """
    ts_a, rs_a = _stores(tmp_path / "container-a")
    ts_b, rs_b = _stores(tmp_path / "container-b")
    seed_demo_topic(ts_a, rs_a, env={})
    seed_demo_topic(ts_b, rs_b, env={})

    topic_a, topic_b = ts_a.list()[0], ts_b.list()[0]
    assert topic_a.topic_id == topic_b.topic_id
    assert topic_a.created_at == topic_b.created_at

    def run_ids(rs, topic_id):
        return {
            mode: [r.run_id for r in rs.for_topic(topic_id, mode)]
            for mode in ("mine", "insight", "report")
        }

    ids_a, ids_b = run_ids(rs_a, topic_a.topic_id), run_ids(rs_b, topic_b.topic_id)
    assert ids_a == ids_b
    # A test that only checked equality across the two seeds could pass
    # vacuously if a bug made every run id collapse to the same constant —
    # that would be deterministic too, just wrong. The two MINE runs within
    # *one* seed must still be two distinct runs.
    assert ids_a["mine"][0] != ids_a["mine"][1]

    mine_a, mine_b = rs_a.snapshots(topic_a.topic_id), rs_b.snapshots(topic_b.topic_id)
    mine_artifacts = ("signals.json", "provenance.json", "coverage.json", "cost.json", "plan.json")
    for run_a, run_b in zip(mine_a, mine_b):
        assert run_a.run_id == run_b.run_id
        assert run_a.started_at == run_b.started_at
        assert run_a.finished_at == run_b.finished_at
        for name in mine_artifacts:
            assert rs_a.read_artifact(run_a.run_id, name) == rs_b.read_artifact(run_b.run_id, name), name

    insight_a = rs_a.for_topic(topic_a.topic_id, "insight")[0]
    insight_b = rs_b.for_topic(topic_b.topic_id, "insight")[0]
    assert insight_a.started_at == insight_b.started_at
    assert insight_a.finished_at == insight_b.finished_at
    insight_artifacts = (
        "entities.json", "themes.json", "stance.json", "duallens.json",
        "momentum.json", "anomaly.json", "findings.json",
    )
    for name in insight_artifacts:
        assert rs_a.read_artifact(insight_a.run_id, name) == rs_b.read_artifact(insight_b.run_id, name), name

    report_a = rs_a.for_topic(topic_a.topic_id, "report")[0]
    report_b = rs_b.for_topic(topic_b.topic_id, "report")[0]
    assert report_a.started_at == report_b.started_at
    assert report_a.finished_at == report_b.finished_at
    report_artifacts = (
        "pulse_report.md", "provenance_appendix.md", "methodology.md", "worth_considering.md",
    )
    for name in report_artifacts:
        assert rs_a.read_artifact(report_a.run_id, name) == rs_b.read_artifact(report_b.run_id, name), name


def test_seeding_still_gives_real_topics_and_runs_random_ids(tmp_path):
    """The guard on the other side of the fix: only the demo seed's own
    topic and runs may be deterministic. A topic — and its own runs — a real
    visitor creates afterwards must still get genuinely random ids each
    time, proven by creating the same real topic twice and getting two
    different ids both times: the override parameters ``run_mine`` /
    ``run_insight`` / ``run_report`` gained for the seed default to ``None``
    and must never leak into an ordinary call.
    """
    ts, rs = _stores(tmp_path)
    seed_demo_topic(ts, rs, env={})  # occupies the store, exactly as production does

    real_1 = ts.create(name="Real topic", therapeutic_area="gi", spend_band="probe")
    real_2 = ts.create(name="Real topic", therapeutic_area="gi", spend_band="probe")
    assert real_1.topic_id != real_2.topic_id

    from vsm.demo import _stable_topic_id
    assert real_1.topic_id != _stable_topic_id()
    assert real_2.topic_id != _stable_topic_id()

    run_1 = rs.start(real_1.topic_id, "mine")
    run_2 = rs.start(real_1.topic_id, "mine")
    assert run_1.run_id != run_2.run_id
