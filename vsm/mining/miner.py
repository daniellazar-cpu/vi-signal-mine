"""The Stage-2 run layer: clusters in, normalised signal rows out.

Order of operations, and why each step is where it is:

1. **Plan** each cluster into a gold-list query plan with the *same* planner the
   offline miner uses (:func:`vsm.mining.queries.plan_queries`), so an offline
   dry run rehearses the live sweep exactly — same queries, same order.
2. **Gold-list SERP first** (Tier B) — ``site:``-scoped queries against the venues
   :mod:`vsm.mining.venues` says are strong for this cluster's therapeutic
   areas. This is where the budget is meant to go. The first live sweep was an open
   Google search and spent two of eighteen rows on a university repository and a
   pay-to-publish journal.
3. **Intent discovery** (Tier B) — one Discover job per cluster, ranked by an
   intent built from the cluster label, with parsed content.
4. **Open web last, and only if the gold list under-delivers** — capped, and with
   the denylist applied to every result *before* any page fetch.
5. **Tier gate before anything else touches a URL.** A Tier-C domain is dropped
   here *and* refused inside every client, and is recorded as
   *restricted → human-read only*. It is never fetched, not once, not partially.
6. **The denylist** (:mod:`vsm.mining.denylist`) drops what is not worth paying
   for — brand and pharma-corporate sites, content farms, pay-to-publish
   publishers, repository duplicates. Every drop is recorded with its reason; a
   silent filter is indistinguishable from finding nothing.
7. **Page fetch via Web Unlocker only against a gold-list host** whose tier is A/B,
   whose venue entry permits a body fetch, and whose robots.txt allows the path. An
   unclassified host contributes public search-result metadata and nothing else.
   A SERP request is ``SERP_COST_PER_REQUEST_USD`` ($0.0015) and a successful page
   fetch is ``UNLOCKER_COST_PER_SUCCESS_USD`` — 2× at the PRD §13.1 verified price
   of $3/1,000, and 20× at the $30/1,000 the owner quoted. The ratio is disputed;
   the direction is not, and the direction is the whole cost argument for having a
   gold list. Both constants live in :mod:`vsm.mining.budget`.
8. **Recency by venue kind, never as a blanket filter**
   (:mod:`vsm.mining.recency`). Discussion and community venues carry an exact
   90-day-plus window on the SERP URL; evidence, guideline, regulatory and
   drug-reference venues are not date-filtered, because for those the test is
   current edition, not recent date.
9. **Normalise → dedupe.** Patient-generated venues come out as themes only.
10. **Budget on every step.** Results are counted against the Bright Data free
    tier (5,000/month) and, when one is injected, the runner's quota ledger under
    ``account="brightdata"``. A breach stops the sweep *cleanly* — partial rows,
    a recorded deferral, no overspend, no exception thrown at the pipeline.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from vsm.mining.budget import (
    DISCOVER_COST_PER_RESULT_USD,
    FREE_TIER_RESULTS_PER_MONTH,
    SERP_COST_PER_REQUEST_USD,
    UNLOCKER_COST_PER_SUCCESS_USD,
    Budget,
    BudgetStop,
    FetchCall,
)
from vsm.mining.client import BRIGHTDATA_BASE_URL, BrightDataError
from vsm.mining.denylist import Denial, brand_domain_slugs, partition
from vsm.mining.discover import DiscoverClient, DiscoverResult
from vsm.mining.queries import (
    GOLD_SITES_PER_QUERY,
    MIN_GOLD_ROWS,
    OPEN_QUERIES_MAX,
    PlannedQuery,
    gold_under_delivered,
    intent_for,
    plan_queries,
)
from vsm.mining.recency import (
    DEFAULT_RECENCY_DAYS,
    RecencyWindow,
    supersession_flag,
    window_for,
)
from vsm.mining.robots import RobotsCache
from vsm.mining.serp import SerpClient, SerpResult
from vsm.mining.signals import Hit, build_row, dedupe_rows, tos_basis_for
from vsm.mining.tiers import (
    TierCRefused,
    catalogue_by_domain,
    domain_of,
    is_patient_generated,
    is_tier_c,
    page_fetch_allowed,
    tier_for,
)
from vsm.mining.unlocker import UnlockerClient
from vsm.mining.venues import (
    EVERGREEN_KINDS,
    areas_for_cluster,
    gold_page_fetch_allowed,
    is_gold,
    kind_of,
)

__all__ = ["MiningConfig", "MiningOutcome", "LiveSignalMining"]

_DISCOVER_ENDPOINT = f"{BRIGHTDATA_BASE_URL}/discover"


@dataclass(frozen=True)
class MiningConfig:
    """Sweep shape. Defaults sit inside the PRD §13.1 per-campaign envelope."""

    queries_per_cluster: int = 4
    serp_results_per_query: int = 10
    discover_results_per_cluster: int = 10
    discover_mode: str = "standard"
    include_content: bool = True
    fetch_pages: bool = True
    #: at most this many Web Unlocker page fetches per cluster (cost control)
    page_fetches_per_cluster: int = 3
    result_cap: int = FREE_TIER_RESULTS_PER_MONTH
    country: str = "us"
    language: str = "en"
    # ------------------------------------------------------------- gold list
    #: ``site:`` tokens per gold query — one request, several venues
    gold_sites_per_query: int = GOLD_SITES_PER_QUERY
    #: spend on the open web only when the gold list came back this thin
    min_gold_rows: int = MIN_GOLD_ROWS
    #: hard cap on the conditional open-web tail
    open_queries_max: int = OPEN_QUERIES_MAX
    open_search_fallback: bool = True
    # -------------------------------------------------------------- recency
    #: 90 is the floor the owner named, not a ceiling — widen freely
    recency_days: int = DEFAULT_RECENCY_DAYS
    apply_recency: bool = True
    #: when a date-restricted query returns nothing, re-ask once without the window
    #: so "the filter excluded everything" cannot be mistaken for "the venue is
    #: empty". Costs one extra SERP call ($0.0015), capped per cluster.
    probe_outside_window: bool = True
    probes_per_cluster: int = 2


@dataclass
class MiningOutcome:
    """Everything one live sweep produced, including what it refused and why."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    queries_run: list[str] = field(default_factory=list)
    venues_attempted: list[str] = field(default_factory=list)
    venues_collected: list[str] = field(default_factory=list)
    venues_restricted: list[str] = field(default_factory=list)
    provider: str = "brightdata"
    cost_usd: float = 0.0
    calls: list[dict[str, Any]] = field(default_factory=list)
    deferrals: list[dict[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    #: what the denylist dropped, and why — never silent
    denied: list[dict[str, str]] = field(default_factory=list)
    #: the plan, as planned (both miners can rebuild this and must agree)
    plan: list[dict[str, Any]] = field(default_factory=list)
    #: D5: per-host tier + robots answer, recorded even when (default) neither
    #: vetoed a fetch — this is what later lands in coverage.json. "recorded per
    #: host in coverage — reporting, not gating" (spec D5, design §2).
    coverage: list[dict[str, Any]] = field(default_factory=list)


class LiveSignalMining:
    """Runs the sweep. Holds no credentials of its own — the clients do."""

    def __init__(
        self,
        *,
        serp: SerpClient | None,
        discover: DiscoverClient | None = None,
        unlocker: UnlockerClient | None = None,
        robots: RobotsCache | None = None,
        catalogue: Sequence[Mapping[str, Any]] = (),
        config: MiningConfig | None = None,
        quota: Any = None,
        clock: Callable[[], datetime] | None = None,
        query_for: Callable[[Mapping[str, Any], int], str] | None = None,
        brand_terms: Mapping[str, str] | None = None,
    ) -> None:
        self.serp = serp
        self.discover = discover
        self.unlocker = unlocker
        self.robots = robots
        self.catalogue = list(catalogue)
        self.config = config or MiningConfig()
        self.quota = quota
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.query_for = query_for
        self.brand_terms = dict(brand_terms or {})
        #: brand/competitor product domains, derived from the never-say list
        self.brand_slugs = brand_domain_slugs(self.brand_terms)

    # ------------------------------------------------------------------- entry
    def run(
        self,
        *,
        campaign_id: str,
        clusters: Sequence[Mapping[str, Any]],
        queries_per_cluster: int | None = None,
    ) -> MiningOutcome:
        cfg = self.config
        per_cluster = int(queries_per_cluster or cfg.queries_per_cluster)
        budget = Budget(
            campaign_id=campaign_id, result_cap=cfg.result_cap, ledger=self.quota, account="brightdata"
        )
        outcome = MiningOutcome()
        window = window_for(self.clock(), cfg.recency_days)
        index = catalogue_by_domain(self.catalogue)
        restricted: set[str] = {
            domain_of(str(entry.get("domain") or ""))
            for entry in self.catalogue
            if str(entry.get("collection_tier")) == "C"
        }
        restricted.discard("")
        attempted: set[str] = set(restricted)
        rows: list[dict[str, Any]] = []
        denied: list[Denial] = []
        targeting: list[dict[str, Any]] = []
        recency_queries: list[dict[str, Any]] = []
        probes: list[dict[str, Any]] = []
        superseded: list[dict[str, str]] = []
        metadata_only: set[str] = set()
        ran = {"gold": 0, "open": 0}

        try:
            for cluster in clusters:
                areas = areas_for_cluster(cluster)
                plan = plan_queries(
                    cluster,
                    per_cluster,
                    query_for=self.query_for,
                    areas=areas,
                    sites_per_query=cfg.gold_sites_per_query,
                    open_queries_max=cfg.open_queries_max,
                )
                outcome.plan.extend(p.as_dict() for p in plan)
                gold = [p for p in plan if p.kind == "gold"]
                tail = [p for p in plan if p.kind == "open"]
                targeting.append(
                    {
                        "cluster_id": cluster.get("cluster_id"),
                        "areas": list(areas),
                        "gold_venues": sorted({d for p in gold for d in p.venues}),
                        "gold_queries": len(gold),
                        "open_queries_available": len(tail),
                    }
                )
                # rows are built per batch, so a mid-sweep stop keeps everything
                # already paid for instead of discarding it
                state = {"fetched": 0, "probes": 0}
                gold_rows = 0
                for planned in gold:
                    outcome.queries_run.append(planned.text)
                    ran["gold"] += 1
                    batch = self._planned_hits(
                        planned,
                        budget=budget,
                        outcome=outcome,
                        window=window,
                        state=state,
                        recency_queries=recency_queries,
                        probes=probes,
                    )
                    new = self._rows_for(
                        batch,
                        cluster=cluster,
                        campaign_id=campaign_id,
                        budget=budget,
                        outcome=outcome,
                        index=index,
                        attempted=attempted,
                        restricted=restricted,
                        state=state,
                        denied=denied,
                        superseded=superseded,
                        metadata_only=metadata_only,
                    )
                    gold_rows += len(new)
                    rows.extend(new)
                rows.extend(
                    self._rows_for(
                        self._discover_hits(cluster, plan, budget=budget, outcome=outcome),
                        cluster=cluster,
                        campaign_id=campaign_id,
                        budget=budget,
                        outcome=outcome,
                        index=index,
                        attempted=attempted,
                        restricted=restricted,
                        state=state,
                        denied=denied,
                        superseded=superseded,
                        metadata_only=metadata_only,
                    )
                )
                # ---------------------------------------------- the open-web tail
                thin = gold_under_delivered(gold_rows, minimum=cfg.min_gold_rows)
                if not tail or not cfg.open_search_fallback:
                    pass
                elif not thin:
                    outcome.notes.append(
                        f"gold list delivered {gold_rows} rows for cluster "
                        f"{cluster.get('cluster_id')} — the {len(tail)} open-web quer"
                        f"{'y' if len(tail) == 1 else 'ies'} in the plan were not run "
                        f"(${SERP_COST_PER_REQUEST_USD * len(tail):.4f} unspent)"
                    )
                else:
                    outcome.notes.append(
                        f"gold list under-delivered ({gold_rows} rows < {cfg.min_gold_rows}) for "
                        f"cluster {cluster.get('cluster_id')} — running {len(tail)} open-web "
                        "quer" + ("y" if len(tail) == 1 else "ies") + ", denylist applied before "
                        "any page fetch"
                    )
                    for planned in tail:
                        outcome.queries_run.append(planned.text)
                        ran["open"] += 1
                        batch = self._planned_hits(
                            planned,
                            budget=budget,
                            outcome=outcome,
                            window=window,
                            state=state,
                            recency_queries=recency_queries,
                            probes=probes,
                        )
                        rows.extend(
                            self._rows_for(
                                batch,
                                cluster=cluster,
                                campaign_id=campaign_id,
                                budget=budget,
                                outcome=outcome,
                                index=index,
                                attempted=attempted,
                                restricted=restricted,
                                state=state,
                                denied=denied,
                                superseded=superseded,
                                metadata_only=metadata_only,
                            )
                        )
        except BudgetStop as stop:
            budget.stop(stop.reason)
            outcome.deferrals.append(
                {
                    "needs": "the remainder of the Bright Data sweep",
                    "reason": stop.reason,
                    "substitute": "partial sweep — the rows collected before the cap, all with provenance",
                }
            )
            outcome.notes.append(f"sweep stopped early: {stop.reason}")

        outcome.rows = dedupe_rows(rows)
        collected = sorted({str(r["venue"]) for r in outcome.rows if r.get("venue")})
        outcome.venues_collected = collected
        outcome.venues_restricted = sorted(restricted)
        outcome.venues_attempted = sorted(attempted | set(collected))
        outcome.cost_usd = round(budget.cost_usd, 6)
        outcome.calls = [c.as_dict() for c in budget.calls]
        outcome.denied = [d.as_dict() for d in denied]
        outcome.provenance = budget.as_provenance()
        if self.robots is not None:
            outcome.provenance["robots"] = self.robots.as_provenance()
        outcome.provenance["tier_c_refused"] = outcome.venues_restricted
        outcome.provenance["targeting"] = {
            "strategy": (
                "gold-list site:-scoped SERP first; intent discovery; open web only when the gold "
                "list under-delivers. Web Unlocker page fetches only against gold-list hosts — an "
                "unclassified host contributes search-result metadata and is never page-fetched"
            ),
            "per_cluster": targeting,
            "metadata_only_hosts": sorted(metadata_only),
            "gold_queries_planned": sum(1 for q in outcome.plan if q["kind"] == "gold"),
            "gold_queries_run": ran["gold"],
            "open_queries_planned": sum(1 for q in outcome.plan if q["kind"] == "open"),
            "open_queries_run": ran["open"],
        }
        outcome.provenance["denylist"] = {
            "dropped": outcome.denied,
            "dropped_count": len(outcome.denied),
            "rule": (
                "not a compliance blocklist (that is tier C) — these are hosts not worth paying "
                "for: sponsor/competitor product sites, pharma corporate marketing, content farms, "
                "pay-to-publish publishers, repository duplicates, non-clinical noise"
            ),
        }
        recency = window.as_dict() if cfg.apply_recency else {
            "window_days": None,
            "rule": "recency filtering disabled for this run",
        }
        recency["queries"] = recency_queries
        recency["zero_result_probes"] = probes
        recency["applied"] = bool(cfg.apply_recency)
        outcome.provenance["recency"] = recency
        if superseded:
            outcome.provenance["superseded_flags"] = superseded
        outcome.provenance["plan"] = outcome.plan
        return outcome

    # ------------------------------------------------------------------- steps
    def _rows_for(
        self,
        hits: Sequence[Hit],
        *,
        cluster: Mapping[str, Any],
        campaign_id: str,
        budget: Budget,
        outcome: MiningOutcome,
        index: Mapping[str, Mapping[str, Any]],
        attempted: set[str],
        restricted: set[str],
        state: dict[str, int],
        denied: list[Denial],
        superseded: list[dict[str, str]],
        metadata_only: set[str],
    ) -> list[dict[str, Any]]:
        """Tier-gate, deny-list, optionally page-fetch, and normalise one batch."""
        cfg = self.config
        rows: list[dict[str, Any]] = []
        for hit in hits:
            domain = hit.domain
            if not domain:
                continue
            attempted.add(domain)
            if is_tier_c(hit.url, catalogue=self.catalogue):
                # never fetched, never a row — human-read only (PRD §9.1)
                restricted.add(domain)
                continue
            # the budget rule, applied after the compliance rule and before any spend
            kept, dropped = partition([hit], url_of=lambda h: h.url, brand_slugs=self.brand_slugs)
            if dropped:
                denied.extend(dropped)
                continue
            entry = index.get(domain)
            hit.collection_tier = tier_for(hit.url, catalogue=self.catalogue)
            hit.distribution_mode = (entry or {}).get("distribution_mode")
            hit.patient_generated = is_patient_generated(hit.url, catalogue=self.catalogue)

            robots_summary = ""
            gold_host = is_gold(hit.url)
            if not gold_host:
                metadata_only.add(domain)
            if (
                cfg.fetch_pages
                and self.unlocker is not None
                and state["fetched"] < cfg.page_fetches_per_cluster
                # the twentyfold rule: only a curated host is worth $0.03
                and gold_page_fetch_allowed(hit.url)
                and page_fetch_allowed(hit.url, catalogue=self.catalogue)
                and not hit.content
            ):
                page, robots_summary = self._fetch_page(hit, budget=budget, outcome=outcome)
                if page is not None:
                    state["fetched"] += 1
                    hit.content = page.text
                    hit.collection_method = (
                        "api" if bool((entry or {}).get("api_available")) else "public_web_fetch"
                    )
            if hit.content and kind_of(hit.url) in EVERGREEN_KINDS:
                # evidence and guidelines are never dropped for age; a page that says
                # it has been replaced is flagged so a human checks the edition
                flag = supersession_flag(hit.content, title=hit.title)
                if flag:
                    superseded.append({"url": hit.url, "venue": domain, "flag": flag})
                    outcome.notes.append(f"{domain}: {flag}")
            hit.tos_basis = tos_basis_for(
                venue_entry=entry,
                robots_summary=robots_summary,
                method=hit.collection_method,
                checked_at=self.clock(),
            )
            rows.append(
                build_row(
                    campaign_id=campaign_id,
                    cluster=cluster,
                    hit=hit,
                    captured_at=self.clock(),
                    brand_terms=self.brand_terms,
                )
            )
        return rows

    def _planned_hits(
        self,
        planned: PlannedQuery,
        *,
        budget: Budget,
        outcome: MiningOutcome,
        window: RecencyWindow,
        state: dict[str, int],
        recency_queries: list[dict[str, Any]],
        probes: list[dict[str, Any]],
    ) -> list[Hit]:
        """One planned SERP query, with the recency window where it belongs."""
        cfg = self.config
        restrict = bool(planned.date_restricted and cfg.apply_recency)
        hits = self._serp_hits(planned.text, budget=budget, outcome=outcome, tbs=window.tbs if restrict else "")
        recency_queries.append(
            {
                "query": planned.text,
                "kind": planned.kind,
                "venues": list(planned.venues),
                "venue_kinds": list(planned.venue_kinds),
                "date_restricted": restrict,
                "results": len(hits),
                "why": (
                    f"discussion/community venues — restricted to the {window.days}-day window"
                    if restrict
                    else "evidence, guideline, regulatory or open-web query — not date-filtered; "
                    "the test is current edition, not recent date"
                ),
            }
        )
        if (
            restrict
            and not hits
            and cfg.probe_outside_window
            and state["probes"] < cfg.probes_per_cluster
        ):
            state["probes"] += 1
            outside = self._serp_hits(planned.text, budget=budget, outcome=outcome, tbs="", probe=True)
            finding = (
                f"{len(outside)} results exist outside the {window.days}-day window — the window "
                "excluded them, the venue is not empty"
                if outside
                else "nothing with or without the window — the venue had nothing on this question"
            )
            probes.append(
                {
                    "query": planned.text,
                    "venues": list(planned.venues),
                    "results_in_window": 0,
                    "results_without_window": len(outside),
                    "finding": finding,
                    "collected": False,
                }
            )
            outcome.notes.append(f"recency probe — {planned.text}: {finding}")
            # deliberately NOT turned into rows: they are outside the window the run
            # declared. The count is the finding; the content is not admissible here.
        return hits

    def _serp_hits(
        self,
        query: str,
        *,
        budget: Budget,
        outcome: MiningOutcome,
        tbs: str = "",
        probe: bool = False,
    ) -> list[Hit]:
        if self.serp is None:
            return []
        limit = self.config.serp_results_per_query
        budget.check(limit, what=f"SERP query {query!r}")
        at = self.clock()
        url = self.serp.search_url(query, tbs=tbs)
        try:
            results: list[SerpResult] = self.serp.search(query, limit=limit, tbs=tbs)
        except BrightDataError as exc:
            budget.record(
                FetchCall(kind="serp", target=query, url=url, at=at, status="error", results=0,
                          cost_usd=0.0, billable=False, detail=str(exc)[:200],
                          reason=f"{type(exc).__name__}: {exc}"[:300],
                          http_status=getattr(exc, "status", None))
            )
            outcome.notes.append(f"SERP failed for {query!r}: {exc}")
            # an error is not a null result: say what is missing, so nobody reads the
            # row count as "the web had nothing"
            outcome.deferrals.append(
                {
                    "needs": f"SERP results for {query!r}",
                    "reason": f"{type(exc).__name__}: {exc}"[:300],
                    "substitute": "none — this query contributed no rows to the sweep",
                }
            )
            return []
        budget.record(
            FetchCall(
                kind="serp", target=query, url=url, at=at, status="ok", results=len(results),
                cost_usd=SERP_COST_PER_REQUEST_USD, billable=True,
                detail="zero-result recency probe — counted, not collected" if probe else "",
            )
        )
        return [
            Hit(
                url=r.link,
                title=r.title,
                description=r.description,
                collection_method="serp_result",
                query=query,
                posted_at=r.posted_at,
            )
            for r in results
        ]

    def _discover_hits(
        self,
        cluster: Mapping[str, Any],
        plan: Sequence[PlannedQuery],
        *,
        budget: Budget,
        outcome: MiningOutcome,
    ) -> list[Hit]:
        if self.discover is None or not plan:
            return []
        cfg = self.config
        query = str(cluster.get("label") or plan[0].base)
        intent = intent_for(cluster)
        budget.check(cfg.discover_results_per_cluster, what=f"Discover job {query!r}")
        at = self.clock()
        try:
            results: list[DiscoverResult] = self.discover.discover(
                query,
                intent=intent,
                num_results=cfg.discover_results_per_cluster,
                include_content=cfg.include_content,
                country=cfg.country.upper(),
                language=cfg.language,
                mode=cfg.discover_mode,
            )
        except BrightDataError as exc:
            budget.record(
                FetchCall(kind="discover", target=query, url=_DISCOVER_ENDPOINT, at=at,
                          status="error", results=0, cost_usd=0.0, billable=False,
                          detail=str(exc)[:200], reason=f"{type(exc).__name__}: {exc}"[:300],
                          http_status=getattr(exc, "status", None))
            )
            outcome.notes.append(f"Discover failed for {query!r}: {exc}")
            outcome.deferrals.append(
                {
                    "needs": f"intent-ranked discovery for {query!r}",
                    "reason": f"{type(exc).__name__}: {exc}"[:300],
                    "substitute": "none — this cluster has SERP coverage only",
                }
            )
            return []
        budget.record(
            FetchCall(
                kind="discover", target=query, url=_DISCOVER_ENDPOINT, at=at, status="ok",
                results=len(results), cost_usd=DISCOVER_COST_PER_RESULT_USD * len(results),
                billable=True, estimated=True,
                detail="per-result price estimated from PRD §13.1 parsed-page line",
            )
        )
        return [
            Hit(
                url=r.link,
                title=r.title,
                description=r.description,
                content=r.content,
                relevance_score=r.relevance_score,
                collection_method="discover",
                query=query,
            )
            for r in results
        ]

    def _fetch_page(self, hit: Hit, *, budget: Budget, outcome: MiningOutcome) -> tuple[Any, str]:
        """Web Unlocker fetch. Tier and robots are recorded (spec D5), not gated,
        unless ``VSM_ENFORCE_TIER_C=1`` restores the parent's refusal.

        Returns ``(page | None, robots summary)``.
        """
        assert self.unlocker is not None
        enforce = os.environ.get("VSM_ENFORCE_TIER_C", "0") == "1"
        robots_ok = True
        summary = "robots.txt not consulted (no cache injected)"
        if self.robots is not None:
            state = self.robots.state_for(hit.url)
            robots_ok = state.allows(hit.url, self.robots.user_agent)
            summary = state.summary()
            if not robots_ok:
                # D5: recorded per host in coverage — reporting, not gating.
                # Nothing here may be silently dropped, in either branch below.
                outcome.coverage.append(
                    {
                        "domain": hit.domain,
                        "tier": hit.collection_tier,
                        "robots_ok": False,
                        "robots_summary": summary,
                        "enforced": enforce,
                    }
                )
                if enforce:
                    outcome.notes.append(
                        f"{hit.domain}: robots.txt disallows this path — page not fetched, "
                        "search-result metadata only"
                    )
                    return None, f"{summary}; Disallow for this path — page not fetched"
                outcome.notes.append(
                    f"{hit.domain}: robots.txt disallows this path — fetched anyway (spec D5: "
                    "recorded in coverage, not gated; VSM_ENFORCE_TIER_C=1 restores the refusal)"
                )
        budget.check(1, what=f"page fetch {hit.domain}")
        at = self.clock()
        try:
            page = self.unlocker.fetch(hit.url, robots_ok=robots_ok, catalogue=self.catalogue)
        except TierCRefused:
            raise
        except BrightDataError as exc:
            # failures are not billed in Web Unlocker standard mode. This is the
            # branch that produced the one bare `status: "error"` in the first live
            # sweep — it now records the reason and the HTTP status, and counts as
            # possible data loss rather than as an empty page.
            budget.record(
                FetchCall(kind="unlocker", target=hit.url, url=hit.url, at=at, status="error",
                          results=0, cost_usd=0.0, billable=False, detail=str(exc)[:200],
                          reason=f"{type(exc).__name__}: {exc}"[:300],
                          http_status=getattr(exc, "status", None))
            )
            outcome.notes.append(f"page fetch failed for {hit.url}: {exc}")
            outcome.deferrals.append(
                {
                    "needs": f"page body for {hit.url}",
                    "reason": f"{type(exc).__name__}: {exc}"[:300],
                    "substitute": "search-result metadata only for this row — no excerpt",
                }
            )
            return None, summary
        if not page.usable:
            # expected, and not data loss: the venue defeated the unlocker, so there
            # was never a body to lose. Recorded, unbilled, and the sweep continues.
            budget.record(
                FetchCall(kind="unlocker", target=hit.url, url=hit.url, at=at, status="blocked",
                          results=0, cost_usd=0.0, billable=False,
                          detail="block page or empty body",
                          reason="the venue returned a block/interstitial page or an empty body — "
                                 "expected against a protected host; no page body existed to keep")
            )
            outcome.notes.append(f"page fetch for {hit.url} returned a block page — dropped")
            return None, summary
        budget.record(
            FetchCall(kind="unlocker", target=hit.url, url=hit.url, at=at, status="ok", results=1,
                      cost_usd=UNLOCKER_COST_PER_SUCCESS_USD, billable=True)
        )
        return page, summary
