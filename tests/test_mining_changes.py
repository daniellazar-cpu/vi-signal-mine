import json
from datetime import datetime, timezone

import httpx
import pytest

from vsm.config import Settings
from vsm.mining.budget import Budget
from vsm.mining.client import BrightDataClient, BrightDataError
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


# --------------------------------------------------------------------------- #
# Round 4 (review finding, Q1 - Important): gate 5 changed what
# venues_restricted means (now "seen as Tier C", not "refused"), but
# provenance["tier_c_refused"] still published that set unchanged — a false
# statement in the artifact a human actually reads: it names doximity.com as
# refused in the same outcome where a row was built for it. Worse than the
# silent drops removed in rounds 2-3, because it is present and wrong rather
# than merely absent.
# --------------------------------------------------------------------------- #


def test_tier_c_refused_is_empty_by_default_while_hosts_still_named():
    """With the flag off, nothing was actually refused — tier_c_refused must
    say so — but tier_c_hosts still names doximity.com as Tier C, so the
    record is not lost, only correctly labelled."""
    mining, _config = _run_with_tier_c_serp_hit()

    outcome = mining.run(campaign_id="camp1", clusters=[CLUSTER], queries_per_cluster=1)

    assert outcome.provenance["tier_c_refused"] == []
    assert "doximity.com" in outcome.provenance["tier_c_hosts"]


def test_tier_c_refused_is_populated_when_enforced(monkeypatch):
    """With the flag on, a hard-blocklisted domain like doximity.com is
    stripped upstream by the SERP parser (gate 6) before it ever reaches the
    run layer's own restricted-tracking, so it cannot demonstrate this case —
    that is the parser and the run layer correctly agreeing, not a gap.

    A host that is Tier C only via the campaign's own catalogue (not the hard
    blocklist) is the case that demonstrates it: the SERP parser has no
    catalogue to consult (it only ever sees the hard blocklist, see
    ``serp.py``'s ``tier_for(link)`` with no ``catalogue=``), so it survives
    the parser — but the run layer's ``is_tier_c(hit.url,
    catalogue=self.catalogue)`` still catches it and, enforced, refuses it:
    no row, and named in tier_c_refused, not just tier_c_hosts."""
    monkeypatch.setenv("VSM_ENFORCE_TIER_C", "1")
    catalogue = [{"domain": "restricted-by-catalogue.org", "collection_tier": "C"}]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "organic": [
                    {
                        "rank": 1,
                        "title": "Catalogue-restricted thread",
                        "link": "https://restricted-by-catalogue.org/t/1",
                        "description": "clinicians discuss OIC",
                    }
                ]
            },
        )

    serp = _serp(handler)
    mining = LiveSignalMining(
        serp=serp,
        discover=None,
        unlocker=None,
        robots=None,
        catalogue=catalogue,
        config=MiningConfig(fetch_pages=False, discover_results_per_cluster=0),
    )

    outcome = mining.run(campaign_id="camp1", clusters=[CLUSTER], queries_per_cluster=1)

    assert outcome.rows == []
    assert outcome.provenance["tier_c_refused"] == ["restricted-by-catalogue.org"]
    assert "restricted-by-catalogue.org" in outcome.provenance["tier_c_hosts"]


@pytest.mark.parametrize(
    ("title", "theme"),
    [
        ("Medicare covers GLP-1s for obesity starting 2026", "medicare covers glp-1s for obesity starting 2026"),
        ("Study compares GLP-1 agonists in OSA", "study compares glp-1 agonists in osa"),
        ("Itchy welt from Zepbound. What to do? - GLP-1 Connect", "itchy welt from zepbound. what to do?"),
        ("Outcomes 2020–2024 in adults", "outcomes 2020–2024 in adults"),
        ("Zepbound for weight loss: what to know - Mayo Clinic", "zepbound for weight loss: what to know"),
        ("Tirzepatide dosing | Healio", "tirzepatide dosing"),
        ("Tirzepatide dosing|Healio", "tirzepatide dosing"),
        ("Part one - part two — Site", "part one - part two"),
    ],
)
def test_theme_strips_a_site_tail_but_never_splits_a_hyphenated_word(title, theme):
    """Found on the first live sweep: "GLP-1s" read as a "Title - Site" separator,
    so a theme came out as "medicare covers glp". A dash separates a site name
    only with spaces around it."""
    row = build_row(
        campaign_id="camp1",
        cluster=CLUSTER,
        hit=Hit(url=ALLOWED_URL, title=title),
        captured_at=datetime(2026, 9, 27, tzinfo=timezone.utc),
    )
    assert row["theme"] == theme


