"""Rung 4 — how many *independent* sources say this, and what that earns.

Tastewise publishes the rule: three independent sources must align before a
finding is high-confidence. The rule is only as good as the definition of
independent, so here is ours — and it is venue-kind-aware, because the naive
version broke on the first realistic fixture.

**Publisher venues** (evidence, guideline bodies, regulatory, drug reference,
and any venue this tool has not classified) are independent by registrable
domain. Five outlets carrying one press release must count as one source, and
domain is the right key for that: op-ed.example.com and www.example.com are
the same publisher.

**Conversational venues** (``hcp_discussion``, ``patient_community``) are
independent by *post*, not by domain. Twenty people posting on one forum are
twenty sources, not one — collapsing them onto the forum's domain would have
meant every conversational theme sits on a single domain and therefore never
clears three independent sources, so G6 would keep every conversational
finding out of the report body. For a tool whose entire subject is what
people are saying, that is fatal, and it is not a hypothetical: it is what a
straight domain-based rule does on a realistic fixture.

**The title clause is unchanged, for both kinds.** It still collapses a
syndicated release across publishers, and for a conversational venue it also
catches one person cross-posting the same text into several threads — a
partial answer to the fact that a post is only a proxy for a person: this
tool retains no author identifier for patient-generated content, not even
hashed, so people themselves are never counted, only posts and publishers.

That makes independence a connected-components count: link signals that share
an independence key (domain for a publisher, post for a conversation) or a
title, then count the components.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping, Sequence

from vsm.mining.signals import normalise_url
from vsm.mining.tiers import registrable_domain
from vsm.mining.venues import kind_of

__all__ = [
    "Finding",
    "Tier",
    "CORROBORATED_AT",
    "CONVERSATIONAL_KINDS",
    "independence_key",
    "independent_source_count",
    "tier_for_count",
    "corroborate",
]

Tier = Literal["corroborated", "emerging", "single_source"]

#: Tastewise's published threshold, adopted deliberately rather than invented.
CORROBORATED_AT = 3

#: Venue kinds where the *post* is the source, not the publisher. Matches
#: ``vsm.analysis.authorclass.KIND_TO_CLASS``'s conversational half — the
#: registry has no third kind between "a publication" and "a conversation".
CONVERSATIONAL_KINDS = frozenset({"hcp_discussion", "patient_community"})

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


def independence_key(signal: Mapping[str, Any]) -> tuple[str, str]:
    """What makes this signal the same source as another one.

    A conversational venue (a forum, a patient community) is keyed on the
    *post* — its normalised URL, or the bare venue when no URL is given — so
    twenty different threads on one forum are twenty sources. Everything
    else is keyed on the registrable domain, so five outlets are one
    publisher and subdomains of one publisher collapse together.
    """
    venue = str(signal.get("venue") or "")
    if kind_of(venue) in CONVERSATIONAL_KINDS:
        return ("post", normalise_url(str(signal.get("url") or "") or venue))
    return ("publisher", registrable_domain(venue))


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
    """Connected components under "same independence key OR same title"."""
    if not signals:
        return 0
    uf = _Union()
    by_key: dict[tuple[str, str], str] = {}
    by_title: dict[str, str] = {}
    for signal in signals:
        sid = str(signal["signal_id"])
        uf.find(sid)
        key = independence_key(signal)
        if key[1]:
            if key in by_key:
                uf.union(by_key[key], sid)
            else:
                by_key[key] = sid
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
