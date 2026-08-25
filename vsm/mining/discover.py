"""Bright Data **Discover API** — intent-ranked discovery.

Doc source: ``brightdata-plugin:discover-api`` (SKILL + ``references/api-reference.md``),
July 2026.

    POST https://api.brightdata.com/discover        → {"status": "ok", "task_id": "…"}
    GET  https://api.brightdata.com/discover?task_id=…
         → {"status": "processing", …} … then {"status": "done", "results": [...]}

Body: ``query`` (≤1500 chars, required), ``intent`` (≤3000, strongly recommended —
it is what does the ranking), ``num_results`` 1–20, ``include_content``,
``filter_keywords``, ``country``, ``language``, ``mode``
(``standard|deep|fast|zeroRanking``; REST-only).

Result row: ``{link, title, description, relevance_score, content?}``.

Two documented traps handled here:

* A job can come back ``done`` with empty ``results`` **transiently**. That is a
  retry-once condition, not a hard error; a persistent empty means the intent is
  too narrow (or Discover is not enabled — that surfaces as ``403``).
* A high ``relevance_score`` does not mean good content: block pages come back as
  ``content`` too. :func:`looks_blocked` gates them out.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from vsm.mining.client import BrightDataClient, BrightDataError
from vsm.mining.tiers import domain_of, tier_for

__all__ = ["DiscoverResult", "DiscoverClient", "looks_blocked", "BLOCK_SIGNATURES"]

#: Substrings that mean "you got the bot wall, not the page".
BLOCK_SIGNATURES: tuple[str, ...] = (
    "captcha",
    "just a moment",
    "access denied",
    "cf-browser-verification",
    "enable javascript and cookies to continue",
    "attention required! | cloudflare",
)


def looks_blocked(text: str | None) -> bool:
    """``True`` when this body is a block/interstitial page rather than content."""
    if not text:
        return False
    lowered = text[:4000].lower()
    return any(signature in lowered for signature in BLOCK_SIGNATURES)


@dataclass(frozen=True)
class DiscoverResult:
    """One intent-ranked hit. ``content`` is present only with ``include_content``."""

    link: str
    title: str = ""
    description: str = ""
    relevance_score: float | None = None
    content: str | None = None
    query: str = ""
    intent: str = ""
    #: D5: recorded on every result, not just the ones this parser lets through.
    #: By default a Tier-C link still comes back here, carrying ``tier="C"`` —
    #: ``VSM_ENFORCE_TIER_C=1`` restores the parent's stripping instead.
    tier: str = "B"

    @property
    def domain(self) -> str:
        return domain_of(self.link)


class DiscoverClient:
    """Intent discovery (collection mode 2, Tier B — PRD §5 stage 2)."""

    product = "discover"

    def __init__(
        self,
        client: BrightDataClient,
        *,
        poll_interval: float = 3.0,
        poll_budget: float = 180.0,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic,
        empty_retries: int = 1,
    ) -> None:
        self.client = client
        self.poll_interval = float(poll_interval)
        self.poll_budget = float(poll_budget)
        self._sleep = sleep
        self._now = now
        self.empty_retries = int(empty_retries)

    # --------------------------------------------------------------- discovery
    def discover(
        self,
        query: str,
        *,
        intent: str,
        num_results: int = 10,
        include_content: bool = True,
        country: str = "US",
        language: str = "en",
        mode: str = "standard",
        filter_keywords: Sequence[str] | None = None,
    ) -> list[DiscoverResult]:
        """Trigger a job, poll to ``done``, return the results.

        Tier is computed and attached to every result (spec D5); stripping is
        gated behind ``VSM_ENFORCE_TIER_C=1``. See :meth:`_rows`.
        """
        if not query.strip():
            return []
        attempts = self.empty_retries + 1
        for attempt in range(attempts):
            task_id = self.trigger(
                query,
                intent=intent,
                num_results=num_results,
                include_content=include_content,
                country=country,
                language=language,
                mode=mode,
                filter_keywords=filter_keywords,
            )
            rows = self.collect(task_id, query=query, intent=intent)
            if rows or attempt == attempts - 1:
                return rows
            self._sleep(self.poll_interval)  # short backoff, then one more go
        return []

    def trigger(
        self,
        query: str,
        *,
        intent: str,
        num_results: int = 10,
        include_content: bool = True,
        country: str = "US",
        language: str = "en",
        mode: str = "standard",
        filter_keywords: Sequence[str] | None = None,
    ) -> str:
        body: dict[str, Any] = {
            "query": query[:1500],
            "intent": intent[:3000],
            "num_results": max(1, min(int(num_results), 20)),  # documented 1–20
            "include_content": bool(include_content),
            "country": country,
            "language": language,
            "mode": mode,
        }
        if mode == "zeroRanking":  # documented: these two do not apply
            body.pop("num_results", None)
            body["include_content"] = False
        if filter_keywords:
            body["filter_keywords"] = list(filter_keywords)
        payload = BrightDataClient.json_of(self.client.request("POST", "/discover", json_body=body))
        task_id = str(payload.get("task_id") or "")
        if not task_id:
            raise BrightDataError(
                f"Discover trigger returned no task_id: {payload!r} — check that Discover is "
                "enabled on the account (403 when it is not)"
            )
        return task_id

    def collect(self, task_id: str, *, query: str = "", intent: str = "") -> list[DiscoverResult]:
        """Poll ``task_id`` until ``done``; never read ``results`` while processing."""
        deadline = self._now() + self.poll_budget
        while True:
            payload = BrightDataClient.json_of(
                self.client.request("GET", "/discover", params={"task_id": task_id})
            )
            status = str(payload.get("status") or "").lower()
            if status == "done":
                return self._rows(payload.get("results"), query=query, intent=intent)
            if status in ("failed", "error"):
                raise BrightDataError(f"Discover task {task_id} reported status={status!r}")
            if self._now() >= deadline:
                raise BrightDataError(
                    f"Discover task {task_id} still {status!r} after {self.poll_budget:.0f}s"
                )
            self._sleep(self.poll_interval)

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _rows(raw: Any, *, query: str, intent: str) -> list[DiscoverResult]:
        """Parse Discover's raw results. Tier is recorded, not gated (spec D5):
        a Tier-C link is returned like any other by default, carrying
        ``tier="C"``; a parser that silently shortened its own result list would
        leave nothing downstream able to tell "the venue said nothing" from "we
        deleted it". ``VSM_ENFORCE_TIER_C=1`` restores the parent's refusal —
        the link never reaches this list at all (PRD §9.1)."""
        if not isinstance(raw, list):
            return []
        enforce = os.environ.get("VSM_ENFORCE_TIER_C", "0") == "1"
        rows: list[DiscoverResult] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            link = str(item.get("link") or "")
            if not link:
                continue
            tier = tier_for(link)
            if tier == "C" and enforce:
                continue  # PRD §9.1 — refused before anything downstream sees it
            content = item.get("content")
            text = str(content) if isinstance(content, str) and content.strip() else None
            if looks_blocked(text):
                text = None  # a block page is not content; do not store it as one
            score = item.get("relevance_score")
            rows.append(
                DiscoverResult(
                    link=link,
                    title=str(item.get("title") or "").strip(),
                    description=str(item.get("description") or "").strip(),
                    relevance_score=float(score) if isinstance(score, (int, float)) else None,
                    content=text,
                    query=query,
                    intent=intent,
                    tier=tier,
                )
            )
        return rows