def _serp_with_bodies(bodies: list[str]) -> tuple[SerpClient, list[int]]:
    """A SerpClient whose transport answers 200 with each body in turn."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        body = bodies[min(len(calls), len(bodies)) - 1]
        return httpx.Response(200, text=body)

    settings = Settings.from_env({"VSM_OFFLINE": "1", "BRIGHTDATA_API_KEY": "bd-fake"})
    bd_client = BrightDataClient(settings, transport=httpx.MockTransport(handler), sleep=lambda _s: None)
    return SerpClient(bd_client, zone="serp_api1"), calls


def test_an_empty_200_is_retried_not_parsed():
    """Seen live: Bright Data's SERP answers 200 with an empty body on some calls.
    That is a transient failure, so it is retried like a 5xx."""
    organic = '{"organic": [{"rank": 1, "title": "t", "link": "https://example.org/a"}]}'
    serp, calls = _serp_with_bodies(["", organic])
    results = serp.search("tirzepatide")
    assert [r.link for r in results] == ["https://example.org/a"]
    assert len(calls) == 2


def test_an_empty_200_that_persists_says_so():
    serp, calls = _serp_with_bodies([""])
    with pytest.raises(BrightDataError, match="empty body"):
        serp.search("tirzepatide")
    assert len(calls) == 3


def test_a_non_json_serp_body_is_quoted_in_the_error():
    """The old message blamed a missing brd_json=1 even when the URL carried it,
    and dropped the body that would have said what went wrong."""
    serp, _calls = _serp_with_bodies(["upstream timeout, retry later"])
    with pytest.raises(BrightDataError, match="upstream timeout, retry later"):
        serp.search("tirzepatide")


# --------------------------------------------------------------------------- #
# Found on the first client sweeps (28 Sep 2026): brand terms never reached the
# live miner, off-topic hits were filed as mentions, and a SERP "try again in 15
# seconds" answer was not retried.
# --------------------------------------------------------------------------- #

FILSPARI_CLUSTER = {"cluster_id": "c1", "label": "filspari", "terms": ["Filspari", "sparsentan"]}
ON_TOPIC = {"rank": 1, "title": "Filspari in IgAN: early experience",
            "link": "https://www.healio.com/news/nephrology/filspari", "description": "sparsentan data"}
OFF_TOPIC = {"rank": 2, "title": "Cancer: what physicians say, in their own words",
             "link": "https://kevinmd.com/topic/cancer", "description": "physician essays"}


def _mining_with_organic(items: list[dict]) -> LiveSignalMining:
    serp = _serp(lambda request: httpx.Response(200, json={"organic": items}))
    config = MiningConfig(fetch_pages=False, discover_results_per_cluster=0)
    return LiveSignalMining(serp=serp, discover=None, unlocker=None, robots=None, config=config)


def test_a_hit_naming_none_of_the_topic_terms_is_dropped_and_the_drop_is_named():
    """KevinMD index pages came back for a site-restricted query and were filed as
    mentions of the drug: matched_terms fell back to the query's first word."""
    mining = _mining_with_organic([ON_TOPIC, OFF_TOPIC])
    outcome = mining.run(campaign_id="camp1", clusters=[FILSPARI_CLUSTER], queries_per_cluster=1)
    assert {r["venue"] for r in outcome.rows} == {"healio.com"}
    assert "kevinmd.com" not in outcome.venues_collected
    assert any("none of its terms" in n for n in outcome.notes), outcome.notes


