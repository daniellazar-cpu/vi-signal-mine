import pytest

from vsm.analysis.anomaly import (
    MIN_VOLUME, Anomaly, baseline_for, detect_anomalies, median, narrate,
)
from vsm.analysis.cluster import Theme


def th(name, volume):
    return Theme(f"th-{name}", name, tuple(f"s{i}" for i in range(volume)), volume, {}, {})


def test_median_of_nothing_is_none():
    assert median([]) is None


def test_median_ignores_one_freak_week():
    """Mean would let a single spike redefine normal and then hide the next one."""
    assert median([4, 5, 400]) == 5
    assert median([4, 6]) == 5


def test_baseline_uses_the_LATEST_three_snapshots_not_the_oldest():
    """The baseline is the *previous* three snapshots — recency is the whole
    claim. A fixture where both ends of the list agree cannot prove that."""
    priors = [[th("x", 1)], [th("x", 2)], [th("x", 3)],
              [th("x", 7)], [th("x", 8)], [th("x", 9)]]
    assert baseline_for("x", priors) == 8


def test_baseline_is_the_median_not_the_mean_so_one_freak_week_does_not_redefine_normal():
    """A mean would let 400 drag the baseline up to ~136, which would then
    mask the next real spike instead of reporting it — the output would just
    look quiet. Median holds the baseline at a stable 5."""
    priors = [[th("x", 4)], [th("x", 5)], [th("x", 400)]]
    assert baseline_for("x", priors) == 5


def test_a_theme_appearing_is_an_anomaly():
    out = detect_anomalies([th("new", 6)], [[th("old", 6)]])
    kinds = {(a.kind, a.theme_name) for a in out}
    assert ("theme_appeared", "new") in kinds


def test_a_theme_vanishing_is_an_anomaly():
    out = detect_anomalies([th("kept", 5)], [[th("gone", 8), th("kept", 5)]])
    assert ("theme_vanished", "gone") in {(a.kind, a.theme_name) for a in out}


def test_a_spike_needs_both_a_multiple_and_a_floor():
    """A guard sitting behind a stricter guard is never reached by a fixture
    that trips the outer one first. observed=4 against baseline=1 clears the
    multiplier (4 > 2*1) cleanly, so only the floor stops it — that's the
    behaviour this test is named for."""
    noise = detect_anomalies([th("x", 4)], [[th("x", 1)], [th("x", 1)]])
    assert not [a for a in noise if a.kind == "volume_spike"], (
        "a 4x rise on a baseline of 1 is still only four mentions; the floor "
        "exists exactly so a tiny baseline cannot manufacture drama"
    )

    real = detect_anomalies([th("x", 20)], [[th("x", 5)], [th("x", 5)]])
    spike = [a for a in real if a.kind == "volume_spike"]
    assert spike and spike[0].observed == 20 and spike[0].baseline == 5


def test_no_baseline_means_no_anomalies_at_all():
    """On a first snapshot everything looks new. Reporting that would be noise
    dressed as insight."""
    assert detect_anomalies([th("x", 50)], []) == []


def test_narration_attaches_notes_without_touching_the_numbers():
    """Detection is reproducible arithmetic; only the prose is model-written."""
    detected = detect_anomalies([th("x", 20)], [[th("x", 5)], [th("x", 5)]])

    class _Client:
        def complete_structured(self, **kw):
            class _Out:
                ok = True
                data = {"notes": [{"anomaly_id": a.anomaly_id, "note": "discussion widened"}
                                  for a in detected]}
                reason = ""
            return _Out()

    narrated = narrate(detected, client=_Client())
    assert narrated[0].note == "discussion widened"
    assert narrated[0].observed == detected[0].observed
    assert narrated[0].baseline == detected[0].baseline


def test_narration_without_a_client_leaves_notes_empty():
    detected = detect_anomalies([th("x", 20)], [[th("x", 5)], [th("x", 5)]])
    assert all(a.note == "" for a in narrate(detected, client=None))
