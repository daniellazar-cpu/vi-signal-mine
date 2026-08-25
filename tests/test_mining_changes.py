from datetime import datetime, timezone

import httpx
import pytest

from vsm.config import Settings
from vsm.mining.budget import Budget
from vsm.mining.client import BrightDataClient
from vsm.mining.discover import DiscoverClient
from vsm.mining.miner import LiveSignalMining, MiningConfig, MiningOutcome
from vsm.mining.robots import RobotsCache
from vsm.mining.serp import SerpClient
from vsm.mining.signals import Hit, build_row
from vsm.mining.tiers import assert_collectable
from vsm.mining.unlocker import UnlockerClient

CLUSTER = {"cluster_id": "c1", "label": "oic", "terms": ["OIC"]}

TIER_C_URL = "https://www.doximity.com/some/post"
ALLOWED_URL = "https://example-forum.org/t/1"


def _unlocker(handler) -> UnlockerClient:
    """A real UnlockerClient over httpx.MockTransport — no network, no key."""
    settings = Settings.from_env({"VSM_OFFLINE": "1", "BRIGHTDATA_API_KEY": "bd-fake"})
    bd_client = BrightDataClient(settings, transport=httpx.MockTransport(handler))
    return UnlockerClient(bd_client, zone=settings.brightdata_unlocker_zone)


def _page_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text="Real page content, long enough to be usable.")


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


# --------------------------------------------------------------------------- #
# Round 2 (coordinator correction): D5 has four gates, not one. tiers.py's
# assert_collectable (above) is gate 1. The other three — UnlockerClient.fetch's
# tier-C check, UnlockerClient.fetch's robots_ok=False check, and the run
# layer's own robots pre-check in LiveSignalMining._fetch_page — all share the
# same VSM_ENFORCE_TIER_C flag and must convert together, or D5 does not
# actually hold at runtime for the one surface (Web Unlocker) it names.
# --------------------------------------------------------------------------- #


def test_unlocker_fetch_records_tier_c_without_refusing():
    """Gate 2 (unlocker.py): a Tier-C URL is fetched, not refused, by default —
    and the tier it was classified at lands on the returned page."""
    client = _unlocker(_page_handler)
    page = client.fetch(TIER_C_URL, robots_ok=True)
    assert page.tier == "C"
    assert page.text


def test_unlocker_fetch_refuses_tier_c_when_enforced(monkeypatch):
    from vsm.mining.tiers import TierCRefused

    monkeypatch.setenv("VSM_ENFORCE_TIER_C", "1")
    client = _unlocker(_page_handler)
    with pytest.raises(TierCRefused):
        client.fetch(TIER_C_URL, robots_ok=True)


def test_unlocker_fetch_records_robots_disallow_without_refusing():
    """Gate 3 (unlocker.py): robots_ok=False is fetched, not refused, by
    default — and that answer lands on the returned page. ``robots_ok`` stays a
    required keyword (no default) — the caller must still have formed an
    opinion about robots.txt; D5 only removes its veto."""
    client = _unlocker(_page_handler)
    page = client.fetch(ALLOWED_URL, robots_ok=False)
    assert page.robots_ok is False
    assert page.text


def test_unlocker_fetch_refuses_robots_disallow_when_enforced(monkeypatch):
    from vsm.mining.client import BrightDataError

    monkeypatch.setenv("VSM_ENFORCE_TIER_C", "1")
    client = _unlocker(_page_handler)
    with pytest.raises(BrightDataError):
        client.fetch(ALLOWED_URL, robots_ok=False)


def _mining_for_robots(disallow: bool) -> tuple[LiveSignalMining, MiningOutcome, Budget]:
    robots_txt = "User-agent: *\nDisallow: /" if disallow else "User-agent: *\nAllow: /"
    robots = RobotsCache(fetch=lambda url: robots_txt)
    unlocker = _unlocker(_page_handler)
    mining = LiveSignalMining(serp=None, unlocker=unlocker, robots=robots)
    outcome = MiningOutcome()
    budget = Budget(campaign_id="t1")
    return mining, outcome, budget


