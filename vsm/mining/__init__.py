"""Bright Data connectors for Stage 2 signal mining (PRD §5 stage 2, §9.1, §13.1).

Three small, typed clients over one HTTP surface — `httpx` only, no new
dependency, no SDK:

* :class:`~vsm.mining.serp.SerpClient`      — SERP API: query → organic results.
* :class:`~vsm.mining.discover.DiscoverClient` — Discover API: intent-ranked
  discovery (async trigger → poll).
* :class:`~vsm.mining.unlocker.UnlockerClient` — Web Unlocker: fetch one public
  page that blocks a plain ``GET``.

and the run layer that turns clusters into normalised signal rows:

* :class:`~vsm.mining.miner.LiveSignalMining` — expand → search → discover →
  (tier-permitting) unlock → normalise → dedupe, under a result cap and a ledger.

and the three modules that decide *where* a sweep spends:

* :mod:`~vsm.mining.venues` — the **gold list**: a hand-verified venue registry
  (evidence, guideline bodies by specialty, regulatory, HCP discussion, patient
  communities), routed by therapeutic area. Gold-scoped SERP queries come first and
  only a gold host is ever page-fetched.
* :mod:`~vsm.mining.denylist` — what is **not worth paying for**: brand and
  pharma-corporate sites, content farms, pay-to-publish publishers, repository
  duplicates. Separate from tier C, which is *may not* rather than *not worth it*.
* :mod:`~vsm.mining.recency` — the 90-day-plus window, applied to discussion and
  community venues and **never** to evidence or guidelines, where the test is
  current edition rather than recent date.

**Nothing here decides policy on its own.** Tier C is a blocklist in
:mod:`vsm.mining.tiers` and it is checked before a URL is ever handed to a
client. By default (spec D5) that check *records* the tier rather than
refusing it — ``VSM_ENFORCE_TIER_C=1`` restores the parent's refusal, at
which point the clients themselves also refuse a Tier-C URL, so a future
caller cannot route around the run layer.

Every client takes an injectable ``transport`` (``httpx.MockTransport``) so the
whole package is testable with zero network — which is how it is tested, because
there is no Bright Data key in the build environment. See ``tests/test_mining.py``.
"""

from __future__ import annotations

from typing import Any

from vsm.config import Settings, get_settings
from vsm.errors import ConfigError
from vsm.mining.budget import (
    DISCOVER_COST_PER_RESULT_USD,
    FREE_TIER_RESULTS_PER_MONTH,
    SERP_COST_PER_REQUEST_USD,
    UNLOCKER_COST_PER_SUCCESS_USD,
    Budget,
    FetchCall,
)
from vsm.mining.client import (
    BrightDataAuthError,
    BrightDataClient,
    BrightDataError,
    BrightDataRateLimited,
)
from vsm.mining.denylist import (
    CONTENT_FARMS,
    PHARMA_CORPORATE,
    Denial,
    brand_domain_slugs,
    deny_reason,
    partition,
)
from vsm.mining.discover import DiscoverClient, DiscoverResult
from vsm.mining.fake import DeterministicMiner
from vsm.mining.miner import LiveSignalMining, MiningConfig, MiningOutcome
from vsm.mining.queries import (
    PlannedQuery,
    expand_queries,
    gold_under_delivered,
    plan_queries,
)
from vsm.mining.recency import (
    DEFAULT_RECENCY_DAYS,
    RecencyWindow,
    google_tbs,
    parse_posted_at,
    supersession_flag,
    window_for,
)
from vsm.mining.robots import RobotsCache, RobotsState
from vsm.mining.serp import SerpClient, SerpResult
from vsm.mining.signals import build_row, dedupe_rows
from vsm.mining.tiers import (
    TIER_C_DOMAINS,
    TierCRefused,
    VenueTier,
    assert_collectable,
    domain_of,
    is_tier_c,
    tier_for,
)
from vsm.mining.unlocker import UnlockedPage, UnlockerClient
from vsm.mining.venues import (
    GOLD_DOMAINS,
    GOLD_VENUES,
    VERIFIED_AT,
    Venue,
    areas_for_cluster,
    areas_for_text,
    catalogue_entries,
    gold_page_fetch_allowed,
    is_gold,
    venue_for,
    venues_for,
)

