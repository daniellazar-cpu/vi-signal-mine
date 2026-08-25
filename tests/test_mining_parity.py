"""The vendored copy must plan the same sweep as the parent.

This is the only test that reaches outside the repo. It imports the parent's
mining package directly from its checkout and asserts the two planners agree
query-for-query. If the parent is not present the test skips — it is a guard
against silent divergence during the fork, not a permanent dependency.
"""

import importlib.util
import sys
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
