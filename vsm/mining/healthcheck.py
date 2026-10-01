"""A rehearsal of a sweep's Bright Data calls, to prove a sweep will work before it spends.

**It sends what a sweep sends.** Three real ``site:``-scoped gold queries from the
sweep's own planner (:func:`vsm.mining.queries.plan_queries`), with the sweep's
recency window, sent together the way :class:`~vsm.mining.miner.LiveSignalMining`
now sends them, through the same :class:`~vsm.mining.serp.SerpClient`. Then one Web
Unlocker fetch of the first result a sweep would page-fetch. Bright Data's own test
URL is only the fallback when no such result came back, and the detail says so.

A trivial query against a test page proved the key and nothing else: it passed in a
second while real ``site:`` queries took 20-70s each and a Wide sweep died at the
function timeout. The latencies measured here feed :func:`wide_sweep_fit`, which
says how many search groups a Wide sweep can cover in full inside the Vercel limit.

**Each call is made once** (``max_retries=0``): a throttled or cooling-down zone is
reported as the failure it is, not hidden behind retries, and the page's quoted cost
(three searches and one fetch, about one cent) is the cost.

Discover is not probed: it is a trigger-then-poll job rather than one request, so a
green result here does not vouch for a sweep's Discover leg.

The key is never returned or logged. Each result carries a status, a latency and a
short, safe detail string, and nothing else.
"""

from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from vsm.config import Settings, get_settings
from vsm.mining.client import BrightDataClient, BrightDataError
from vsm.mining.miner import MiningConfig
from vsm.mining.queries import plan_queries
from vsm.mining.recency import window_for
from vsm.mining.serp import SerpClient
from vsm.mining.tiers import page_fetch_allowed
from vsm.mining.venues import areas_for_cluster, catalogue_entries, gold_page_fetch_allowed

__all__ = [
    "CheckResult",
    "check_brightdata",
    "wide_sweep_fit",
    "PROBE_CLUSTER",
    "UNLOCKER_TEST_URL",
]

#: A topic every gold venue list covers, so the probe queries are the shape a sweep sends.
PROBE_CLUSTER: dict[str, Any] = {"cluster_id": "probe", "label": "semaglutide", "terms": ["semaglutide"]}
PROBE_SEARCHES = 3

#: Fallback Unlocker target when no search result is one a sweep would fetch.
UNLOCKER_TEST_URL = "https://geo.brdtest.com/welcome.txt?product=unlocker&method=api"


class CheckResult(dict):
    """A single call's result. A plain dict so a template and a JSON caller read it
    the same way; a class only so the shape is documented in one place.

    Keys: ``product`` (str), ``zone`` (str), ``ok`` (bool), ``detail`` (str, safe
    to display — never contains the key), ``latency_ms`` (int | None).
    """

    def __init__(self, product: str, zone: str, ok: bool, detail: str, latency_ms: int | None):
        super().__init__(product=product, zone=zone, ok=ok, detail=detail, latency_ms=latency_ms)


def _timed(fn: Any) -> tuple[bool, str, int | None]:
    """Run one probe, translating every outcome into (ok, detail, latency_ms).

    Bright Data's own errors carry the message a person needs — a 401/403 means the
    key or product is wrong, a 429 or a cooldown means the zone is throttled right
    now — so they are surfaced verbatim. An unexpected exception is caught too: a
    health check that raises looks like the app is broken when it is the connection.
    """
    start = time.monotonic()
    try:
        detail = fn()
        return True, detail, int((time.monotonic() - start) * 1000)
    except BrightDataError as exc:
        return False, str(exc), int((time.monotonic() - start) * 1000)
    except Exception as exc:  # noqa: BLE001 — a health check must never itself 500
        return False, f"unexpected error: {type(exc).__name__}: {exc}", int((time.monotonic() - start) * 1000)