def test_a_hit_naming_the_topic_is_kept_when_the_cluster_terms_are_phrases():
    """The live lexicon writes terms as phrases ("Isembyld approval"); a Wide sweep
    on 1 Oct 2026 kept 0 of ~700 results because no headline repeats a phrase."""
    serp = _serp(lambda request: httpx.Response(200, json={"organic": [
        {"rank": 1, "title": "FDA clears Isembyld for SMA", "link": "https://www.healio.com/news/1",
         "description": "first muscle-targeted therapy"},
        {"rank": 2, "title": "Switching from Spinraza: what families report", "link": "https://www.healio.com/news/2",
         "description": "caregivers on intrathecal dosing"},
        OFF_TOPIC,
    ]}))
    mining = LiveSignalMining(
        serp=serp, config=MiningConfig(fetch_pages=False, discover_results_per_cluster=0),
        brand_terms={"isembyld": "ours", "apitegromab": "ours", "spinraza": "competitor"},
    )
    cluster = {"cluster_id": "approval", "label": "approval", "terms": ["Isembyld approval", "FDA approval apitegromab"]}
    outcome = mining.run(campaign_id="camp1", clusters=[cluster], queries_per_cluster=1)
    assert sorted(r["url"] for r in outcome.rows) == ["https://www.healio.com/news/1", "https://www.healio.com/news/2"]
    assert "kevinmd.com" not in outcome.venues_collected


def test_a_cluster_with_no_terms_is_not_filtered():
    mining = _mining_with_organic([OFF_TOPIC])
    cluster = {"cluster_id": "c1", "label": "documentation friction", "terms": []}
    outcome = mining.run(campaign_id="camp1", clusters=[cluster], queries_per_cluster=1)
    assert {r["venue"] for r in outcome.rows} == {"kevinmd.com"}


def test_the_live_miner_gets_the_topics_brand_terms():
    from vsm.mining import get_miner
    from vsm.topics.model import BANDS, Topic

    settings = Settings.from_env({"VSM_OFFLINE": "0", "VSM_MINER": "live", "BRIGHTDATA_API_KEY": "bd-fake"})
    topic = Topic(topic_id="t1", name="Filspari", therapeutic_area="IgA nephropathy", spend_band="probe",
                  created_at="2026-09-28", brand="Filspari", molecule="sparsentan", competitors=("Tarpeyo",))
    miner = get_miner(settings, band=BANDS["probe"], topic=topic)
    assert miner.brand_terms == {"filspari": "ours", "sparsentan": "ours", "tarpeyo": "competitor"}


def test_the_mine_route_hands_the_topic_to_get_miner(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import vsm.ui.app as ui_app
    from vsm.mining.fake import DeterministicMiner
    from vsm.runs.store import RunStore
    from vsm.topics.store import TopicStore

    seen = {}

    def spy(settings=None, **kwargs):
        seen.update(kwargs)
        return DeterministicMiner(queries_per_cluster=2)

    monkeypatch.setattr(ui_app, "get_miner", spy)
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    topic = ts.create(name="Filspari", therapeutic_area="nephrology", spend_band="probe", brand="Filspari")
    client = TestClient(ui_app.create_app(topic_store=ts, run_store=rs))
    assert client.post(f"/topics/{topic.topic_id}/mine", data={}, follow_redirects=False).status_code == 303
    assert seen.get("topic") is not None and seen["topic"].topic_id == topic.topic_id


def test_a_serp_recently_failed_answer_is_retried_after_the_wait_it_names():
    busy = ("This query recently failed and cannot be attempted at this time. Please try again later, "
            "after a minimum of 15 seconds. https://docs.brightdata.com/scraping-automation/serp-api/debugging")
    organic = '{"organic": [{"rank": 1, "title": "t", "link": "https://example.org/a"}]}'
    bodies, calls, waits = [busy, organic], [], []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, text=bodies[min(len(calls), len(bodies)) - 1])

    settings = Settings.from_env({"VSM_OFFLINE": "1", "BRIGHTDATA_API_KEY": "bd-fake"})
    serp = SerpClient(BrightDataClient(settings, transport=httpx.MockTransport(handler), sleep=waits.append),
                      zone="serp_api1")
    assert [r.link for r in serp.search("filspari")] == ["https://example.org/a"]
    assert len(calls) == 2
    assert waits and waits[0] >= 15, waits


THROTTLED = ("The request was auto-throttled due to low success rate. "
             "Please decrease your request rate to 10/min.")
ORGANIC = '{"organic": [{"rank": 1, "title": "t", "link": "https://example.org/a"}]}'


