"""Rung 4 — how many *independent* sources say this, and what that earns.

Tastewise publishes the rule: three independent sources must align before a
finding is high-confidence. The rule is only as good as the definition of
independent, so here is ours.

Two signals are **not** independent when they share a registrable domain, or
when they share a normalised title. The first clause collapses subdomains of one
publisher. The second collapses syndication — five outlets carrying the same
press release are one source, and counting them as five is how a single PR gets
promoted into a corroborated finding.

That makes independence a connected-components count: link signals that share a
domain or a title, then count the components.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping, Sequence

from vsm.mining.tiers import registrable_domain

__all__ = [
    "Finding",
    "Tier",
    "CORROBORATED_AT",
    "independent_source_count",
    "tier_for_count",
    "corroborate",
]

Tier = Literal["corroborated", "emerging", "single_source"]

#: Tastewise's published threshold, adopted deliberately rather than invented.
CORROBORATED_AT = 3

_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Finding:
    finding_id: str
    statement: str
    signal_ids: tuple[str, ...]
    independent_sources: int
    tier: Tier
    #: Ids the claim named that do not resolve to a ledger row. A later guard
    #: binds every claim's signal_ids back to real rows and blocks the whole
    #: report on any that fail — so a hallucinated id belongs neither in
    #: ``signal_ids`` (where it would inflate the evidence list past what
    #: ``independent_sources`` was actually computed from) nor nowhere at all
    #: (a silent drop is indistinguishable from the model finding nothing).
    #: It is recorded here instead.
    unresolved_ids: tuple[str, ...] = ()


def _dedupe_preserve_order(ids: Iterable[str]) -> list[str]:
    """First-seen order, no repeats.

    A repeated id must count once. Left undeduped it doesn't change
    ``independent_source_count`` (union-find collapses a sid unioned with
    itself), but it would make ``signal_ids`` overstate the evidence a
    finding rests on.
    """
    seen: set[str] = set()
    out: list[str] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def _norm_title(signal: Mapping[str, Any]) -> str:
    return _WS.sub(" ", str(signal.get("title") or "")).strip().lower()


class _Union:
    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def find(self, key: str) -> str:
        self._parent.setdefault(key, key)
        while self._parent[key] != key:
            self._parent[key] = self._parent[self._parent[key]]
            key = self._parent[key]
        return key

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra


def independent_source_count(signals: Sequence[Mapping[str, Any]]) -> int:
    """Connected components under "same domain OR same title"."""
    if not signals:
        return 0
    uf = _Union()
    by_domain: dict[str, str] = {}
    by_title: dict[str, str] = {}
    for signal in signals:
        sid = str(signal["signal_id"])
        uf.find(sid)
        domain = registrable_domain(str(signal.get("venue") or ""))
        if domain:
            if domain in by_domain:
                uf.union(by_domain[domain], sid)
            else:
                by_domain[domain] = sid
        title = _norm_title(signal)
        if title:
            if title in by_title:
                uf.union(by_title[title], sid)
            else:
                by_title[title] = sid
    return len({uf.find(str(s["signal_id"])) for s in signals})


def tier_for_count(n: int) -> Tier:
    if n >= CORROBORATED_AT:
        return "corroborated"
    if n == 2:
        return "emerging"
    return "single_source"


def corroborate(
    claims: Sequence[Mapping[str, Any]], signals_by_id: Mapping[str, Mapping[str, Any]]
) -> list[Finding]:
    findings: list[Finding] = []
    for index, claim in enumerate(claims, start=1):
        raw_ids = _dedupe_preserve_order(str(s) for s in claim.get("signal_ids", []))
        ids = tuple(i for i in raw_ids if i in signals_by_id)
        unresolved = tuple(i for i in raw_ids if i not in signals_by_id)
        rows = [signals_by_id[i] for i in ids]
        count = independent_source_count(rows)
        findings.append(
            Finding(
                finding_id=f"fin-{index:03d}",
                statement=str(claim.get("statement", "")),
                signal_ids=ids,
                independent_sources=count,
                tier=tier_for_count(count),
                unresolved_ids=unresolved,
            )
        )
    return findings
