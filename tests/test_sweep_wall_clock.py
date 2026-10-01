"""A Wide sweep has to finish inside a Vercel function's 800 seconds."""

import json
import threading
import time
import zlib

import httpx

from vsm.config import Settings
from vsm.mining.client import BrightDataClient
from vsm.mining.miner import LiveSignalMining, MiningConfig
from vsm.mining.serp import SerpClient
from vsm.mining.unlocker import UnlockerClient

TERMS = ["OIC", "naloxegol", "methylnaltrexone"]
CLUSTERS = [
    {"cluster_id": f"c{i}", "label": term, "terms": [term], "areas": ["gastroenterology"]}
    for i, term in enumerate(TERMS)
]
SERP_LATENCY_S = 0.3


def _bd(handler) -> BrightDataClient:
    settings = Settings.from_env({"VSM_OFFLINE": "1", "BRIGHTDATA_API_KEY": "bd-fake"})
    return BrightDataClient(settings, transport=httpx.MockTransport(handler))


def _slow_serp(request: httpx.Request) -> httpx.Response:
    time.sleep(SERP_LATENCY_S)
    target = json.loads(request.content)["url"]
    n = zlib.crc32(target.encode())
    return httpx.Response(200, json={"organic": [
        {"rank": 1, "title": f"{' '.join(TERMS)} thread {n}", "description": "clinicians discuss it",
         "link": f"https://gi.org/guidelines/{n}"},
    ]})


def _mining(config: MiningConfig, page_calls: list[str]) -> LiveSignalMining:
    def page(request: httpx.Request) -> httpx.Response:
        page_calls.append(str(request.url))
        return httpx.Response(200, text="Real page content about OIC, long enough to be usable.")

    settings = Settings.from_env({"VSM_OFFLINE": "1"})
    return LiveSignalMining(
        serp=SerpClient(_bd(_slow_serp), zone=settings.brightdata_serp_zone),
        unlocker=UnlockerClient(_bd(page), zone=settings.brightdata_unlocker_zone),
        catalogue=[{"domain": "gi.org", "collection_tier": "A"}],
        config=config,
    )


def test_gold_queries_are_sent_in_parallel():
    config = MiningConfig(queries_per_cluster=3, discover_results_per_cluster=0, fetch_pages=False,
                          probe_outside_window=False)
    mining = _mining(config, [])
    started = time.monotonic()
    outcome = mining.run(campaign_id="camp", clusters=CLUSTERS)
    elapsed = time.monotonic() - started

    serp_calls = [c for c in outcome.calls if c["kind"] == "serp"]
    assert len(serp_calls) == 9
    assert all(c["status"] == "ok" for c in serp_calls)
    assert outcome.rows
    assert elapsed < SERP_LATENCY_S * len(serp_calls) / 2


def test_past_the_time_limit_pages_are_skipped_and_rows_are_kept():
    config = MiningConfig(queries_per_cluster=3, discover_results_per_cluster=0,
                          page_fetches_per_cluster=2, time_limit_s=SERP_LATENCY_S * 2 / 3)
    page_calls: list[str] = []
    outcome = _mining(config, page_calls).run(campaign_id="camp", clusters=CLUSTERS)

    assert page_calls == []
    assert outcome.rows
    assert any("time limit" in n for n in outcome.notes)


def test_no_search_starts_after_the_time_limit():
    config = MiningConfig(queries_per_cluster=3, discover_results_per_cluster=0, fetch_pages=False,
                          time_limit_s=0.0)
    outcome = _mining(config, []).run(campaign_id="camp", clusters=CLUSTERS)

    assert [c for c in outcome.calls if c["kind"] == "serp"] == []
    assert any("time limit" in n for n in outcome.notes)


def test_inside_the_time_limit_pages_are_fetched():
    config = MiningConfig(queries_per_cluster=3, discover_results_per_cluster=0,
                          page_fetches_per_cluster=2, time_limit_s=600.0)
    page_calls: list[str] = []
    _mining(config, page_calls).run(campaign_id="camp", clusters=CLUSTERS)

    assert page_calls


def test_parallel_search_uses_more_than_one_thread():
    seen: set[int] = set()

    def serp(request: httpx.Request) -> httpx.Response:
        seen.add(threading.get_ident())
        return _slow_serp(request)

    settings = Settings.from_env({"VSM_OFFLINE": "1"})
    config = MiningConfig(queries_per_cluster=3, discover_results_per_cluster=0, fetch_pages=False)
    LiveSignalMining(
        serp=SerpClient(_bd(serp), zone=settings.brightdata_serp_zone), config=config
    ).run(campaign_id="camp", clusters=CLUSTERS)

    assert len(seen) > 1


def test_a_sweep_that_skipped_nothing_does_not_claim_the_limit():
    """The ninth search starts before the limit and ends after it; nothing was skipped."""
    config = MiningConfig(queries_per_cluster=3, discover_results_per_cluster=0, fetch_pages=False,
                          probe_outside_window=False, time_limit_s=SERP_LATENCY_S * 1.5)
    outcome = _mining(config, []).run(campaign_id="camp", clusters=CLUSTERS)

    assert not any("time limit" in n for n in outcome.notes)
    assert not any("time limit" in d["reason"] for d in outcome.deferrals)