def probe_queries(now: datetime) -> list[tuple[str, str]]:
    """The first gold queries a sweep would send for :data:`PROBE_CLUSTER`, with its tbs."""
    cfg = MiningConfig()
    window = window_for(now, cfg.recency_days)
    plan = plan_queries(
        PROBE_CLUSTER, PROBE_SEARCHES, areas=areas_for_cluster(PROBE_CLUSTER),
        sites_per_query=cfg.gold_sites_per_query, open_queries_max=0,
    )
    return [(p.text, window.tbs if p.date_restricted else "") for p in plan if p.kind == "gold"][:PROBE_SEARCHES]


def _fetchable(url: str) -> bool:
    return gold_page_fetch_allowed(url) and page_fetch_allowed(url, catalogue=catalogue_entries())


def check_brightdata(
    settings: Settings | None = None, *, transport: Any = None
) -> list[CheckResult]:
    """Three sweep-shaped searches in parallel, then one sweep-shaped page fetch.

    ``transport`` is the ``httpx`` seam the client exposes for tests — production
    passes nothing. Returns a row per product even when the key is missing, so the
    caller shows the same table whether the instance is configured or not.
    """
    s = settings or get_settings(refresh=True)
    if not s.brightdata_api_key:
        return [
            CheckResult(product, zone, False, "BRIGHTDATA_API_KEY is not set on this deployment.", None)
            for product, zone in (("SERP", s.brightdata_serp_zone), ("Web Unlocker", s.brightdata_unlocker_zone))
        ]

    client = BrightDataClient(s, transport=transport, max_retries=0)
    serp = SerpClient(client, zone=s.brightdata_serp_zone)
    links: list[str] = []

    def search(query_tbs: tuple[str, str]) -> CheckResult:
        query, tbs = query_tbs

        def probe() -> str:
            found = serp.search(query, limit=MiningConfig().serp_results_per_query, tbs=tbs)
            links.extend(r.link for r in found)
            window = "last 90 days" if tbs else "any date"
            return f"{len(found)} results, {window}: {query[:70]}…"

        return CheckResult("SERP", s.brightdata_serp_zone, *_timed(probe))

    try:
        queries = probe_queries(datetime.now(timezone.utc))
        with ThreadPoolExecutor(max_workers=len(queries)) as pool:
            results = list(pool.map(search, queries))
        target = next((u for u in links if _fetchable(u)), None)

        def unlock() -> str:
            resp = client.request(
                "POST", "/request",
                json_body={"zone": s.brightdata_unlocker_zone, "url": target or UNLOCKER_TEST_URL, "format": "raw"},
            )
            source = target or "Bright Data's test page (no search result was one a sweep would fetch)"
            return f"HTTP {resp.status_code}, {len((resp.text or '').strip()):,} characters from {source}"

        results.append(CheckResult("Web Unlocker", s.brightdata_unlocker_zone, *_timed(unlock)))
    finally:
        client.close()
    return results


def wide_sweep_fit(results: list[CheckResult], *, limit_s: float) -> dict[str, int] | None:
    """How much of a Wide sweep the measured speeds fit inside ``limit_s``.

    Per search group a Wide sweep sends its searches in parallel batches, then makes
    its page fetches one at a time; the slowest measured call of each kind sets the
    pace. ``None`` when a search or the page fetch failed, since there is no speed to
    project from.
    """
    from vsm.topics.model import BANDS

    searches = [r["latency_ms"] for r in results if r["product"] == "SERP" and r["ok"]]
    pages = [r["latency_ms"] for r in results if r["product"] == "Web Unlocker" and r["ok"]]
    if not searches or not pages or len(searches) < sum(r["product"] == "SERP" for r in results):
        return None
    wide = BANDS["deep"]
    search_s = max(searches) / 1000 * math.ceil(wide.queries_per_cluster / MiningConfig().parallel_searches)
    fetch_s = max(pages) / 1000 * wide.page_fetches_per_cluster
    return {
        "search_s": math.ceil(search_s),
        "fetch_s": math.ceil(fetch_s),
        "full_groups": int(limit_s // (search_s + fetch_s)),
        "limit_s": int(limit_s),
    }
