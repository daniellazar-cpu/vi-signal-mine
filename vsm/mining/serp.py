"""Bright Data **SERP API** — query → organic results.

Doc source: ``brightdata-plugin:bright-data-best-practices`` → "SERP API"
(``references/serp-api.md``), July 2026.

    POST https://api.brightdata.com/request
    Authorization: Bearer <key>
    {"zone": "<serp zone>",
     "url":  "https://www.google.com/search?q=…&brd_json=1&gl=us&hl=en",
     "format": "raw"}

``brd_json=1`` is what makes the response parsed JSON rather than HTML — always
on here, because a data pipeline that parses SERP HTML itself is a liability.
``num`` is deprecated (Sept 2025); pagination is ``start=10/20/…``.

Response (parsed): ``{"organic": [{"rank", "title", "link", "description"}, …],
"paid": [], "people_also_ask": [], "general": {…}}``.

Billing: per 1,000 **successful** requests.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Sequence
from urllib.parse import urlencode

from vsm.mining.client import BrightDataClient, BrightDataError
from vsm.mining.recency import parse_posted_at
from vsm.mining.tiers import domain_of, tier_for

__all__ = ["SerpResult", "SerpClient", "GOOGLE_SEARCH_URL"]

GOOGLE_SEARCH_URL = "https://www.google.com/search"


@dataclass(frozen=True)
class SerpResult:
    """One organic result. ``description`` is Google's snippet, not page text."""

    rank: int
    title: str
    link: str
    description: str = ""
    query: str = ""
    #: whatever the payload put in ``date`` — an *absolute* date only, normalised to
    #: ISO by :func:`vsm.mining.recency.parse_posted_at`; ``None`` when the venue
    #: exposed nothing parseable. A relative "3 days ago" is refused, because
    #: resolving it would be our arithmetic presented as the venue's fact (PRD §5.3).
    posted_at: str | None = None
    #: D5: recorded on every result, not just the ones this parser lets through.
    #: By default a Tier-C link still comes back here, carrying ``tier="C"`` —
    #: ``VSM_ENFORCE_TIER_C=1`` restores the parent's stripping instead.
    tier: str = "B"

    @property
    def domain(self) -> str:
        return domain_of(self.link)


class SerpClient:
    """Keyword SERP sweep (collection mode 1, Tier B — PRD §5 stage 2)."""

    product = "serp"

    def __init__(
        self,
        client: BrightDataClient,
        *,
        zone: str,
        country: str = "us",
        language: str = "en",
    ) -> None:
        self.client = client
        self.zone = zone
        self.country = country
        self.language = language

    # ------------------------------------------------------------------ search
    def search_url(self, query: str, *, start: int = 0, tbs: str = "") -> str:
        """The Google URL for one query.

        ``tbs`` carries the recency window as an **exact** custom range
        (``cdr:1,cd_min:…,cd_max:…`` — see :mod:`vsm.mining.recency`) rather than
        ``qdr:m``. An approximate window cannot be reconciled against a provenance
        record, and this URL is what lands in that record.
        """
        params = {
            "q": query,
            "brd_json": "1",
            "gl": self.country,
            "hl": self.language,
        }
        if start:
            params["start"] = str(start)
        if tbs:
            params["tbs"] = tbs
        return f"{GOOGLE_SEARCH_URL}?{urlencode(params)}"

    def search(
        self, query: str, *, limit: int = 10, start: int = 0, tbs: str = ""
    ) -> list[SerpResult]:
        """Run one SERP request and return the organic results.

        Tier is computed and attached to every result (spec D5): by default a
        Tier-C link comes back like any other, carrying ``tier="C"`` so nothing
        downstream can mistake "the venue said nothing" for "we deleted it".
        ``VSM_ENFORCE_TIER_C=1`` restores the parent's stripping — a Tier-C
        result never handed out at all (PRD §9.1) — for this parser and the
        run layer alike.
        """
        enforce = os.environ.get("VSM_ENFORCE_TIER_C", "0") == "1"
        response = self.client.request(
            "POST",
            "/request",
            json_body={
                "zone": self.zone,
                "url": self.search_url(query, start=start, tbs=tbs),
                "format": "raw",
            },
        )
        payload = self._payload(response)
        organic = payload.get("organic")
        if not isinstance(organic, list):
            return []
        results: list[SerpResult] = []
        for item in organic:
            if not isinstance(item, dict):
                continue
            link = str(item.get("link") or "")
            if not link:
                continue
            tier = tier_for(link)
            if tier == "C" and enforce:
                continue
            results.append(
                SerpResult(
                    rank=int(item.get("rank") or item.get("global_rank") or len(results) + 1),
                    title=str(item.get("title") or "").strip(),
                    link=link,
                    description=str(item.get("description") or item.get("snippet") or "").strip(),
                    query=query,
                    posted_at=parse_posted_at(item.get("date") or item.get("published")),
                    tier=tier,
                )
            )
            if len(results) >= limit:
                break
        return results

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _payload(response: Any) -> dict[str, Any]:
        try:
            return BrightDataClient.json_of(response)
        except BrightDataError:
            # ``format: raw`` without ``brd_json`` yields HTML; that is a wiring
            # bug, not a transient one — say so instead of parsing HTML.
            raise BrightDataError(
                "SERP response was not parsed JSON — the request URL must carry brd_json=1",
                status=getattr(response, "status_code", None),
            ) from None

    def search_many(self, queries: Sequence[str], *, limit: int = 10) -> dict[str, list[SerpResult]]:
        return {q: self.search(q, limit=limit) for q in queries}
