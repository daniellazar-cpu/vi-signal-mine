from vsm.analysis.momentum import NO_BASELINE
import pytest

from vsm.modes.insight import run_insight
from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore

ARTIFACTS = ("entities.json", "findings.json", "themes.json", "stance.json",
             "duallens.json", "momentum.json", "anomaly.json")


@pytest.fixture
def env(tmp_path):
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    topic = ts.create(name="OIC", therapeutic_area="gastroenterology",
                      spend_band="standard", brand="Symproic", molecule="naldemedine")
    return ts, rs, topic


def _snapshot(rs, topic, rows):
    run = rs.start(topic.topic_id, "mine")
    rs.write_artifact(run.run_id, "signals.json", rows)
    rs.finish(run.run_id, "complete", cost_usd=0.01)
    return run


def _rows(n_hcp, n_patient, theme="tolerability"):
    rows = [{"signal_id": f"h{i}", "venue": "studentdoctor.net", "theme": theme,
             "title": f"{theme} {i}", "excerpt": theme,
             "url": f"https://studentdoctor.net/{i}"} for i in range(n_hcp)]
    rows += [{"signal_id": f"p{i}", "venue": "patient.info", "theme": theme,
              "title": f"{theme} p{i}", "excerpt": theme,
              "url": f"https://patient.info/{i}"} for i in range(n_patient)]
    return rows


def test_insight_writes_all_seven_artifacts(env):
    ts, rs, topic = env
    snap = _snapshot(rs, topic, _rows(2, 2))
    run = run_insight(topic, snap.run_id, rs)
    for name in ARTIFACTS:
        assert (rs.artifacts_dir(run.run_id) / name).exists(), name


def test_the_insight_run_records_its_snapshot_as_parent(env):
    ts, rs, topic = env
    snap = _snapshot(rs, topic, _rows(1, 1))
    run = run_insight(topic, snap.run_id, rs)
    assert run.parent_run_id == snap.run_id


def test_first_snapshot_momentum_says_no_baseline(env):
    ts, rs, topic = env
    snap = _snapshot(rs, topic, _rows(2, 1))
    run = run_insight(topic, snap.run_id, rs)
    momentum = rs.read_artifact(run.run_id, "momentum.json")
    assert momentum and all(m["reason"] == NO_BASELINE for m in momentum)
    assert rs.read_artifact(run.run_id, "anomaly.json") == []


def test_second_snapshot_compares_against_the_first(env):
    ts, rs, topic = env
    _snapshot(rs, topic, _rows(2, 0))
    second = _snapshot(rs, topic, _rows(6, 0))
    run = run_insight(topic, second.run_id, rs)
    momentum = {m["theme_name"]: m for m in rs.read_artifact(run.run_id, "momentum.json")}
    assert momentum["tolerability"]["volume_prior"] == 2
    assert momentum["tolerability"]["delta"] == 4


def test_a_prior_snapshot_after_this_one_is_not_used_as_a_baseline(env):
    """History is what came before. Comparing against a later snapshot would
    make the delta depend on when the insight run happened."""
    ts, rs, topic = env
    first = _snapshot(rs, topic, _rows(2, 0))
    _snapshot(rs, topic, _rows(50, 0))
    run = run_insight(topic, first.run_id, rs)
    momentum = rs.read_artifact(run.run_id, "momentum.json")
    assert all(m["reason"] == NO_BASELINE for m in momentum)


def test_stance_artifact_records_its_basis(env):
    ts, rs, topic = env
    snap = _snapshot(rs, topic, _rows(1, 1))
    run = run_insight(topic, snap.run_id, rs)
    stance = rs.read_artifact(run.run_id, "stance.json")
    assert stance and all(s["basis"] == "venue" for s in stance)