def test_run_layer_surfaces_robots_answer_instead_of_dropping_row():
    """Gate 4 (miner.py _fetch_page): by default, a robots-disallowed host is no
    longer skipped — the page is still fetched, and the host/tier/robots answer
    are recorded in outcome.coverage rather than silently dropped (spec D5:
    "recorded per host in coverage — reporting, not gating")."""
    mining, outcome, budget = _mining_for_robots(disallow=True)
    hit = Hit(url=ALLOWED_URL, title="A", collection_tier="B")

    page, summary = mining._fetch_page(hit, budget=budget, outcome=outcome)

    assert page is not None, "D5: a robots Disallow must not drop the fetch by default"
    assert page.robots_ok is False
    assert len(outcome.coverage) == 1
    entry = outcome.coverage[0]
    assert entry["domain"] == "example-forum.org"
    assert entry["tier"] == "B"
    assert entry["robots_ok"] is False
    assert entry["enforced"] is False
    # the run layer's returned summary and the coverage record describe the same
    # robots answer — neither may silently diverge from the other
    assert entry["robots_summary"] == summary


def test_run_layer_enforced_mode_still_records_before_skipping(monkeypatch):
    """With VSM_ENFORCE_TIER_C=1, the run layer restores the parent's behaviour
    (page not fetched) — but the answer still reaches outcome.coverage first;
    nothing may be silently swallowed even in the enforcing branch."""
    monkeypatch.setenv("VSM_ENFORCE_TIER_C", "1")
    mining, outcome, budget = _mining_for_robots(disallow=True)
    hit = Hit(url=ALLOWED_URL, title="A", collection_tier="B")

    page, _summary = mining._fetch_page(hit, budget=budget, outcome=outcome)

    assert page is None, "parent behaviour restored under the flag"
    assert len(outcome.coverage) == 1
    entry = outcome.coverage[0]
    assert entry["domain"] == "example-forum.org"
    assert entry["tier"] == "B"
    assert entry["robots_ok"] is False
    assert entry["enforced"] is True


def test_run_layer_allows_pass_through_unaffected():
    """Sanity check: a robots-allowed host never touches outcome.coverage — that
    field is specifically for what D5 would otherwise have swallowed."""
    mining, outcome, budget = _mining_for_robots(disallow=False)
    hit = Hit(url=ALLOWED_URL, title="A", collection_tier="B")

    page, _summary = mining._fetch_page(hit, budget=budget, outcome=outcome)

    assert page is not None
    assert page.robots_ok is True
    assert outcome.coverage == []


# --------------------------------------------------------------------------- #
# Round 3 (coordinator correction): three more ungated drops surfaced by the
# round-2 smoke check — the parent's own "parser" and "run layer" checkpoints.
# Until these convert too, D5 is inert: a Tier-C host still produces no row at
# all, which is exactly the outcome the decision was meant to reverse.
# --------------------------------------------------------------------------- #


def _serp(handler) -> SerpClient:
    settings = Settings.from_env({"VSM_OFFLINE": "1", "BRIGHTDATA_API_KEY": "bd-fake"})
    bd_client = BrightDataClient(settings, transport=httpx.MockTransport(handler))
    return SerpClient(bd_client, zone=settings.brightdata_serp_zone)


def _serp_handler_with_tier_c(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "organic": [
                {
                    "rank": 1,
                    "title": "Doximity thread",
                    "link": TIER_C_URL,
                    "description": "clinicians discuss OIC",
                }
            ]
        },
    )


def _discover(handler) -> DiscoverClient:
    settings = Settings.from_env({"VSM_OFFLINE": "1", "BRIGHTDATA_API_KEY": "bd-fake"})
    bd_client = BrightDataClient(settings, transport=httpx.MockTransport(handler))
    return DiscoverClient(bd_client, sleep=lambda s: None)


def _discover_handler_with_tier_c(request: httpx.Request) -> httpx.Response:
    if request.method == "POST":
        return httpx.Response(200, json={"status": "ok", "task_id": "task-1"})
    return httpx.Response(
        200,
        json={
            "status": "done",
            "results": [
                {"link": TIER_C_URL, "title": "Doximity", "description": "d", "relevance_score": 0.9}
            ],
        },
    )


def test_serp_search_records_tier_c_without_stripping_it():
    """Gate 6 (serp.py): a Tier-C link survives the parser by default, carrying
    its tier. A parser that silently shortens its own result list is the worst
    of the seven gates — nothing downstream can tell "the venue said nothing"
    from "we deleted it"."""
    client = _serp(_serp_handler_with_tier_c)
    results = client.search("opioid-induced constipation forum")
    assert [r.link for r in results] == [TIER_C_URL]
    assert results[0].tier == "C"


def test_serp_search_strips_tier_c_when_enforced(monkeypatch):
    monkeypatch.setenv("VSM_ENFORCE_TIER_C", "1")
    client = _serp(_serp_handler_with_tier_c)
    results = client.search("opioid-induced constipation forum")
    assert results == []


