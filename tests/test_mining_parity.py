"""The vendored copy must plan the same sweep as the parent.

This is the only test that reaches outside the repo. It imports the parent's
mining package directly from its checkout and asserts the two planners agree
query-for-query. If the parent is not present the test skips — it is a guard
against silent divergence during the fork, not a permanent dependency.
"""

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

PARENT = Path.home() / "Documents" / "forum-engine"

pytestmark = pytest.mark.skipif(
    not (PARENT / "engine" / "mining" / "queries.py").exists(),
    reason="parent checkout not present",
)


@pytest.fixture(scope="module")
def parent_queries():
    if str(PARENT) not in sys.path:
        sys.path.insert(0, str(PARENT))
    import engine.mining.queries as pq  # noqa: PLC0415

    return pq


CLUSTER = {
    "cluster_id": "c1",
    "label": "opioid-induced constipation management",
    "terms": ["opioid-induced constipation", "OIC", "naldemedine"],
    "areas": ["gastroenterology"],
}


def test_planned_queries_match_the_parent_exactly(parent_queries):
    from vsm.mining.queries import plan_queries

    # NOTE: the brief's draft of this test called
    # ``plan_queries(CLUSTER, queries_per_cluster=4)``. The parameter is
    # actually named ``count`` in both the parent and this vendored copy (see
    # every real call site: engine/mining/miner.py, engine/orchestrator/
    # estimate.py, engine/orchestrator/stages.py — all positional). A keyword
    # of ``queries_per_cluster`` raises TypeError against the real signature,
    # so it was a bug in the test draft, not a copy divergence. Fixed by
    # calling positionally, which matches parent and copy alike.
    ours = plan_queries(CLUSTER, 4)
    theirs = parent_queries.plan_queries(CLUSTER, 4)

    # NOTE: the brief's draft also read ``q.query`` — ``PlannedQuery`` has no
    # such attribute in either the parent or this copy; the field is
    # ``text`` (``as_dict()`` is what renames it to the "query" dict key).
    # Also a bug in the draft, fixed the same way: match the real dataclass.
    assert [q.text for q in ours] == [q.text for q in theirs]
    assert [q.kind for q in ours] == [q.kind for q in theirs]


def test_gold_registry_is_byte_identical():
    """The gold list was hand-verified on 2026-08-02 with a real robots.txt GET
    per domain, and three unreachable candidates were dropped rather than listed
    on faith. It must never be regenerated from memory."""
    import engine.mining.venues as theirs  # noqa: PLC0415

    from vsm.mining.venues import GOLD_VENUES, VERIFIED_AT

    assert VERIFIED_AT == theirs.VERIFIED_AT
    assert {v.domain for v in GOLD_VENUES} == {v.domain for v in theirs.GOLD_VENUES}
    assert {(v.domain, v.kind, v.collection_tier) for v in GOLD_VENUES} == {
        (v.domain, v.kind, v.collection_tier) for v in theirs.GOLD_VENUES
    }


def test_build_row_matches_the_parent_exactly():
    """Signals row shape is not negotiable (PRD §5.3). The two new D5 kwargs
    (topic_id, snapshot_at) must be strictly additive: with neither passed,
    the row must equal the parent's byte-for-byte, not merely be a superset
    of it; with both passed, they must add exactly those two keys and change
    no existing value."""
    import engine.mining.signals as parent_signals  # noqa: PLC0415

    from vsm.mining.signals import Hit, build_row

    hit = Hit(
        url="https://example.org/a",
        title="Managing OIC in practice",
        description="A clinician's discussion of laxative-refractory constipation.",
    )
    captured_at = datetime(2026, 8, 25, tzinfo=timezone.utc)

    ours = build_row(campaign_id="camp1", cluster=CLUSTER, hit=hit, captured_at=captured_at)
    theirs = parent_signals.build_row(
        campaign_id="camp1", cluster=CLUSTER, hit=hit, captured_at=captured_at
    )

    assert ours == theirs

    ours_with_snapshot = build_row(
        campaign_id="camp1",
        cluster=CLUSTER,
        hit=hit,
        captured_at=captured_at,
        topic_id="t1",
        snapshot_at="2026-08-25T00:00:00+00:00",
    )

    assert set(ours_with_snapshot) - set(ours) == {"topic_id", "snapshot_at"}
    for key in ours:
        assert ours_with_snapshot[key] == ours[key]
    assert ours_with_snapshot["topic_id"] == "t1"
    assert ours_with_snapshot["snapshot_at"] == "2026-08-25T00:00:00+00:00"
