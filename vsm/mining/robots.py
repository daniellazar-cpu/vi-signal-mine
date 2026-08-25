"""robots.txt, fetched and cached **per campaign** (PRD §9.1).

    *"robots.txt is fetched and cached per campaign, and a `Disallow` moves a
    venue to C for that campaign."*

Parsing is :mod:`urllib.robotparser` from the standard library — no new
dependency, and it implements the ``User-agent``/``Allow``/``Disallow``
precedence rules properly. Fetching goes through an injected callable so the
cache is testable and so the *same* transport (mock or real) is used everywhere.

A host whose robots.txt cannot be fetched is treated as **disallowed**, not
allowed: absence of evidence is not permission.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from vsm.mining.client import USER_AGENT
from vsm.mining.tiers import domain_of

__all__ = ["RobotsState", "RobotsCache", "robots_url_for"]


def robots_url_for(url: str) -> str:
    parts = urlsplit(url if "//" in url else f"https://{url}")
    scheme = parts.scheme or "https"
    return f"{scheme}://{parts.netloc or parts.path}/robots.txt"


@dataclass
class RobotsState:
    """What robots.txt said, and when — the provenance a Signal's ToS basis needs."""

    domain: str
    fetched_at: datetime | None = None
    text: str | None = None
    reachable: bool = False
    parser: RobotFileParser | None = None

    def allows(self, url: str, user_agent: str) -> bool:
        if not self.reachable or self.parser is None:
            return False
        return bool(self.parser.can_fetch(user_agent, url))

    def summary(self) -> str:
        if not self.reachable:
            return "robots.txt unreachable at fetch time — treated as disallow"
        stamp = self.fetched_at.isoformat() if self.fetched_at else "unknown"
        return f"robots.txt fetched {stamp}"


@dataclass
class RobotsCache:
    """One cache per campaign. ``fetch`` returns the text, or ``None`` if unreachable."""

    fetch: Callable[[str], str | None]
    user_agent: str = USER_AGENT
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    states: dict[str, RobotsState] = field(default_factory=dict)

    def state_for(self, url: str) -> RobotsState:
        domain = domain_of(url)
        cached = self.states.get(domain)
        if cached is not None:
            return cached
        text: str | None
        try:
            text = self.fetch(robots_url_for(url))
        except Exception:
            text = None
        state = RobotsState(domain=domain, fetched_at=self.now(), text=text, reachable=text is not None)
        if text is not None:
            parser = RobotFileParser()
            parser.parse(text.splitlines())
            state.parser = parser
        self.states[domain] = state
        return state

    def allows(self, url: str) -> bool:
        # D5: callers in this fork RECORD this answer into coverage.json rather
        # than letting it veto a fetch. The method is unchanged; its authority is.
        return self.state_for(url).allows(url, self.user_agent)

    def as_provenance(self) -> dict[str, dict[str, object]]:
        return {
            domain: {
                "fetched_at": state.fetched_at.isoformat() if state.fetched_at else None,
                "reachable": state.reachable,
                "bytes": len(state.text or ""),
            }
            for domain, state in self.states.items()
        }
