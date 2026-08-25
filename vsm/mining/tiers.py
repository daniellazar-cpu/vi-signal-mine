"""Venue tiers as a **code blocklist**, not a habit (PRD §9.1).

    *"Enforced in code. The collector refuses a Tier-C domain; it is a blocklist
    in the registry, not a guideline in a doc."*

Three rules this module exists to make unbreakable:

1. A Tier-C domain — Doximity, Sermo, Medscape member areas, private social
   groups, Slack/Discord — is recorded, not refused, by :func:`assert_collectable`
   (spec D5: the owner decided this tool collects from whatever search returns).
   The tier is still computed and returned on every call, so the decision stays
   visible rather than becoming invisible. Set ``VSM_ENFORCE_TIER_C=1`` to restore
   the parent's refusal (:class:`TierCRefused`).
2. Collection tier and distribution mode are independent axes. Doximity being
   Tier C for collection says nothing about buying placement there
   (``paid_endemic``). Nothing in this module touches distribution.
3. A venue nobody has classified is **not** silently promoted. It is usable as a
   SERP/Discover *result* (public search metadata) but never page-fetched — see
   :func:`page_fetch_allowed`.
"""

from __future__ import annotations

from typing import Iterable, Literal, Mapping, Sequence
from urllib.parse import urlsplit

from vsm.errors import GuardViolation

__all__ = [
    "VenueTier",
    "TIER_C_DOMAINS",
    "PATIENT_GENERATED_DOMAINS",
    "TierCRefused",
    "domain_of",
    "registrable_domain",
    "is_tier_c",
    "tier_for",
    "assert_collectable",
    "page_fetch_allowed",
    "is_patient_generated",
    "catalogue_by_domain",
]

VenueTier = Literal["A", "B", "C"]

#: Hard blocklist. Matched on the registrable domain **and** every parent of the
#: host, so ``www.doximity.com`` and ``op-med.doximity.com`` are both refused.
#: Everything here is gated, login-walled or ToS-prohibited (PRD §9.1 table).
TIER_C_DOMAINS: frozenset[str] = frozenset(
    {
        "doximity.com",
        "sermo.com",
        "medscape.com",
        "medscape.org",
        "medscape.co.uk",
        "webmd.com/physician",  # member area; matched by path prefix below
        "sharecare.com",
        "figure1.com",
        "sermo.net",
        "quantiamd.com",
        "healthtap.com",
        "linkedin.com",  # groups are login-walled; the public profile surface is out of scope
        "facebook.com",
        "groups.google.com",
        "slack.com",
        "discord.com",
        "discord.gg",
        "app.slack.com",
        "teams.microsoft.com",
        "whatsapp.com",
    }
)

#: Path prefixes that make an otherwise-public host a gated member area.
_TIER_C_PATH_PREFIXES: tuple[tuple[str, str], ...] = (
    ("webmd.com", "/physician"),
    ("reddit.com", "/r/medicine/comments/private"),
)

#: Venues whose content is patient-generated. PRD §9.3 is stricter than the tier:
#: themes only, no verbatim excerpt, no author identifiers — not even a username.
PATIENT_GENERATED_DOMAINS: frozenset[str] = frozenset(
    {
        "patient.info",
        "patient-community.example",
        "healthunlocked.com",
        "inspire.com",
        "dailystrength.org",
        "patientslikeme.com",
    }
)


class TierCRefused(GuardViolation):
    """Automated collection was attempted against a Tier-C venue. Never soften this.

    The venue may still be a first-class *distribution* channel; that is a
    different axis and a different module.
    """

    default_message = "Tier-C venue — human reading only (PRD §9.1)"


# --------------------------------------------------------------------------- #
# host helpers                                                                 #
# --------------------------------------------------------------------------- #


