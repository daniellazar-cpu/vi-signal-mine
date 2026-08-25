"""The **denylist** — hosts that are not worth paying for. A different rule to tier C.

Tier C (:mod:`vsm.mining.tiers`) is *may not*: a compliance blocklist, refused
three times over, never softened. This module is *not worth it*: a budget rule.
Both drop a host, and conflating them would be a mistake — a tier-C refusal is a
finding a human must see, a denylist drop is a saved $0.03.

Four rules, in the order they fire:

1. **The sponsor's and competitors' own product sites.** Derived from the brief's
   ``term_policy`` never-list, because those terms are exactly the brand names the
   output may never repeat (CLAUDE.md hard rule 1). Reading the brand's own site to
   learn what clinicians find difficult is circular; it is also the single easiest
   way to contaminate an unbranded draft with promotional phrasing.
2. **Pharma corporate marketing sites.** Same problem, one level up.
3. **Content farms, SEO-spam health sites and pay-to-publish journals.** The first
   live sweep returned a predatory-adjacent publisher and it looked, in the row,
   exactly like a real journal.
4. **Non-clinical noise** — retail, social, tertiary encyclopedias, and
   institutional repositories that hold a *copy* of a paper better cited from the
   journal or PMC. The first live sweep spent a query on a Danish university
   repository.

Nothing here is silent. Every drop is returned as a :class:`Denial` with the rule
and the reason, the miner writes them into ``fetch_provenance["denylist"]``, and a
count goes into the run notes. *A silent filter is indistinguishable from finding
nothing* — which is the failure mode this module exists to avoid.

The gold list always wins: a host in :data:`vsm.mining.venues.GOLD_DOMAINS` is
never denied, so a clumsy brand-slug rule can never knock out a real venue.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from vsm.mining.tiers import domain_of, registrable_domain
from vsm.mining.venues import is_gold

__all__ = [
    "Denial",
    "DenyRule",
    "PHARMA_CORPORATE",
    "CONTENT_FARMS",
    "PAY_TO_PUBLISH",
    "PAPER_AGGREGATORS",
    "NON_CLINICAL",
    "REPOSITORY_HOST_PREFIXES",
    "brand_domain_slugs",
    "deny_reason",
    "partition",
]

DenyRule = str

#: Manufacturer corporate sites. Not a judgement about the companies — a
#: judgement about the *content*: it is written to promote a product.
PHARMA_CORPORATE: frozenset[str] = frozenset(
    {
        "pfizer.com", "novartis.com", "gsk.com", "merck.com", "msd.com", "lilly.com",
        "astrazeneca.com", "sanofi.com", "jnj.com", "janssen.com", "bms.com", "abbvie.com",
        "amgen.com", "takeda.com", "bayer.com", "boehringer-ingelheim.com", "novonordisk.com",
        "roche.com", "genentech.com", "regeneron.com", "biogen.com", "teva.com", "tevapharm.com",
        "viatris.com", "organon.com", "gilead.com", "vertex.com", "moderna.com", "otsuka.com",
        "otsuka-us.com", "shionogi.com", "salix.com", "bauschhealth.com", "collegiumpharma.com",
        "supernus.com", "alkermes.com", "jazzpharma.com", "ucb.com", "servier.com", "ipsen.com",
        "astellas.com", "daiichisankyo.com", "eisai.com", "sunpharma.com", "drreddys.com",
        "zoetis.com", "csl.com", "grifols.com", "sobi.com", "alnylam.com", "bluebirdbio.com",
        "sarepta.com", "praxismedicines.com", "dyne-tx.com",
    }
)

#: Ad-funded consumer health, SEO farms, coupon and pharmacy retail. Some are
#: perfectly accurate; none of them tells us what clinicians find difficult, and
#: all of them rank highly on exactly the queries Stage 2 runs.
CONTENT_FARMS: frozenset[str] = frozenset(
    {
        "healthline.com", "verywellhealth.com", "verywellmind.com", "webmd.com",
        "medicalnewstoday.com", "everydayhealth.com", "health.com", "prevention.com",
        "self.com", "menshealth.com", "womenshealthmag.com", "wikihow.com", "livestrong.com",
        "healthgrades.com", "goodrx.com", "singlecare.com", "buzzrx.com", "rxlist.com",
        "drugs.com", "ehealthme.com", "patientpop.com", "zocdoc.com", "sharecare.com",
        "medindia.net", "onlymyhealth.com", "practo.com", "webmd.boots.com", "netdoctor.co.uk",
        "healthcentral.com", "thehealthy.com", "eatthis.com", "medicinenet.com",
    }
)

#: Pay-to-publish / rapid-review publishers and the paper-mill adjacent. Judgement
#: call, stated as one: these are not accusations of fraud, they are a decision not
#: to spend a $0.03 fetch on a venue whose editorial screening we cannot vouch for.
#: A specific paper from one of these may still be cited by a human who read it.
PAY_TO_PUBLISH: frozenset[str] = frozenset(
    {
        "mdpi.com", "hindawi.com", "scirp.org", "omicsonline.org", "longdom.org",
        "iiste.org", "sciencepublishinggroup.com", "davidpublisher.com", "ijsr.net",
        "medcraveonline.com", "juniperpublishers.com", "cureus.com", "e-century.us",
        "imedpub.com", "peertechzpublications.com", "austinpublishinggroup.com",
    }
)

#: Copy-of-a-paper hosts. Not publishers and not spam — just the wrong copy: the
#: version of record is at the journal or in PMC, with the licence attached.
PAPER_AGGREGATORS: frozenset[str] = frozenset(
    {
        "researchgate.net", "academia.edu", "semanticscholar.org", "ssrn.com",
        "preprints.org", "scilit.net", "core.ac.uk", "paperity.org", "sci-hub.se",
    }
)

#: Social, retail, tertiary reference and everything the owner meant by
#: "not in places like nautical sea life".
NON_CLINICAL: frozenset[str] = frozenset(
    {
        "pinterest.com", "quora.com", "tiktok.com", "instagram.com", "x.com", "twitter.com",
        "youtube.com", "vimeo.com", "amazon.com", "ebay.com", "walmart.com", "cvs.com",
        "walgreens.com", "chewy.com", "etsy.com", "alibaba.com", "indeed.com", "glassdoor.com",
        "wikipedia.org", "wikidata.org", "britannica.com", "coursehero.com", "studocu.com",
        "quizlet.com", "chegg.com", "scribd.com", "slideshare.net", "medium.com",
        "blogspot.com", "wordpress.com", "substack.com", "tripadvisor.com", "yelp.com",
    }
)

#: Institutional repository host prefixes. A repository copy of a paper is a
#: duplicate of something better cited from the journal or PMC, and it is where the
#: first live sweep wasted two of eighteen rows (``discovery.ucl.ac.uk``,
#: ``vbn.aau.dk``). Matched on the *host label*, so ``pure.au.dk`` is caught and
#: ``purestorage.com`` is not.
REPOSITORY_HOST_PREFIXES: tuple[str, ...] = (
    "discovery", "vbn", "pure", "repository", "repositorio", "eprints", "dspace",
    "escholarship", "openaccess", "research-portal", "researchportal", "orbit", "diva-portal",
    "hal", "theses", "etd", "digitalcommons", "scholarworks", "kar", "eprint",
)

_SLUG = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Denial:
    """One dropped candidate, with the rule that dropped it and why."""

    domain: str
    rule: DenyRule
    reason: str
    url: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"domain": self.domain, "rule": self.rule, "reason": self.reason, "url": self.url}


def brand_domain_slugs(
    brand_terms: Mapping[str, str] | None = None,
    *,
    labels: Sequence[str] = ("ours", "competitor"),
    min_length: int = 5,
) -> frozenset[str]:
    """Brand slugs to match host labels against, from the brief's never-list.

    ``brand_terms`` is the miner's ``term -> label`` map, where the label is
    ``ours`` / ``competitor`` / ``class``. Only ``ours`` and ``competitor`` become
    domain rules: a *class* term ("PAMORA") is not a website.

    Short terms are ignored (``min_length``). ``OIC`` as a domain rule would deny
    every host with "oic" in its name, which is how a filter starts eating the
    gold list.
    """
    slugs: set[str] = set()
    for term, label in (brand_terms or {}).items():
        if str(label) not in labels:
            continue
        slug = _SLUG.sub("", str(term).lower())
        if len(slug) >= min_length:
            slugs.add(slug)
    return frozenset(slugs)


def deny_reason(
    url_or_domain: str,
    *,
    brand_slugs: Iterable[str] = (),
) -> tuple[DenyRule, str] | None:
    """``(rule, reason)`` when this host is not worth paying for, else ``None``."""
    host = domain_of(url_or_domain)
    if not host:
        return ("no_host", "no host in the result — nothing to fetch")
    if is_gold(host):
        return None  # the curated list always wins over every heuristic below
    labels = [p for p in host.split(".") if p]
    suffixes = {".".join(labels[i:]) for i in range(len(labels))}

    for slug in brand_slugs:
        if slug and slug in labels:
            return (
                "brand_site",
                f"a sponsor or competitor product site ({host}) — its brand name is on the "
                "never-say list, so reading it is both circular and a contamination risk",
            )
    if suffixes & PHARMA_CORPORATE:
        return ("pharma_corporate", f"manufacturer corporate marketing site ({host})")
    if suffixes & CONTENT_FARMS:
        return (
            "content_farm",
            f"ad-funded consumer health / SEO site ({host}) — ranks on these queries, carries no "
            "clinician signal",
        )
    if suffixes & PAY_TO_PUBLISH:
        return (
            "pay_to_publish",
            f"pay-to-publish or preprint-aggregator publisher ({host}) — editorial screening we "
            "cannot vouch for; a human may still cite a specific paper",
        )
    if suffixes & NON_CLINICAL:
        return ("non_clinical", f"non-clinical or tertiary source ({host})")
    if suffixes & PAPER_AGGREGATORS:
        return (
            "repository_duplicate",
            f"paper aggregator ({host}) — cite the version of record at the journal or in PMC",
        )
    if labels and labels[0] in REPOSITORY_HOST_PREFIXES:
        return (
            "repository_duplicate",
            f"institutional repository ({host}) — a copy of a paper that should be cited from the "
            "journal or PMC",
        )
    return None


def partition(
    candidates: Sequence[Any],
    *,
    url_of: Any = None,
    brand_slugs: Iterable[str] = (),
) -> tuple[list[Any], list[Denial]]:
    """Split candidates into (kept, denied). ``url_of`` extracts the URL.

    Order is preserved on both sides so the caller's spend order does not change.
    """
    getter = url_of or (lambda item: getattr(item, "url", "") or str(item))
    slugs = list(brand_slugs)
    kept: list[Any] = []
    denied: list[Denial] = []
    for item in candidates:
        url = str(getter(item) or "")
        verdict = deny_reason(url, brand_slugs=slugs)
        if verdict is None:
            kept.append(item)
        else:
            rule, reason = verdict
            denied.append(Denial(domain=registrable_domain(domain_of(url)) or url, rule=rule, reason=reason, url=url[:300]))
    return kept, denied
