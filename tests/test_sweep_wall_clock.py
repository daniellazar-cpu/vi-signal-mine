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


def test_pages_are_fetched_while_later_searches_are_still_running():
    """A throttled SERP zone paced a Wide sweep's searches across the whole limit; page
    fetches that waited for every search to land never ran."""
    search_ends: list[float] = []
    page_starts: list[float] = []

    def serp(request: httpx.Request) -> httpx.Response:
        response = _slow_serp(request)
        search_ends.append(time.monotonic())
        return response

    def page(request: httpx.Request) -> httpx.Response:
        page_starts.append(time.monotonic())
        return httpx.Response(200, text="Real page content about OIC, long enough to be usable.")

    settings = Settings.from_env({"VSM_OFFLINE": "1"})
    config = MiningConfig(queries_per_cluster=3, discover_results_per_cluster=0, page_fetches_per_cluster=1,
                          parallel_searches=1, probe_outside_window=False)
    LiveSignalMining(
        serp=SerpClient(_bd(serp), zone=settings.brightdata_serp_zone),
        unlocker=UnlockerClient(_bd(page), zone=settings.brightdata_unlocker_zone),
        catalogue=[{"domain": "gi.org", "collection_tier": "A"}],
        config=config,
    ).run(campaign_id="camp", clusters=CLUSTERS)

    assert page_starts and min(page_starts) < max(search_ends)


def test_a_search_the_limit_stops_is_noted_not_counted_and_does_not_end_the_sweep():
    config = MiningConfig(queries_per_cluster=3, discover_results_per_cluster=0, fetch_pages=False,
                          parallel_searches=1, probe_outside_window=False, time_limit_s=SERP_LATENCY_S * 2.5)
    outcome = _mining(config, []).run(campaign_id="camp", clusters=CLUSTERS)

    targeting = outcome.provenance["targeting"]
    sent = [c for c in outcome.calls if c["kind"] == "serp"]
    assert targeting["gold_queries_run"] == len(sent) < targeting["gold_queries_planned"]
    assert any("was not sent" in n for n in outcome.notes)
    assert not any("sweep stopped early" in n for n in outcome.notes)


# --------------------------------------------------------------------------- #
# review findings, 1 Oct 2026                                                  #
# --------------------------------------------------------------------------- #


class _RecordingDiscover:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def discover(self, query, **_):
        self.calls.append(query)
        return []


def test_discover_is_skipped_past_the_time_limit():
    discover = _RecordingDiscover()
    config = MiningConfig(queries_per_cluster=3, discover_results_per_cluster=5, fetch_pages=False,
                          probe_outside_window=False, time_limit_s=0.0)
    mining = _mining(config, [])
    mining.discover = discover
    outcome = mining.run(campaign_id="camp", clusters=CLUSTERS)
    assert discover.calls == []
    assert any("intent discovery" in n for n in outcome.notes)


def test_no_retry_starts_after_the_clients_stop_time():
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(502, text="bad gateway")

    client = _bd(handler)
    client._sleep = lambda s: None
    client.stop_at = time.monotonic() - 1
    try:
        client.request("POST", "/request", json_body={"zone": "z", "url": "u", "format": "raw"})
    except Exception:
        pass
    assert calls == [1]


def test_a_wait_is_cut_at_the_clients_stop_time():
    waits: list[float] = []
    client = _bd(lambda request: httpx.Response(502, text="bad gateway"))
    client._sleep = waits.append
    client.stop_at = time.monotonic() + 0.5
    client._backoff(0, at_least=300.0)
    assert waits and waits[0] <= 0.5


def test_an_unexpected_error_in_a_search_is_recorded_not_raised():
    settings = Settings.from_env({"VSM_OFFLINE": "1"})
    real = SerpClient(_bd(_slow_serp), zone=settings.brightdata_serp_zone)

    class _Flaky:
        client = real.client

        def search_url(self, query, **kw):
            return real.search_url(query, **kw)

        def search(self, query, **kw):
            if query.startswith("naloxegol"):
                raise ValueError("malformed rank")
            return real.search(query, **kw)

    config = MiningConfig(queries_per_cluster=3, discover_results_per_cluster=0, fetch_pages=False,
                          probe_outside_window=False)
    outcome = LiveSignalMining(serp=_Flaky(), config=config).run(campaign_id="camp", clusters=CLUSTERS)
    failed = [c for c in outcome.calls if c["kind"] == "serp" and c["status"] == "error"]
    assert failed and all("ValueError" in (c.get("error") or "") for c in failed)
    assert outcome.rows


def test_the_time_limit_note_names_only_what_was_skipped():
    """The ninth search lands after the limit, so only its page fetch is skipped."""
    config = MiningConfig(queries_per_cluster=3, discover_results_per_cluster=0, page_fetches_per_cluster=3,
                          probe_outside_window=False, time_limit_s=SERP_LATENCY_S * 1.5)
    outcome = _mining(config, []).run(campaign_id="camp", clusters=CLUSTERS)
    note = next(n for n in outcome.notes if n.startswith("time limit of"))
    assert "page fetches" in note
    assert "open-web" not in note and "probes" not in note


class _RefusingLedger:
    """Allows the up-front check and the first three searches, then refuses."""

    def __init__(self) -> None:
        self.checks = 0

    def fetches(self, campaign_id):
        return 0

    def authorize_fetch(self, *, campaign_id, units, account, dry_run):
        self.checks += 1
        if self.checks > 4:
            raise RuntimeError("monthly quota reached")

    def record_fetch(self, **_):
        pass


def test_searches_sent_but_not_read_are_still_recorded():
    config = MiningConfig(queries_per_cluster=3, discover_results_per_cluster=0, fetch_pages=False,
                          probe_outside_window=False)
    mining = _mining(config, [])
    mining.quota = _RefusingLedger()
    outcome = mining.run(campaign_id="camp", clusters=CLUSTERS)
    serp_calls = [c for c in outcome.calls if c["kind"] == "serp"]
    in_flight = next((int(n.split()[0]) for n in outcome.notes if "still in flight" in n), 0)
    assert any("sweep stopped early" in n for n in outcome.notes)
    assert len(serp_calls) + in_flight == 9
    assert sum("not read" in (c.get("detail") or "") for c in serp_calls) + in_flight == 6
