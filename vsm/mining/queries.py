"""Query expansion **and the gold-list query plan**, shared by both miners.

The live path deliberately reuses ``DeterministicMiner.query_for`` (passed in by
:class:`engine.orchestrator.stages.HttpSignalMiner`) so that the two paths issue
the *same* queries for the same clusters. That is what makes an offline dry run a
real rehearsal of a live run, and it is asserted in ``tests/test_mining.py``.

The local fallback below is byte-identical to the deterministic miner's shape
list; it exists only so this package never has to import the orchestrator.

:func:`plan_queries` is the other half of that contract. It turns one cluster into
an ordered plan of ``site:``-scoped queries against the gold list
(:mod:`vsm.mining.venues`) followed by open-web queries as a *tail*, and both
miners walk the same plan in the same order. Two consequences worth stating:

* Gold first, open second, and the open tail only runs when the gold list
  under-delivers — so the tail being unspent is the normal, cheap outcome.
* Because the open queries are last, a sweep that stops early has executed a
  **prefix** of the plan. That is what keeps the offline rehearsal honest even
  when the live run spends less than the plan allowed.
"""

from __future__ import annotations

import re

from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping, Sequence

from vsm.mining.venues import (
    BAND_PATTERN,
    EVERGREEN_KINDS,
    Venue,
    areas_for_cluster,
    site_tokens,
    venues_for,
)

__all__ = [
    "default_query_for",
    "expand_queries",
    "query_registers",
    "intent_for",
    "PlannedQuery",
    "plan_queries",
    "gold_under_delivered",
    "GOLD_SITES_PER_QUERY",
    "MIN_GOLD_ROWS",
    "OPEN_QUERIES_MAX",
]

_SHAPES = ("{t}", "{t} guideline", "how to manage {t}", "{t} monitoring interval")

#: How many ``site:`` tokens go into one SERP query. Google tolerates long
#: ``OR``-chains, but a wide chain returns the same two dominant hosts over and
#: over — six keeps the spread while still costing one request.
GOLD_SITES_PER_QUERY = 6

#: Below this many rows from the gold list, the open-web tail is worth its money.
MIN_GOLD_ROWS = 3

#: Hard cap on the open tail. Open search is the expensive, low-yield half.
OPEN_QUERIES_MAX = 2


def model_queries(cluster: Mapping[str, Any]) -> list[str]:
    """Model-planned base queries carried on the cluster, if any.

    Written by ``engine.orchestrator.stages._plan_model_queries`` when a drafter is
    configured. Read from the cluster rather than from a module-level override so
    the offline and live miners plan identically from the same input — that
    equivalence is what makes a dry run a rehearsal of a paid one, and a global
    would break it the moment two campaigns overlapped.
    """
    return [str(q).strip() for q in (cluster.get("model_queries") or []) if str(q).strip()]


#: Query shapes, in the order the priority actually is: **conversation first**.
#:
#: The old set was ``("{t}", "{t} guideline", "how to manage {t}", "{t} monitoring
#: interval")`` — of which "guideline" and "monitoring interval" find *evidence* and
#: "how to manage" finds content farms. Not one of the four targeted discussion, while
#: ``MINING_SYSTEM`` told the model conversation was priority one. The shapes are how
#: that priority is actually expressed to a search engine.
_CONVERSATION_SHAPES: tuple[str, ...] = (
    "{t}",                       # the bare term, scoped to a forum, is the best single query
    "{t} experience",
    "anyone else {t}",
    "{t} not working",
)
#: Kept for the evidence tail — a guideline query is still worth one slot per cluster,
#: it just should not be three of four.
_EVIDENCE_SHAPES: tuple[str, ...] = (
    "{t} guideline",
    "{t} monitoring interval",
)