def test_discover_rows_record_tier_c_without_stripping_it():
    """Gate 7 (discover.py): same contract as the SERP parser (gate 6)."""
    client = _discover(_discover_handler_with_tier_c)
    rows = client.discover("OIC", intent="clinical discussion")
    assert [r.link for r in rows] == [TIER_C_URL]
    assert rows[0].tier == "C"


def test_discover_rows_strip_tier_c_when_enforced(monkeypatch):
    monkeypatch.setenv("VSM_ENFORCE_TIER_C", "1")
    client = _discover(_discover_handler_with_tier_c)
    rows = client.discover("OIC", intent="clinical discussion")
    assert rows == []


def _call_rows_for(mining: LiveSignalMining, hits: list[Hit]) -> tuple[list[dict], set, set]:
    budget = Budget(campaign_id="t1")
    outcome = MiningOutcome()
    attempted: set[str] = set()
    restricted: set[str] = set()
    rows = mining._rows_for(
        hits,
        cluster=CLUSTER,
        campaign_id="t1",
        budget=budget,
        outcome=outcome,
        index={},
        attempted=attempted,
        restricted=restricted,
        state={"fetched": 0},
        denied=[],
        superseded=[],
        metadata_only=set(),
    )
    return rows, attempted, restricted


def test_run_layer_rows_for_records_tier_c_without_dropping_the_hit():
    """Gate 5 (miner.py _rows_for), isolated from the SERP/Discover parsers: a
    Hit already carrying a Tier-C url still becomes a row by default, with
    collection_tier == "C" so the tier is on the record, and its domain lands
    in `restricted` too — once as a row, once as a Tier-C host that was
    collected from. The excerpt rule is unrelated and must hold unchanged:
    D5 changed whether we collect, not whether we quote."""
    mining = LiveSignalMining(
        serp=None, discover=None, unlocker=None, robots=None, config=MiningConfig(fetch_pages=False)
    )
    hit = Hit(url=TIER_C_URL, title="Doximity thread", description="clinicians discuss OIC")

    rows, _attempted, restricted = _call_rows_for(mining, [hit])

    assert len(rows) == 1
    assert rows[0]["collection_tier"] == "C"
    assert rows[0]["excerpt"] is None, "D5 must not move the excerpt rule as a side effect"
    assert "doximity.com" in restricted


def test_run_layer_rows_for_still_drops_tier_c_hit_when_enforced(monkeypatch):
    monkeypatch.setenv("VSM_ENFORCE_TIER_C", "1")
    mining = LiveSignalMining(
        serp=None, discover=None, unlocker=None, robots=None, config=MiningConfig(fetch_pages=False)
    )
    hit = Hit(url=TIER_C_URL, title="Doximity thread", description="clinicians discuss OIC")

    rows, _attempted, restricted = _call_rows_for(mining, [hit])

    assert rows == []
    assert "doximity.com" in restricted


def _run_with_tier_c_serp_hit() -> tuple[LiveSignalMining, MiningConfig]:
    serp = _serp(_serp_handler_with_tier_c)
    config = MiningConfig(fetch_pages=False, discover_results_per_cluster=0)
    return LiveSignalMining(serp=serp, discover=None, unlocker=None, robots=None, config=config), config


def test_run_layer_end_to_end_produces_a_row_for_a_tier_c_hit_when_flag_unset():
    """End-to-end assertion through the full run layer (this is what the
    round-2 smoke check caught): with VSM_ENFORCE_TIER_C unset, a Tier-C host
    among the SERP hits produces a row, not a drop — gates 5 and 6 have to
    cooperate for that to happen, which a per-gate unit test cannot show by
    itself."""
    mining, _config = _run_with_tier_c_serp_hit()

    outcome = mining.run(campaign_id="camp1", clusters=[CLUSTER], queries_per_cluster=1)

    assert len(outcome.rows) == 1
    row = outcome.rows[0]
    assert row["venue"] == "doximity.com"
    assert row["collection_tier"] == "C"
    assert row["excerpt"] is None
    assert "doximity.com" in outcome.venues_restricted
    assert "doximity.com" in outcome.venues_collected


def test_run_layer_end_to_end_produces_no_row_when_enforced(monkeypatch):
    monkeypatch.setenv("VSM_ENFORCE_TIER_C", "1")
    mining, _config = _run_with_tier_c_serp_hit()

    outcome = mining.run(campaign_id="camp1", clusters=[CLUSTER], queries_per_cluster=1)

    assert outcome.rows == []
    assert "doximity.com" not in outcome.venues_collected
