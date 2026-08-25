import sqlite3
from contextlib import closing

import pytest

from vsm.errors import NoSuchRun
from vsm.runs.store import RunStore


@pytest.fixture
def store(tmp_path):
    return RunStore(tmp_path / "r.db", tmp_path / "var")


def test_start_then_finish(store):
    r = store.start("top-1", "mine")
    assert r.status == "running" and r.finished_at is None
    done = store.finish(r.run_id, "complete", cost_usd=0.0315)
    assert done.status == "complete"
    assert done.finished_at is not None
    assert done.cost_usd == pytest.approx(0.0315)


def test_get_unknown_raises(store):
    with pytest.raises(NoSuchRun):
        store.get("nope")


def test_snapshots_are_completed_mine_runs_oldest_first(store):
    """Every delta pass walks history forward, so the store hands it over in
    that order rather than making each caller remember to reverse it."""
    a = store.start("top-1", "mine")
    store.finish(a.run_id, "complete", cost_usd=0.01)
    b = store.start("top-1", "mine")
    store.finish(b.run_id, "complete", cost_usd=0.01)
    running = store.start("top-1", "mine")
    insight = store.start("top-1", "insight")
    store.finish(insight.run_id, "complete", cost_usd=0.0)

    ids = [r.run_id for r in store.snapshots("top-1")]
    assert ids == [a.run_id, b.run_id]
    assert running.run_id not in ids


def test_a_budget_stop_is_not_a_failure(store):
    """A cap breach is a clean stop with partial rows, not an error. It has its
    own status so a later reader can tell 'we stopped paying' from 'it broke'."""
    r = store.start("top-1", "mine")
    done = store.finish(r.run_id, "stopped_on_budget", cost_usd=5.0, note="cap bound at 5.0")
    assert done.status == "stopped_on_budget"
    assert "cap bound" in done.note


def test_artifacts_round_trip(store):
    r = store.start("top-1", "mine")
    path = store.write_artifact(r.run_id, "signals.json", [{"signal_id": "sig-1"}])
    assert path.exists()
    assert store.read_artifact(r.run_id, "signals.json") == [{"signal_id": "sig-1"}]


def test_artifact_name_cannot_escape_the_run_directory(store):
    r = store.start("top-1", "mine")
    with pytest.raises(ValueError):
        store.write_artifact(r.run_id, "../../etc/passwd", {})


def test_snapshot_order_survives_identical_timestamps(store):
    """Ordering is by the monotonic ``seq`` column, not by wall-clock time.

    Five runs started back-to-back in a tight loop would likely still land in
    seq order even if ``snapshots()`` sorted by ``started_at`` — clocks tend
    to advance, and this test would then pass for the wrong reason. To make
    it genuinely fail on a timestamp-based fallback, we scramble
    ``started_at`` after the fact so timestamp order is the *reverse* of
    ``seq`` order. Only an implementation that orders by ``seq`` survives.
    """
    ids = []
    for _ in range(5):
        r = store.start("top-1", "mine")
        store.finish(r.run_id, "complete", cost_usd=0.0)
        ids.append(r.run_id)

    with closing(sqlite3.connect(store.db_path)) as conn:
        for i, run_id in enumerate(ids):
            reversed_ts = f"2000-01-01T00:00:{len(ids) - i:02d}+00:00"
            conn.execute(
                "UPDATE runs SET started_at=? WHERE run_id=?", (reversed_ts, run_id)
            )
        conn.commit()

    assert [r.run_id for r in store.snapshots("top-1")] == ids


def test_parent_run_is_recorded(store):
    mine = store.start("top-1", "mine")
    store.finish(mine.run_id, "complete", cost_usd=0.0)
    ins = store.start("top-1", "insight", parent_run_id=mine.run_id)
    assert store.get(ins.run_id).parent_run_id == mine.run_id