def query_registers(cluster: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Distinct *registers* for one cluster — never spellings of one register.

    This is the fix for the most expensive defect in the mining path. ``cluster.terms``
    is sliced from ``LexiconEntry.all_terms()``, which begins with
    ``morph_variants`` output — so ``terms[:4]`` for an OIC cluster was::

        ['opioid-induced constipation', 'opioid-induced constipations',
         'opioid induced constipation', 'OIC']

    One concept in four spellings: four paid SERP calls for one search, including a
    plural ("constipations") that nobody has ever typed. ``morph_variants`` is *right*
    for what it was built for — the never-say list genuinely needs every surface form,
    because a leak can wear any of them — and wrong as query input. Same list, two
    opposite jobs.

    So this reads the registers the lexicon already separates, and takes at most one
    from each:

    * the **concept**, once, in its canonical spelling;
    * the **pain point**, which was previously in the cluster label and never queried —
      and which is the single best forum-finding string in the object, because it is
      phrased the way a clinician complains rather than the way a journal indexes;
    * one **HCP colloquial** phrase ("the laxatives just are not touching it");
    * one **lay** phrase ("the pain pills stopped me up").

    Falls back to whatever ``terms`` holds when the richer fields are absent, so a
    hand-built cluster in a test still produces queries.
    """
    def first(values: Any) -> str:
        for v in values or ():
            text = str(v or "").strip()
            if text:
                return text
        return ""

    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(kind: str, value: str) -> None:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text:
            return
        # Compare on a normalised key so "opioid-induced constipation" and
        # "opioid induced constipation" cannot both take a slot.
        key = re.sub(r"[^a-z0-9 ]+", " ", text.casefold())
        key = re.sub(r"\s+", " ", key).strip()
        if key and key not in seen:
            seen.add(key)
            out.append((kind, text))

    add("formal", str(cluster.get("concept") or "") or first(cluster.get("terms")))
    add("pain", cluster.get("pain_point") or "")
    add("hcp", first(cluster.get("hcp_colloquial")))
    add("lay", first(cluster.get("lay")))
    # Only now fall back to the remaining raw terms, for a cluster that carries nothing
    # but ``terms`` — the normalised key above still keeps out pure respellings.
    for term in cluster.get("terms") or ():
        add("formal", term)
    return out


def default_query_for(cluster: Mapping[str, Any], index: int) -> str:
    """Same expansion as ``DeterministicMiner.query_for`` — one implementation.

    A model-planned query wins when one exists for this index; otherwise the shape is
    chosen so that **three of four slots look for conversation and the fourth looks for
    evidence**, matching the stated priority. Each slot draws a *different register*
    (see :func:`query_registers`) rather than a different spelling of the same one.
    """
    planned = model_queries(cluster)
    if index < len(planned):
        return planned[index]

    registers = query_registers(cluster)
    if not registers:
        return str(cluster.get("label") or "clinical question")

    # The last slot of every four goes to evidence; the rest to conversation. With the
    # default four-per-cluster budget that is a 3:1 split. Evidence queries always take
    # the *formal* register, which is register 0 by construction.
    if index % 4 == 3:
        shape = _EVIDENCE_SHAPES[(index // 4) % len(_EVIDENCE_SHAPES)]
        return shape.format(t=registers[0][1])

    kind, term = registers[index % len(registers)]
    return _shaped(kind, term, index)


#: Only the formal register is templated. Everything else is already phrased the way a
#: human writes it, which is the whole reason the lexicon separates the registers.
_TEMPLATED_KINDS = frozenset({"formal"})


def _shaped(kind: str, term: str, index: int) -> str:
    """Apply a conversation template, but only to the register that needs one.

    Two earlier versions of this were wrong in instructive ways.

    The first templated **everything**, producing::

        "managing opioid-induced constipation when the evidence does not fit the
         patient in front of you experience"

    The second gated on word count, which fixed the long cases and still produced::

        "opioid-induced constipation in practice experience"

    Both failures have the same cause: a **colloquial phrase, a pain point and a lay
    phrase are already queries.** "my patients on chronic opioids who stop moving their
    bowels" is the sentence a clinician actually writes in a forum post — that is why
    the lexicon holds it — so wrapping it in a template can only move it *away* from
    the text we are trying to match. Word count was a proxy for that and a leaky one.

    Templates exist to turn a short formal noun phrase ("laxative-refractory
    constipation") into something conversational. That is the only register they help.
    """
    if kind not in _TEMPLATED_KINDS:
        return term
    return _CONVERSATION_SHAPES[index % len(_CONVERSATION_SHAPES)].format(t=term)


def expand_queries(
    cluster: Mapping[str, Any],
    count: int,
    *,
    query_for: Callable[[Mapping[str, Any], int], str] | None = None,
) -> list[str]:
    """``count`` queries for one cluster, order preserved, duplicates dropped."""
    build = query_for or default_query_for
    seen: set[str] = set()
    out: list[str] = []
    for index in range(max(int(count), 0)):
        query = build(cluster, index)
        if query and query not in seen:
            seen.add(query)
            out.append(query)
    return out


def intent_for(cluster: Mapping[str, Any]) -> str:
    """The Discover ``intent`` for a cluster — the thing that drives its ranking.

    Clinical-question framing, never a targeting brief: Stage 2 answers *what to
    write about*, never *who to reach* (PRD §9.3).
    """
    label = str(cluster.get("label") or "").strip()
    terms: Sequence[str] = list(cluster.get("terms") or [])[:4]
    topic = label or (terms[0] if terms else "this clinical question")
    tail = f" Terms: {', '.join(terms)}." if terms else ""
    return (
        f"Clinician-facing discussion, guidance or practice commentary about {topic} — "
        f"what practising clinicians find difficult, uncertain or contested.{tail}"
    )


# --------------------------------------------------------------------------- #
# the gold-list query plan                                                     #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PlannedQuery:
    """One SERP query the plan intends to run, and everything about why."""

    text: str
    #: ``gold`` — scoped to named venues. ``open`` — the open web, tail only.
    kind: Literal["gold", "open"]
    base: str
    venues: tuple[str, ...] = ()
    site_tokens: tuple[str, ...] = ()
    areas: tuple[str, ...] = ()
    venue_kinds: tuple[str, ...] = ()
    #: 1 conversation · 2 opinion/KOL · 3 substrate. ``0`` for the open-web tail.
    band: int = 0
    #: ``True`` when every venue in this query carries the recency window. A query
    #: mixing evidence with discussion could not be honestly date-restricted, so
    #: the plan never builds one — the two are always separate queries.
    date_restricted: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.text,
            "kind": self.kind,
            "base": self.base,
            "venues": list(self.venues),
            "areas": list(self.areas),
            "venue_kinds": list(self.venue_kinds),
            "date_restricted": self.date_restricted,
            "band": self.band,
            "band_name": {1: "conversation", 2: "opinion_kol", 3: "substrate"}.get(self.band, "open_web"),
        }


def _chunk(items: Sequence[Venue], size: int) -> list[list[Venue]]:
    return [list(items[i : i + size]) for i in range(0, len(items), max(int(size), 1))]


def _scoped(base: str, tokens: Sequence[str]) -> str:
    """``base (site:a OR site:b)`` — Google's own syntax, one request."""
    if not tokens:
        return base
    inner = " OR ".join(f"site:{token}" for token in tokens)
    return f"{base} ({inner})" if len(tokens) > 1 else f"{base} site:{tokens[0]}"


def plan_queries(
    cluster: Mapping[str, Any],
    count: int,
    *,
    query_for: Callable[[Mapping[str, Any], int], str] | None = None,
    areas: Sequence[str] | None = None,
    sites_per_query: int = GOLD_SITES_PER_QUERY,
    open_queries_max: int = OPEN_QUERIES_MAX,
    venues: Sequence[Venue] | None = None,
) -> list[PlannedQuery]:
    """The ordered plan for one cluster: gold-scoped queries, then an open tail.

    ``count`` is the gold-list budget in SERP requests — the same number the caller
    used to mean "queries per cluster", now spent on targeted queries instead of
    open ones. The open tail is *additional* and conditional; see
    :func:`gold_under_delivered`.

    Deterministic in ``(cluster, count, areas, registry order)`` and nothing else:
    both miners must be able to build this list independently and agree.
    """
    bases = expand_queries(cluster, count, query_for=query_for)
    if not bases:
        return []
    routed = tuple(areas) if areas is not None else areas_for_cluster(cluster)
    pool = list(venues) if venues is not None else venues_for(routed)

    # one queue of venue groups per spend band, each group homogeneous in recency
    # (a group mixing evidence with discussion could not be honestly date-restricted)
    queues: dict[int, list[list[Venue]]] = {}
    for band in sorted({v.spend_band for v in pool}):
        in_band = [v for v in pool if v.spend_band == band]
        evergreen = [v for v in in_band if v.kind in EVERGREEN_KINDS]
        dated = [v for v in in_band if v.kind not in EVERGREEN_KINDS]
        groups = [g for g in _chunk(dated, sites_per_query) + _chunk(evergreen, sites_per_query) if g]
        if groups:
            queues[band] = groups
    if not queues:
        return []
    order = [band for band in BAND_PATTERN if band in queues] or sorted(queues)

    plan: list[PlannedQuery] = []
    taken: dict[int, int] = {band: 0 for band in queues}
    for index, base in enumerate(bases):
        band = order[index % len(order)]
        groups = queues[band]
        group = groups[taken[band] % len(groups)]
        taken[band] += 1
        tokens: list[str] = []
        for venue in group:
            tokens.extend(site_tokens(venue, routed))
        restricted = all(v.recency_filtered for v in group)
        plan.append(
            PlannedQuery(
                text=_scoped(base, tokens),
                kind="gold",
                base=base,
                venues=tuple(v.domain for v in group),
                site_tokens=tuple(tokens),
                areas=routed,
                venue_kinds=tuple(dict.fromkeys(v.kind for v in group)),
                date_restricted=restricted,
                band=band,
            )
        )
    # the open tail — last, so an early stop is always a prefix of the plan
    for base in bases[: max(int(open_queries_max), 0)]:
        plan.append(PlannedQuery(text=base, kind="open", base=base, areas=routed))
    return plan


def gold_under_delivered(rows_from_gold: int, *, minimum: int = MIN_GOLD_ROWS) -> bool:
    """Is the open-web tail worth its money?

    One rule, in one place, because the offline miner has to make the same call as
    the live one or the rehearsal stops being a rehearsal.
    """
    return int(rows_from_gold) < int(minimum)
