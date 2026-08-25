"""Spec D17 — INSIGHT is resumable.

See ``vsm/modes/insight.py``'s module docstring for the full design:
``resume=True`` (the default) skips any pass whose artifact is already on
*the same run* — found by matching this call's ``(topic_id,
snapshot_run_id)`` against existing INSIGHT runs, rather than starting a
fresh run every call. That lookup is what makes "skip" possible at all: a
brand-new run's artifact directory is always empty, so without it `resume`
would be a parameter that did nothing. ``resume=False`` targets that same
run but forces every pass to recompute regardless of what is already there.
"""

from __future__ import annotations

import time

from vsm.modes.insight import run_insight
from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore

ARTIFACTS = (
    "entities.json", "themes.json", "stance.json", "duallens.json",
    "momentum.json", "anomaly.json", "findings.json",
)


def _env(tmp_path):
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    topic = ts.create(
        name="OIC", therapeutic_area="gastroenterology", spend_band="standard",
        brand="Symproic", molecule="naldemedine",
    )
    return ts, rs, topic


def _rows(n_hcp, n_patient, theme="tolerability"):
    rows = [
        {"signal_id": f"h{i}", "venue": "studentdoctor.net", "theme": theme,
         "title": f"{theme} {i}", "excerpt": theme,
         "url": f"https://studentdoctor.net/{i}"}
        for i in range(n_hcp)
    ]
    rows += [
        {"signal_id": f"p{i}", "venue": "patient.info", "theme": theme,
         "title": f"{theme} p{i}", "excerpt": theme,
         "url": f"https://patient.info/{i}"}
        for i in range(n_patient)
    ]
    return rows


def _snapshot(rs, topic, rows):
    run = rs.start(topic.topic_id, "mine")
    rs.write_artifact(run.run_id, "signals.json", rows)
    rs.finish(run.run_id, "complete", cost_usd=0.01)
    return run


def _stat(rs, run_id, name):
    path = rs.artifacts_dir(run_id) / name
    return path.stat().st_mtime_ns, path.read_bytes()


def test_a_resumed_insight_skips_passes_already_on_disk(tmp_path):
    """Spec D17. INSIGHT is the mode that will hit a function timeout on a
    large snapshot. Each pass already writes its artifact the moment it
    finishes, so resuming costs a re-request rather than the work."""
    ts, rs, topic = _env(tmp_path)
    snap = _snapshot(rs, topic, _rows(3, 2))

    first = run_insight(topic, snap.run_id, rs)
    before = {name: _stat(rs, first.run_id, name) for name in ARTIFACTS}

    # A real gap, so a rewrite would show a measurably different mtime —
    # without it, a skip and a same-microsecond rewrite could be
    # indistinguishable on some filesystems.
    time.sleep(0.01)
    (rs.artifacts_dir(first.run_id) / "themes.json").unlink()

    second = run_insight(topic, snap.run_id, rs, resume=True)

    # A resumed run continues the SAME run. That is the property that makes
    # "skip" meaningful at all: a fresh run's artifact directory would always
    # be empty, and every pass would "have to" run regardless of `resume`.
    assert second.run_id == first.run_id

    # The deleted artifact is rebuilt, with real content.
    rebuilt = rs.artifacts_dir(first.run_id) / "themes.json"
    assert rebuilt.exists()
    assert rs.read_artifact(first.run_id, "themes.json")

    # Every surviving artifact was left completely alone: identical mtime AND
    # identical bytes. Either check alone could pass for the wrong reason —
    # content that happens to recompute identically would still show a
    # changed mtime if the pass had actually re-run, and a preserved mtime
    # with silently different bytes would mean something worse. Both
    # together are what prove a pass was skipped rather than re-run to the
    # same answer.
    for name in ARTIFACTS:
        if name == "themes.json":
            continue
        mtime_after, bytes_after = _stat(rs, first.run_id, name)
        mtime_before, bytes_before = before[name]
        assert mtime_after == mtime_before, f"{name} was rewritten (mtime changed)"
        assert bytes_after == bytes_before, f"{name} content changed"


def test_resume_false_rebuilds_everything(tmp_path):
    """Same setup as the resumed case, but `resume=False` must force every
    pass to recompute on the same run — proved by every artifact's mtime
    moving forward, not merely by the run completing."""
    ts, rs, topic = _env(tmp_path)
    snap = _snapshot(rs, topic, _rows(3, 2))

    first = run_insight(topic, snap.run_id, rs)
    before = {name: _stat(rs, first.run_id, name)[0] for name in ARTIFACTS}

    time.sleep(0.01)
    second = run_insight(topic, snap.run_id, rs, resume=False)

    assert second.run_id == first.run_id
    for name in ARTIFACTS:
        mtime_after, _ = _stat(rs, first.run_id, name)
        assert mtime_after != before[name], f"{name} was NOT rewritten"
