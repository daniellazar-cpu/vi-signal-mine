"""Bright Data **Web Unlocker** — fetch one public page that blocks a plain GET.

Doc source: ``brightdata-plugin:bright-data-best-practices`` → "Web Unlocker API"
(``references/web-unlocker.md``), July 2026.

    POST https://api.brightdata.com/request
    Authorization: Bearer <key>
    {"zone": "<unlocker zone>", "url": "…", "format": "raw",
     "data_format": "markdown"}   # markdown is the best LLM/ledger input

Documented error codes: ``400`` (missing ``zone``/``url``/``format``), ``401``.
Billing: per 1,000 **successful** responses; failures are not billed in standard
mode — so a failed fetch here records ``billable=False`` upstream.

What this client will not do (PRD §9.1 "explicitly not built"): no anti-detect
browser, no proxy rotation to evade enforcement, no paywall bypass. Tier and
robots-allowed are always recorded on the returned page (spec D5): by default
neither vetoes the fetch, and ``VSM_ENFORCE_TIER_C=1`` restores the parent's
refusal of a Tier-C domain or a robots.txt ``Disallow``. The caller must still
pass ``robots_ok``, which :class:`~vsm.mining.robots.RobotsCache` decides — that
requirement survives D5, because the answer is still wanted, it just no longer
gates by default.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from vsm.mining.client import BrightDataClient, BrightDataError
from vsm.mining.discover import looks_blocked
from vsm.mining.tiers import assert_collectable, domain_of

__all__ = ["UnlockedPage", "UnlockerClient"]


@dataclass(frozen=True)
class UnlockedPage:
    """One fetched public page."""

    url: str
    text: str
    fetched_at: datetime
    status: int = 200
    data_format: str = "markdown"
    #: D5: the tier this host classified at, and whether robots.txt allowed this
    #: path — always recorded, even in the (default) case where neither vetoed
    #: the fetch. ``VSM_ENFORCE_TIER_C=1`` restores the parent's refusal instead
    #: of reaching this far.
    tier: str = "B"
    robots_ok: bool = True

    @property
    def domain(self) -> str:
        return domain_of(self.url)

    @property
    def usable(self) -> bool:
        return bool(self.text.strip()) and not looks_blocked(self.text)


class UnlockerClient:
    """Page fetch (collection mode 4, Tier B only — PRD §5 stage 2 / §9.1)."""

    product = "unlocker"

    def __init__(
        self,
        client: BrightDataClient,
        *,
        zone: str,
        country: str = "us",
        data_format: str = "markdown",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.client = client
        self.zone = zone
        self.country = country
        self.data_format = data_format
        self._now = now or (lambda: datetime.now(timezone.utc))

    def fetch(self, url: str, *, robots_ok: bool, catalogue: Any = None) -> UnlockedPage:
        """Fetch ``url``. Tier and robots are recorded, not gated, by default
        (spec D5) — ``VSM_ENFORCE_TIER_C=1`` restores the parent's refusal of a
        Tier-C domain or a robots.txt ``Disallow``.

        ``robots_ok`` is a required keyword rather than a default so that a caller
        cannot fetch a page without having formed an opinion about robots.txt —
        that requirement survives D5 unchanged: we still want the answer, we just
        no longer let it veto by default.

        ``catalogue`` is forwarded to :func:`~vsm.mining.tiers.assert_collectable`
        unchanged — D5 only changed that function's *raise* behaviour, not its
        contract; a per-campaign venue catalogue can still promote a host's tier.
        """
        record = assert_collectable(url, catalogue=catalogue)
        enforce = os.environ.get("VSM_ENFORCE_TIER_C", "0") == "1"
        if not robots_ok and enforce:
            raise BrightDataError(
                f"refused {domain_of(url)} — robots.txt disallows this path for our agent; "
                "a Disallow moves the venue to Tier C for this campaign (PRD §9.1)"
            )
        response = self.client.request(
            "POST",
            "/request",
            json_body={
                "zone": self.zone,
                "url": url,
                "format": "raw",
                "data_format": self.data_format,
                "country": self.country,
            },
        )
        return UnlockedPage(
            url=url,
            text=response.text or "",
            fetched_at=self._now(),
            status=response.status_code,
            data_format=self.data_format,
            tier=record["tier"],
            robots_ok=robots_ok,
        )