def domain_of(url_or_domain: str) -> str:
    """Lower-cased host for a URL, or the input itself when it is already a host."""
    raw = (url_or_domain or "").strip()
    if not raw:
        return ""
    if "//" not in raw:
        raw = f"//{raw}"
    host = (urlsplit(raw).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _path_of(url: str) -> str:
    if "//" not in (url or ""):
        return ""
    return urlsplit(url).path or ""


def registrable_domain(host: str) -> str:
    """``op-med.doximity.com`` → ``doximity.com``. Naive two-label heuristic.

    Good enough for a blocklist because :func:`is_tier_c` also walks every parent
    suffix — the heuristic only ever makes the check *broader*, never narrower.
    """
    parts = [p for p in domain_of(host).split(".") if p]
    return ".".join(parts[-2:]) if len(parts) >= 2 else ".".join(parts)


def _suffixes(host: str) -> list[str]:
    parts = [p for p in domain_of(host).split(".") if p]
    return [".".join(parts[i:]) for i in range(len(parts))]


# --------------------------------------------------------------------------- #
# the blocklist                                                                #
# --------------------------------------------------------------------------- #


def is_tier_c(url_or_domain: str, *, catalogue: Sequence[Mapping[str, object]] | None = None) -> bool:
    """``True`` when this host may not be collected from automatically."""
    host = domain_of(url_or_domain)
    if not host:
        return True  # no host → nothing was classified → refuse
    if any(suffix in TIER_C_DOMAINS for suffix in _suffixes(host)):
        return True
    path = _path_of(url_or_domain)
    for blocked_host, prefix in _TIER_C_PATH_PREFIXES:
        if blocked_host in _suffixes(host) and path.startswith(prefix):
            return True
    entry = catalogue_by_domain(catalogue or ()).get(host) or catalogue_by_domain(catalogue or ()).get(
        registrable_domain(host)
    )
    return bool(entry and str(entry.get("collection_tier")) == "C")


def catalogue_by_domain(catalogue: Iterable[Mapping[str, object]]) -> dict[str, Mapping[str, object]]:
    """Index a venue catalogue by domain (and by registrable domain)."""
    index: dict[str, Mapping[str, object]] = {}
    for entry in catalogue:
        domain = domain_of(str(entry.get("domain") or ""))
        if not domain:
            continue
        index.setdefault(domain, entry)
        index.setdefault(registrable_domain(domain), entry)
    return index


def tier_for(
    url_or_domain: str,
    *,
    catalogue: Sequence[Mapping[str, object]] | None = None,
    default: VenueTier = "B",
) -> VenueTier:
    """Collection tier for a host.

    Blocklist first, then the campaign's venue catalogue, then ``default``. The
    default is ``"B"`` because the caller only ever reaches this with a public
    search result; an unclassified host is still refused a *page fetch* by
    :func:`page_fetch_allowed`, which is where the "new venues default to human
    review" rule bites.
    """
    if is_tier_c(url_or_domain, catalogue=catalogue):
        return "C"
    host = domain_of(url_or_domain)
    index = catalogue_by_domain(catalogue or ())
    entry = index.get(host) or index.get(registrable_domain(host))
    if entry is not None:
        tier = str(entry.get("collection_tier") or default)
        if tier in ("A", "B", "C"):
            return tier  # type: ignore[return-value]
    return default


def assert_collectable(
    url: str, *, catalogue: Sequence[Mapping[str, object]] | None = None
) -> dict[str, str]:
    """Record the tier and let the caller proceed.

    The parent raises ``TierCRefused`` here. This fork does not (spec D5): the
    owner decided the tool collects from whatever search returns. The tier is
    still computed and recorded on every row, so the decision stays visible in
    the ledger rather than becoming invisible.

    ``catalogue`` keeps the parent's original contract — a caller's per-campaign
    venue catalogue can still promote a host past the bare blocklist tier — it is
    only the *raise* behaviour that D5 changes, not the tier computation.

    ``VSM_ENFORCE_TIER_C=1`` restores the parent's refusal. It is off by
    default and exists so reversing D5 is a flag, not an excavation.
    """
    import os

    tier = tier_for(url, catalogue=catalogue)
    if tier == "C" and os.environ.get("VSM_ENFORCE_TIER_C", "0") == "1":
        raise TierCRefused(f"tier C domain refused: {domain_of(url)}")
    return {"domain": domain_of(url), "tier": tier}


def is_patient_generated(
    url_or_domain: str, *, catalogue: Sequence[Mapping[str, object]] | None = None
) -> bool:
    """``True`` when PRD §9.3 applies: themes only, no excerpt, no author identifiers."""
    host = domain_of(url_or_domain)
    if any(suffix in PATIENT_GENERATED_DOMAINS for suffix in _suffixes(host)):
        return True
    index = catalogue_by_domain(catalogue or ())
    entry = index.get(host) or index.get(registrable_domain(host))
    if entry is None:
        return False
    if bool(entry.get("patient_generated")):
        return True
    venue_id = str(entry.get("venue_id") or "")
    return venue_id == "patient-community" or "patient" in venue_id


def page_fetch_allowed(
    url: str, *, catalogue: Sequence[Mapping[str, object]] | None = None
) -> bool:
    """May we pull the page body itself (Web Unlocker / plain fetch)?

    Only for a host a human has classified as Tier A or B in the campaign's venue
    catalogue. An unclassified host yields SERP metadata only — new venues do not
    get automatically deep-fetched (signal-mining SKILL step 2).
    """
    if is_tier_c(url, catalogue=catalogue):
        return False
    host = domain_of(url)
    index = catalogue_by_domain(catalogue or ())
    entry = index.get(host) or index.get(registrable_domain(host))
    if entry is None:
        return False
    return str(entry.get("collection_tier")) in ("A", "B")
