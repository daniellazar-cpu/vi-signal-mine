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
browser, no proxy rotation to evade enforcement, no paywall bypass, no Tier-C
domain, and nothing a venue's robots.txt disallows — the caller must pass
``robots_ok=True``, which :class:`~vsm.mining.robots.RobotsCache` decides.
"""

from __future__ import annotations

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
        """Fetch ``url``. Records tier (spec D5: no refusal by default) and refuses
        a robots ``Disallow``.

        ``robots_ok`` is a required keyword rather than a default so that a caller
        cannot fetch a page without having formed an opinion about robots.txt.

        ``catalogue`` is accepted for signature compatibility with the caller in
        ``vsm.mining.miner`` (which uses it independently, before this call, to
        compute ``hit.collection_tier``) but is no longer forwarded to
        ``assert_collectable`` — that function's signature dropped the parameter
        under spec D5, since this fork has no notion of a per-campaign venue
        catalogue overriding the blocklist.
        """
        assert_collectable(url)
        if not robots_ok:
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
        )
