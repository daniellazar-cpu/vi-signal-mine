"""Normalise a mined hit into the Stage-2 signal row (PRD §5.3).

The row shape is not negotiable: it must be byte-compatible with what
``DeterministicMiner`` emits, because Stage 3 validates both through
``engine.models.Signal`` and the artifact tests assert on the same keys.

Three rules live here rather than in the caller, so they cannot be forgotten:

* ``author_type`` is **never** inferred from a username. It is ``patient`` when
  the *venue* is patient-generated and ``unknown`` otherwise, and
  ``author_type_rationale`` always says so out loud (PRD §5.3).
* Patient-forum signal is **themes only** — no excerpt, no username, no author
  identifier of any kind, not even hashed (PRD §9.3).
* No provenance → not admissible. ``tos_basis`` and ``collection_method`` are
  always populated from what actually happened at fetch time, never assumed.

Nothing here invents a number. ``sentiment`` stays ``None`` because no classifier
ran; ``posted_at`` stays ``None`` unless the venue actually exposed a date
(PRD §5.3: *do not guess*).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

from vsm.mining.tiers import VenueTier, domain_of

__all__ = [
    "Hit",
    "build_row",
    "dedupe_rows",
    "tos_basis_for",
    "normalise_url",
    "derive_theme",
    "short_excerpt",
    "any_synthetic",
    "AUTHOR_RATIONALE",
    "PATIENT_AUTHOR_RATIONALE",
    "MAX_EXCERPT_WORDS",
]

MAX_EXCERPT_WORDS = 25

#: Must keep saying it. A test asserts the substring on every live row.
AUTHOR_RATIONALE = "not inferred from username (PRD §5.3)"
PATIENT_AUTHOR_RATIONALE = (
    "venue is patient-generated, so the venue sets author_type; "
    "not inferred from username (PRD §5.3)"
)

_WHITESPACE = re.compile(r"\s+")
_TITLE_TAIL = re.compile(r"\s*[|–—-]\s*[^|–—-]{1,40}$")


@dataclass
class Hit:
    """One thing we found, before it becomes a ledger row."""

    url: str
    title: str = ""
    description: str = ""
    content: str | None = None
    relevance_score: float | None = None
    #: ``serp_result`` | ``discover`` | ``public_web_fetch`` | ``api``
    collection_method: str = "serp_result"
    collection_tier: VenueTier = "B"
    distribution_mode: str | None = None
    patient_generated: bool = False
    tos_basis: str = ""
    posted_at: str | None = None
    engagement: dict[str, int] = field(default_factory=dict)
    query: str = ""

    @property
    def domain(self) -> str:
        return domain_of(self.url)


# --------------------------------------------------------------------------- #
# text helpers                                                                 #
# --------------------------------------------------------------------------- #


def _clean(text: str | None) -> str:
    return _WHITESPACE.sub(" ", (text or "").replace(" ", " ")).strip()


def normalise_url(url: str) -> str:
    """Scheme/host/path only, lower-cased, no ``www.``, no query, no trailing slash."""
    parts = urlsplit(url if "//" in url else f"https://{url}")
    host = domain_of(url)
    path = (parts.path or "").rstrip("/")
    return f"{host}{path}".lower()


def derive_theme(hit: Hit) -> str:
    """A short, non-verbatim topic phrase — safe for a patient venue.

    Built from the *title* (a page title is a label, not a member's words) with a
    trailing site name stripped, capped at 12 words and lower-cased so it reads as
    a theme rather than a quotation.
    """
    title = _clean(hit.title)
    if title:
        title = _TITLE_TAIL.sub("", title) or title
    if not title:
        title = _clean(hit.description)[:120]
    if not title:
        title = _clean(hit.query) or "unlabelled discussion"
    words = title.split()[:12]
    return " ".join(words).lower()


def short_excerpt(hit: Hit) -> str | None:
    """≤25 words of the fetched page, or ``None`` when an excerpt is not permitted.

    Callers must have already established that the source is Tier A/B and not
    patient-generated; :func:`build_row` enforces that regardless.
    """
    source = _clean(hit.content) or _clean(hit.description)
    if not source:
        return None
    sentence = re.split(r"(?<=[.!?])\s", source)[0]
    words = sentence.split()
    if len(words) > MAX_EXCERPT_WORDS:
        words = words[:MAX_EXCERPT_WORDS]
    text = " ".join(words).strip()
    return text or None


def matched_terms_for(hit: Hit, cluster: Mapping[str, Any]) -> list[str]:
    """Which lexicon terms actually hit. Falls back to the query's leading token."""
    haystack = " ".join(
        filter(None, (_clean(hit.title), _clean(hit.description), _clean(hit.content)[:2000]))
    ).lower()
    hits = [t for t in (cluster.get("terms") or []) if t and str(t).lower() in haystack]
    if hits:
        return [str(t) for t in hits]
    head = _clean(hit.query).split()
    return [head[0]] if head else []


# --------------------------------------------------------------------------- #
# the row                                                                      #
# --------------------------------------------------------------------------- #


def build_row(
    *,
    campaign_id: str,
    cluster: Mapping[str, Any],
    hit: Hit,
    captured_at: datetime,
    brand_terms: Mapping[str, str] | None = None,
    topic_id: str | None = None,
    snapshot_at: str | None = None,
    synthetic: bool = False,
) -> dict[str, Any]:
    """One mined hit → one ledger-shaped row. Same keys as ``DeterministicMiner``."""
    patient = bool(hit.patient_generated)
    theme = derive_theme(hit)
    excerpt: str | None = None
    if not patient and hit.collection_tier != "C":
        excerpt = short_excerpt(hit)

    score = hit.relevance_score
    intent_score = round(max(0.0, min(float(score), 1.0)), 2) if isinstance(score, (int, float)) else None

    signal_id = "sig-" + hashlib.sha1(
        f"{campaign_id}|{normalise_url(hit.url)}|{hit.query}".encode("utf-8")
    ).hexdigest()[:12]

    row: dict[str, Any] = {
        "signal_id": signal_id,
        "campaign_id": campaign_id,
        "cluster_id": cluster.get("cluster_id"),
        "venue": hit.domain,
        "collection_tier": hit.collection_tier,
        "distribution_mode": hit.distribution_mode,
        "url": hit.url,
        "captured_at": captured_at.isoformat(),
        # the venue did not expose it → stays null, never guessed (PRD §5.3)
        "posted_at": hit.posted_at,
        "author_type": "patient" if patient else "unknown",
        "author_type_confidence": None,
        "author_type_rationale": PATIENT_AUTHOR_RATIONALE if patient else AUTHOR_RATIONALE,
        "matched_terms": matched_terms_for(hit, cluster),
        "excerpt": excerpt,
        "theme": theme,
        # no sentiment classifier ran on the live path — a number here would be invented
        "sentiment": None,
        "intent_score": intent_score,
        "brand_mentioned": _brand_mention(hit, brand_terms),
        "engagement": dict(hit.engagement),
        "collection_method": hit.collection_method,
        "tos_basis": hit.tos_basis,
        "action": "content_topic" if (intent_score is not None and intent_score >= 0.6) else "monitor",
        "dedupe_hash": hashlib.sha256(
            f"{normalise_url(hit.url)}|{theme}".encode("utf-8")
        ).hexdigest()[:32],
        "_query": hit.query,
    }
    # Snapshot identity. Defaulted so the parent's fixtures still validate:
    # every pre-existing key keeps its exact meaning and position.
    if topic_id is not None:
        row["topic_id"] = topic_id
    if snapshot_at is not None:
        row["snapshot_at"] = snapshot_at
    # The safety rail (Task: offline demonstration miner). Same pattern as
    # topic_id/snapshot_at above: defaulted keyword-only, absent from the row
    # unless a caller actually asks for it, so a live row — and every parity
    # fixture above, which never passes this kwarg — is byte-identical to
    # before. Only vsm.mining.fake.DeterministicMiner ever passes ``True``.
    # The marker rides on the data, not the chrome: a fabricated row must
    # say so from inside the artifact itself, not merely in a UI badge that
    # a downloaded JSON or Markdown file does not carry with it.
    if synthetic:
        row["synthetic"] = True
    return _strip_author_identifiers(row)


def _brand_mention(hit: Hit, brand_terms: Mapping[str, str] | None) -> str:
    if not brand_terms:
        return "none"
    haystack = " ".join((_clean(hit.title), _clean(hit.description), _clean(hit.content)[:4000])).lower()
    for term, label in brand_terms.items():
        if term and str(term).lower() in haystack and label in ("ours", "competitor", "class"):
            return label
    return "none"


def _strip_author_identifiers(row: dict[str, Any]) -> dict[str, Any]:
    """Belt and braces for PRD §9.3: no author identifier ever reaches the ledger.

    Nothing upstream puts one in, which is the point — this is the assertion that
    keeps it true after the next edit.
    """
    for key in ("author", "author_id", "username", "user", "handle", "display_name", "profile_url"):
        row.pop(key, None)
    if row.get("author_type") == "patient":
        row["excerpt"] = None
    return row


def any_synthetic(rows: Iterable[Mapping[str, Any]]) -> bool:
    """``True`` when at least one row in ``rows`` was fabricated for rehearsal.

    The single source of truth every downstream writer (coverage.json,
    cost.json, every INSIGHT and REPORT artifact) calls to decide whether it
    must carry the marker too. One row is enough: a snapshot is not
    partially trustworthy, and a report built over a mixed snapshot is a
    demonstration report, full stop.
    """
    return any(bool(row.get("synthetic")) for row in rows)


def dedupe_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """First occurrence wins, keyed on ``dedupe_hash`` (URL + theme)."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = str(row.get("dedupe_hash") or "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(dict(row))
    return out


def tos_basis_for(
    *,
    venue_entry: Mapping[str, Any] | None,
    robots_summary: str,
    method: str,
    checked_at: datetime,
) -> str:
    """The ToS basis string. Never empty — an empty one means inadmissible."""
    posture = str((venue_entry or {}).get("tos_posture") or "").strip()
    if not posture:
        posture = {
            "serp_result": "public search-result metadata (title, link, snippet)",
            "discover": "public search-result metadata via intent discovery",
            "public_web_fetch": "public web page, no login, no paywall bypass",
            "api": "official API within terms",
        }.get(method, "public web")
    parts: Sequence[str] = [posture, robots_summary, f"checked at {checked_at.isoformat()}"]
    return "; ".join(p for p in parts if p)
