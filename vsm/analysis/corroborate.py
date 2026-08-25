"""Rung 4 — how many *independent* sources say this, and what that earns.

Tastewise publishes the rule: three independent sources must align before a
finding is high-confidence. The rule is only as good as the definition of
independent, so here is ours — and it is venue-**band**-aware, not merely
venue-kind-aware, because kind alone was tried first and it over-counts.

**Publisher venues** (evidence, guideline bodies, regulatory, drug reference,
trade press, and any venue this tool has not classified) are independent by
registrable domain. Five outlets carrying one press release must count as one
source, and domain is the right key for that: op-ed.example.com and
www.example.com are the same publisher — and so, deliberately, are three
articles from one trade-press outlet under one byline.

**True forums and patient communities** (conversation-band
``hcp_discussion``/``patient_community`` venues) are independent by *post*,
not by domain. Twenty people posting on one forum are twenty sources, not
one — collapsing them onto the forum's domain would have meant every
conversational theme sits on a single domain and therefore never clears
three independent sources, so G6 would keep every conversational finding out
of the report body. For a tool whose entire subject is what people are
saying, that is fatal, and it is not a hypothetical: it is what a straight
domain-based rule does on a realistic fixture.

**Kind alone is the wrong line, and drawing it there was tried and measured
wrong.** Nine of the twenty-seven ``hcp_discussion``/``patient_community``
venues are trade press and clinician blogs — statnews.com, medpagetoday.com,
healio.com, kevinmd.com among them — one editorial voice, not many people.
Keyed on kind alone, three articles from statnews.com counted as three
independent sources and cleared ``corroborated`` on that one publisher's
say-so: the exact failure this rule exists to prevent, reintroduced in the
direction nobody notices, because it produces a confident report rather than
an empty one. See :func:`independence_key` for the band-based fix and why it
needs no edit to the hand-verified venue registry.

**The title clause is unchanged, for both kinds.** It still collapses a
syndicated release across publishers, and for a true forum it also catches
one person cross-posting the same text into several threads — a partial
answer to the fact that a post is only a proxy for a person: this tool
retains no author identifier for patient-generated content, not even hashed,
so people themselves are never counted, only posts and publishers.

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
from vsm.mining.venues import BAND_CONVERSATION, kind_of, venue_for

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

#: Venue kinds that *may* sit on the post path. Necessary but not sufficient —
#: see :func:`independence_key`, which also requires the conversation band.
#: Kind alone over-counts: 9 of the 27 discussion/community-kind venues are
#: trade press and clinician blogs (statnews.com, medpagetoday.com, healio.com,
#: kevinmd.com and friends), and three articles from one of those must not
#: clear the three-source bar on a single publisher's say-so.
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

    A true forum or patient community is keyed on the *post* — its
    normalised URL, or the bare venue when no URL is given — so twenty
    different threads on one forum are twenty sources. Everything else is
    keyed on the registrable domain, so five outlets are one publisher and
    subdomains of one publisher collapse together.

    **Kind alone is not enough.** ``hcp_discussion``/``patient_community`` is
    the venue's *content* kind, and trade press and clinician blogs
    (statnews.com, medpagetoday.com, healio.com, kevinmd.com, ...) share that
    kind with true forums while being a single editorial voice, not many
    people. Keyed on kind alone, three articles from one of those outlets
    were three "posts" and cleared the corroboration bar on that publisher's
    say-so alone — reintroducing, in the opposite direction, the exact
    failure this rule exists to prevent.

    The registry already draws this line without needing an edit: true
    forums carry ``BAND_CONVERSATION`` (explicitly, or by the kind-derived
    default — see ``Venue.spend_band``) and trade press carries
    ``BAND_OPINION`` explicitly. So the post path requires **both** the kind
    and the band; an unregistered venue (``venue_for`` returns ``None``) has
    no band to confirm and falls to the publisher path, which is the safe
    side.

    **Known, accepted limit:** ``op-med.doximity.com`` is Doximity's
    editorial column, not its member forum, but it resolves to the same
    conversation-band registry entry as ``doximity.com`` (the registry
    matches parent domains, not subdomains). Two Op-Med articles will
    therefore count as 2, a modest over-count on one venue. Fixing it would
    mean a subdomain-level exception in a hand-verified registry that is
    deliberately not being edited for one case — noted here rather than
    built around.
    """
    venue = str(signal.get("venue") or "")
    entry = venue_for(venue)
    band = entry.spend_band if entry is not None else None
    conversational = kind_of(venue) in CONVERSATIONAL_KINDS and band == BAND_CONVERSATION
    if conversational:
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
