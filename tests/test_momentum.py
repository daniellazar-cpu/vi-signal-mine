import pytest

from vsm.analysis.cluster import Theme
from vsm.analysis.momentum import momentum


def th(name, volume):
    return Theme(f"th-{name}", name, tuple(f"s{i}" for i in range(volume)), volume, {}, {})


def test_first_snapshot_reports_no_baseline_rather_than_a_trend():
    out = momentum([th("tolerability", 5)], prior_snapshots=[])
    assert out[0].volume_now == 5
    assert out[0].volume_prior is None
    assert out[0].delta is None and out[0].delta_pct is None
    assert out[0].reason == "no prior snapshot"


def test_growth_against_the_immediately_prior_snapshot():
    out = momentum([th("tolerability", 12)], prior_snapshots=[[th("tolerability", 8)]])
    assert out[0].volume_prior == 8
    assert out[0].delta == 4
    assert out[0].delta_pct == pytest.approx(50.0)


def test_decline_is_negative():
    out = momentum([th("cost", 3)], prior_snapshots=[[th("cost", 6)]])
    assert out[0].delta == -3
    assert out[0].delta_pct == pytest.approx(-50.0)


def test_the_comparison_is_against_the_latest_prior_not_the_oldest():
    out = momentum([th("x", 10)], prior_snapshots=[[th("x", 1)], [th("x", 9)]])
    assert out[0].volume_prior == 9


def test_a_theme_absent_from_the_prior_snapshot_is_new_not_infinite_growth():
    out = momentum([th("new thing", 4)], prior_snapshots=[[th("other", 4)]])
    assert out[0].volume_prior == 0
    assert out[0].delta == 4
    assert out[0].delta_pct is None
    assert "not present" in out[0].reason


def test_a_theme_that_vanished_is_reported_at_zero():
    """A theme dropping out is a finding. Omitting it would hide the change."""
    out = momentum([th("still here", 2)], prior_snapshots=[[th("gone", 7), th("still here", 2)]])
    names = {m.theme_name: m for m in out}
    assert names["gone"].volume_now == 0
    assert names["gone"].delta == -7


def test_no_field_named_forecast_exists():
    """D13. We describe measured movement; we do not predict."""
    import dataclasses

    from vsm.analysis.momentum import ThemeMomentum

    names = {f.name for f in dataclasses.fields(ThemeMomentum)}
    assert not {"forecast", "predicted", "projection", "trend_value"} & names