__all__ = [
    "Budget",
    "FetchCall",
    "FREE_TIER_RESULTS_PER_MONTH",
    "SERP_COST_PER_REQUEST_USD",
    "DISCOVER_COST_PER_RESULT_USD",
    "UNLOCKER_COST_PER_SUCCESS_USD",
    "BrightDataClient",
    "BrightDataError",
    "BrightDataAuthError",
    "BrightDataRateLimited",
    "SerpClient",
    "SerpResult",
    "DiscoverClient",
    "DiscoverResult",
    "UnlockerClient",
    "UnlockedPage",
    "RobotsCache",
    "RobotsState",
    "TIER_C_DOMAINS",
    "TierCRefused",
    "VenueTier",
    "tier_for",
    "is_tier_c",
    "domain_of",
    "assert_collectable",
    "expand_queries",
    "plan_queries",
    "PlannedQuery",
    "gold_under_delivered",
    "build_row",
    "dedupe_rows",
    "LiveSignalMining",
    "MiningConfig",
    "MiningOutcome",
    # the gold list, the denylist and the recency window
    "Venue",
    "GOLD_VENUES",
    "GOLD_DOMAINS",
    "VERIFIED_AT",
    "venue_for",
    "venues_for",
    "is_gold",
    "gold_page_fetch_allowed",
    "areas_for_text",
    "areas_for_cluster",
    "catalogue_entries",
    "Denial",
    "deny_reason",
    "partition",
    "brand_domain_slugs",
    "PHARMA_CORPORATE",
    "CONTENT_FARMS",
    "RecencyWindow",
    "window_for",
    "google_tbs",
    "parse_posted_at",
    "supersession_flag",
    "DEFAULT_RECENCY_DAYS",
    "DeterministicMiner",
    "get_miner",
]


def _robots_fetch(url: str) -> str | None:
    """Fetch one robots.txt directly — it is public, and never through the
    Bright Data proxy. Returns ``None`` when it cannot be read;
    :class:`RobotsCache` treats that as *disallow*, because absence of
    evidence is not permission.
    """
    import httpx

    from vsm.mining.client import USER_AGENT

    try:
        with httpx.Client(timeout=15.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
            response = client.get(url)
    except Exception:  # noqa: BLE001 - unreachable robots.txt is not this call's failure
        return None
    return response.text if response.status_code == 200 else None


def get_miner(settings: Settings | None = None, *, band: Any = None) -> Any:
    """The deterministic fake offline, a configured :class:`LiveSignalMining` live.

    ``band`` (a :class:`vsm.topics.model.SpendBand`) decides the query volume
    *both* paths spend for this run — ``MiningConfig`` for the live miner via
    :func:`vsm.modes.mine.config_for`, ``queries_per_cluster`` for the fake —
    so a demonstration run at the deep band rehearses a deep-band live sweep,
    never a probe-band one wearing a deep label. Falls back to the cheapest
    band (``probe``) if none is given, so a bare ``get_miner(settings)`` still
    returns something usable.

    **Live with no Bright Data key raises, never falls back.** A run that
    quietly stopped collecting looks identical, from the outside, to one that
    collected — the same rule :func:`vsm.llm.client.get_client` holds for the
    model client, and softening it here would reopen exactly the failure this
    module's docstring on ``VSM_ENFORCE_TIER_C`` warns against: a decision
    that stops being visible.
    """
    # Deferred imports: vsm.topics.model and vsm.modes.mine both import
    # submodules of vsm.mining (SpendBand is unrelated; config_for imports
    # vsm.mining.miner.MiningConfig), so importing them at module scope here
    # risks a needless import-time cycle for no benefit — this function is
    # the only caller.
    from vsm.modes.mine import config_for
    from vsm.topics.model import BANDS

    s = settings or get_settings()
    chosen_band = band or BANDS["probe"]
    mode = s.effective_miner_mode()

    if mode == "fake":
        return DeterministicMiner(queries_per_cluster=chosen_band.queries_per_cluster)

    if not (s.brightdata_api_key or "").strip():
        raise ConfigError(
            "VSM_MINER=live but BRIGHTDATA_API_KEY is unset — export it, or run with "
            "VSM_OFFLINE=1 / VSM_MINER=fake to use the deterministic miner",
            rule="mining",
        )

    bright_data = BrightDataClient(s)
    return LiveSignalMining(
        serp=SerpClient(bright_data, zone=s.brightdata_serp_zone),
        discover=DiscoverClient(bright_data),
        unlocker=UnlockerClient(bright_data, zone=s.brightdata_unlocker_zone),
        robots=RobotsCache(fetch=_robots_fetch),
        catalogue=catalogue_entries(),
        config=config_for(chosen_band),
    )