def _throttling_serp(bodies_for: dict[str, list[str]], waits: list[float]) -> tuple[SerpClient, list[str]]:
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent.append(body["zone"])
        queue = bodies_for[body["zone"]]
        return httpx.Response(200, text=queue.pop(0) if len(queue) > 1 else queue[0])

    settings = Settings.from_env({"VSM_OFFLINE": "1", "BRIGHTDATA_API_KEY": "bd-fake"})
    client = BrightDataClient(settings, transport=httpx.MockTransport(handler), sleep=waits.append)
    return SerpClient(client, zone="serp_api1"), sent


def test_an_auto_throttled_answer_is_retried_at_the_rate_it_names():
    """Live on 1 Oct 2026: 68 of 81 Wide-sweep searches got this 200 and failed in
    under a second each, because nothing recognised it."""
    waits: list[float] = []
    serp, sent = _throttling_serp({"serp_api1": [THROTTLED, ORGANIC]}, waits)
    assert [r.link for r in serp.search("isembyld")] == ["https://example.org/a"]
    assert len(sent) == 2
    assert waits and min(waits) > 5.9, waits


def test_after_a_throttle_every_later_call_to_that_zone_is_paced():
    waits: list[float] = []
    serp, sent = _throttling_serp({"serp_api1": [THROTTLED, ORGANIC]}, waits)
    serp.search("first")
    waits.clear()
    serp.search("second")
    serp.search("third")
    assert len(waits) == 2 and all(w > 0 for w in waits), waits


def test_a_throttle_on_one_zone_does_not_pace_another():
    waits: list[float] = []
    serp, sent = _throttling_serp({"serp_api1": [THROTTLED, ORGANIC], "web_unlocker1": ["page"]}, waits)
    serp.search("first")
    waits.clear()
    serp.client.request("POST", "/request", json_body={"zone": "web_unlocker1", "url": "https://x.org", "format": "raw"})
    assert waits == []


@pytest.mark.parametrize(
    ("host", "verdict"),
    [
        ("briumvi.com", "brand_site"),
        ("briumvihcp.com", "brand_site"),
        ("mybriumvi.com", "brand_site"),
        ("www.ocrevus.com", "brand_site"),
        ("tgtherapeutics.com", "pharma_corporate"),
        ("ir.tgtherapeutics.com", "pharma_corporate"),
        ("travere.com", "pharma_corporate"),
        ("nationalmssociety.org", None),
        ("healio.com", None),
    ],
)
def test_the_sponsors_own_sites_are_denied_but_a_curated_venue_never_is(host, verdict):
    """Seen live: briumvihcp.com and two TG Therapeutics pages became Briumvi mentions,
    because the brand rule needed a host label to equal the brand exactly."""
    from vsm.mining.denylist import brand_domain_slugs, deny_reason

    slugs = brand_domain_slugs({"briumvi": "ours", "ublituximab": "ours", "ocrevus": "competitor", "healio": "ours"})
    got = deny_reason(host, brand_slugs=slugs)
    assert (got[0] if got else None) == verdict


def test_a_hit_admitted_by_a_topic_name_records_that_name_as_matched():
    serp = _serp(lambda request: httpx.Response(200, json={"organic": [
        {"rank": 1, "title": "FDA clears Isembyld for SMA", "link": "https://www.healio.com/news/1",
         "description": "first muscle-targeted therapy"}]}))
    mining = LiveSignalMining(
        serp=serp, config=MiningConfig(fetch_pages=False, discover_results_per_cluster=0),
        brand_terms={"isembyld": "ours", "": "ours"},
    )
    cluster = {"cluster_id": "approval", "label": "approval", "terms": ["Isembyld approval"]}
    outcome = mining.run(campaign_id="camp1", clusters=[cluster], queries_per_cluster=1)
    assert [r["matched_terms"] for r in outcome.rows] == [["isembyld"]]


def test_an_empty_topic_name_does_not_switch_the_filter_off():
    serp = _serp(lambda request: httpx.Response(200, json={"organic": [OFF_TOPIC]}))
    mining = LiveSignalMining(
        serp=serp, config=MiningConfig(fetch_pages=False, discover_results_per_cluster=0),
        brand_terms={"": "ours", "isembyld": "ours"},
    )
    cluster = {"cluster_id": "approval", "label": "approval", "terms": ["Isembyld approval"]}
    assert mining.run(campaign_id="camp1", clusters=[cluster], queries_per_cluster=1).rows == []
