from datetime import datetime, timezone

from vsm.mining.signals import Hit, build_row
from vsm.mining.tiers import assert_collectable

CLUSTER = {"cluster_id": "c1", "label": "oic", "terms": ["OIC"]}


def test_tier_c_is_recorded_not_refused():
    """Spec D5. The tier still lands on the row; it just no longer vetoes."""
    got = assert_collectable("https://www.doximity.com/some/post")
    assert got["tier"] == "C"


def test_tier_c_refusal_is_restorable_by_flag(monkeypatch):
    from vsm.mining.tiers import TierCRefused
    import pytest

    monkeypatch.setenv("VSM_ENFORCE_TIER_C", "1")
    with pytest.raises(TierCRefused):
        assert_collectable("https://www.doximity.com/some/post")


def test_snapshot_keys_are_absent_unless_asked_for():
    row = build_row(
        campaign_id="t1",
        cluster=CLUSTER,
        hit=Hit(url="https://example.org/a", title="A"),
        captured_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
    )
    assert "topic_id" not in row and "snapshot_at" not in row


def test_snapshot_keys_land_when_given():
    row = build_row(
        campaign_id="t1",
        cluster=CLUSTER,
        hit=Hit(url="https://example.org/a", title="A"),
        captured_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        topic_id="t1",
        snapshot_at="2026-08-25T00:00:00+00:00",
    )
    assert row["topic_id"] == "t1"
    assert row["snapshot_at"] == "2026-08-25T00:00:00+00:00"


def test_sentiment_is_still_none_on_a_fresh_row():
    """No classifier ran at collection time. The stance pass writes its own
    artifact; it must never back-fill this field, because a signal row says
    only what collection witnessed."""
    row = build_row(
        campaign_id="t1",
        cluster=CLUSTER,
        hit=Hit(url="https://example.org/a", title="A"),
        captured_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
    )
    assert row["sentiment"] is None
