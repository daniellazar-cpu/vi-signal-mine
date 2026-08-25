"""The **gold list** — where a campaign is allowed to spend, and where it looks first.

    *"We look for web forums and/or references already around a drug or competitor
    drug … create a gold list of places to scrape from first rather than reading
    straight from the brand website or some silly mistakes that will spend money.
    ADHD could be very broad usage but only several places will be relevant, same
    with cancer — make sure our search will be in relevant platforms and channels
    and not in places like nautical sea life."*

The first live Stage-2 sweep was an open Google search. It found the AGA journals,
PMC and AAFP — and also a Danish university repository and a pay-to-publish
journal, and it had no idea which was which. This module is the difference: a
hand-checked venue registry, routed by therapeutic area, that the miner scopes its
SERP queries to *before* it spends anything on an open search.

Three separate axes, kept separate on purpose:

* **collection tier** (A/B/C, PRD §9.1) — *may* we collect automatically. Tier C
  is the blocklist in :mod:`vsm.mining.tiers` and is never softened here.
* **the gold list** (this module) — *is it worth paying for*. A venue can be
  perfectly collectable and still be off the list.
* **the denylist** (:mod:`vsm.mining.denylist`) — *actively not worth paying
  for*: brand sites, pharma corporate marketing, content farms, repository
  duplicates.

Only a gold-list host is ever page-fetched through the Web Unlocker. A SERP call
is $0.0015; an Unlocker fetch is $0.03 — twenty times more. Everything else may
contribute public search-result metadata and nothing else. That ratio is the whole
cost argument, and it is enforced in :mod:`vsm.mining.miner`.

**Every domain below was verified on 2026-08-02** by a plain ``httpx`` GET of
``https://<domain>/robots.txt`` (no Bright Data key, no proxy, our own honest
User-Agent). ``robots`` records what that GET actually returned — including the
four hosts that answered ``403``/``406`` to our agent and the one that has no
robots.txt at all. Nothing here was written from memory: three candidates
(``chest.org`` TLS handshake failure, ``accessdata.fda.gov`` connection reset,
``dailystrength.org`` connect timeout) could not be reached and were **dropped**
rather than listed on faith.

The recorded ``robots`` string is documentation, not enforcement:
:class:`vsm.mining.robots.RobotsCache` re-fetches robots.txt at run time and
that live answer is what decides a fetch. A venue whose robots.txt we could not
read is therefore metadata-only in practice — absence of evidence is not
permission.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping, Sequence

from vsm.mining.tiers import VenueTier, domain_of, registrable_domain

__all__ = [
    "VenueKind",
    "Venue",
    "GOLD_VENUES",
    "GOLD_DOMAINS",
    "VERIFIED_AT",
    "UNVERIFIED_DROPPED",
    "AREAS",
    "RECENCY_FILTERED_KINDS",
    "EVERGREEN_KINDS",
    "BAND_CONVERSATION",
    "BAND_OPINION",
    "BAND_SUBSTRATE",
    "BAND_PATTERN",
    "areas_for_text",
    "areas_for_cluster",
    "venue_for",
    "is_gold",
    "gold_page_fetch_allowed",
    "venues_for",
    "site_tokens",
    "catalogue_entries",
    "kind_of",
    "is_recency_filtered",
]

#: The day every domain below was resolved and its robots.txt read.
VERIFIED_AT = "2026-08-02"

VenueKind = Literal[
    "evidence",
    "guideline_body",
    "hcp_discussion",
    "patient_community",
    "regulatory",
    "drug_reference",
]

#: Kinds where *staleness is real*: a 2019 forum thread is not current practice.
#: These carry the Stage-2 recency window (see :mod:`vsm.mining.recency`).
RECENCY_FILTERED_KINDS: frozenset[str] = frozenset({"hcp_discussion", "patient_community"})

#: **Spend bands.** What Stage 2 is actually buying, in the owner's order:
#:
#: 1. *conversation* — what clinicians and patients **say**: named clinical
#:    subreddits, Student Doctor Network, public specialty forums, then patient
#:    communities under the §9.3 themes-only rule.
#: 2. *opinion / KOL* — named clinicians publishing publicly, conference
#:    commentary, trade press, society and FOAM blogs.
#: 3. *substrate* — evidence, guidelines, labels. Still essential, but as the
#:    material an article is **written from**, not the signal being mined. Stage 5's
#:    corpus already covers the evidence side; Stage 2 is not where we discover that
#:    the AGA guideline exists.
#:
#: The band drives *query order and budget*. It is a separate axis from the recency
#: window, which is keyed on ``kind`` — trade press is band 2 and still date-windowed.
BAND_CONVERSATION = 1
BAND_OPINION = 2
BAND_SUBSTRATE = 3

#: How the per-cluster query budget is spent across the bands, as a repeating
#: pattern. Read it left to right: the first query is conversation, the second
#: opinion, the third substrate, the fourth conversation again — so a four-query
#: cluster spends **half** its budget on what people are saying and a quarter each
#: on opinion and substrate, and a one-query cluster spends it all on conversation.
#: A band with no venues for this campaign is skipped, not left idle.
BAND_PATTERN: tuple[int, ...] = (1, 2, 3, 1)

#: Order **within** a band. What clinicians say comes before what patients say
#: (both are conversation); a guideline body comes before a journal (both are
#: substrate). Patient community is never dropped — §9.3 governs how it is read,
#: not whether it is read.
KIND_ORDER: Mapping[str, int] = {
    "hcp_discussion": 0,
    "patient_community": 1,
    "guideline_body": 2,
    "evidence": 3,
    "regulatory": 4,
    "drug_reference": 5,
}

_DEFAULT_BAND_BY_KIND: Mapping[str, int] = {
    "hcp_discussion": BAND_CONVERSATION,
    "patient_community": BAND_CONVERSATION,
    "evidence": BAND_SUBSTRATE,
    "guideline_body": BAND_SUBSTRATE,
    "regulatory": BAND_SUBSTRATE,
    "drug_reference": BAND_SUBSTRATE,
}

#: Kinds where the test is **current edition, not recent date**. The AGA OIC
#: guideline is 2019 and is the current one; a 90-day window would delete the
#: entire evidence base and keep last week's chatter. Never date-filter these.
EVERGREEN_KINDS: frozenset[str] = frozenset(
    {"evidence", "guideline_body", "regulatory", "drug_reference"}
)

#: Candidates that did not answer and are therefore **not** in the registry.
#: Recorded so the next person does not "helpfully" add them back from memory.
UNVERIFIED_DROPPED: tuple[tuple[str, str], ...] = (
    ("chest.org", "TLS handshake failed (TLSV1_ALERT_INTERNAL_ERROR) on 2026-08-02, apex and www"),
    ("accessdata.fda.gov", "connection reset by peer on 2026-08-02 — use fda.gov + dailymed instead"),
    ("dailystrength.org", "connect timeout on 2026-08-02"),
    ("sensible-med.com", "does not resolve (NXDOMAIN) on 2026-08-02"),
)


@dataclass(frozen=True)
class Venue:
    """One hand-checked place worth spending a query on."""

    domain: str
    name: str
    kind: VenueKind
    collection_tier: VenueTier
    api_available: bool
    tos_posture: str
    #: therapeutic areas this venue is *strong* for; ``("*",)`` means general.
    areas: tuple[str, ...]
    #: what ``GET https://<domain>/robots.txt`` returned on :data:`VERIFIED_AT`.
    robots: str
    #: ``(area, path)`` scopes — a ``site:`` token narrower than the domain, e.g.
    #: ``("gastroenterology", "reddit.com/r/gastroenterology")``. ``*`` = always.
    path_scopes: tuple[tuple[str, str], ...] = ()
    #: independent of collection tier (PRD §9.1): Doximity is C to collect and
    #: still a paid distribution channel.
    distribution_mode: str | None = None
    patient_generated: bool = False
    #: belt-and-braces gate on top of robots.txt, for venues that block AI
    #: crawlers by name. Metadata-only when ``False``, whatever robots.txt says.
    page_fetch_ok: bool = True
    #: spend band — 1 conversation, 2 opinion/KOL, 3 substrate. ``0`` = derive from
    #: ``kind``; set explicitly where the kind is too coarse (trade press is
    #: ``hcp_discussion`` by kind but opinion by band).
    band: int = 0
    notes: str = ""

    @property
    def registrable(self) -> str:
        return registrable_domain(self.domain)

    @property
    def spend_band(self) -> int:
        return self.band or _DEFAULT_BAND_BY_KIND.get(self.kind, BAND_SUBSTRATE)

    @property
    def recency_filtered(self) -> bool:
        return self.kind in RECENCY_FILTERED_KINDS

    def serves(self, areas: Sequence[str]) -> bool:
        """``True`` when this venue is general, or strong for one of ``areas``."""
        if "*" in self.areas:
            return True
        return any(area in self.areas for area in areas)

    def as_catalogue_entry(self) -> dict[str, Any]:
        """The dict shape the tier/catalogue helpers and Stage 2 already speak."""
        return {
            "venue_id": self.domain.replace(".", "-"),
            "name": self.name,
            "domain": self.domain,
            "collection_tier": self.collection_tier,
            "distribution_mode": self.distribution_mode,
            "api_available": self.api_available,
            "tos_posture": self.tos_posture,
            "patient_generated": self.patient_generated,
            "kind": self.kind,
            "spend_band": self.spend_band,
            "areas": list(self.areas),
            "robots_verified": f"{self.robots} (checked {VERIFIED_AT})",
            "gold": True,
        }


# --------------------------------------------------------------------------- #
# therapeutic areas                                                            #
# --------------------------------------------------------------------------- #

#: Area slugs. Deliberately coarse — this routes *queries*, it is not a taxonomy.
AREAS: tuple[str, ...] = (
    "gastroenterology",
    "oncology",
    "hematology",
    "neurology",
    "headache",
    "cardiology",
    "nephrology",
    "endocrinology",
    "rheumatology",
    "infectious_disease",
    "pediatrics",
    "psychiatry",
    "adhd",
    "primary_care",
    "pain",
    "palliative",
    "pulmonology",
    "sleep",
    "urology",
    "emergency",
)

#: Lower-cased substrings that route a cluster to an area. Matched against the
#: cluster label, its terms, and anything else the caller passes in.
AREA_KEYWORDS: Mapping[str, tuple[str, ...]] = {
    "gastroenterology": (
        "constipation", "gastro", "bowel", "colitis", "crohn", "ibd", "ibs", "gerd",
        "hepat", "liver", "pancrea", "endoscop", "dyspepsia", "gastroparesis", "laxative",
        "oic", "colorect",
    ),
    "oncology": (
        "cancer", "oncolog", "tumour", "tumor", "carcinoma", "melanoma", "chemotherap",
        "metasta", "immunotherap", "sarcoma", "neoplas",
    ),
    "hematology": (
        "leukaem", "leukem", "lymphoma", "myeloma", "sickle", "haemophilia", "hemophilia",
        "anaemia", "anemia", "thrombo", "anticoagul", "haematolog", "hematolog", "transfus",
    ),
    "neurology": (
        "neurolog", "epilep", "seizure", "multiple sclerosis", "parkinson", "tremor",
        "alzheimer", "dementia", "neuropath", "myasthen", "stroke", "duchenne", "als ",
    ),
    "headache": ("migraine", "headache", "cgrp", "aura", "triptan"),
    "cardiology": (
        "cardio", "heart failure", "atrial", "hypertens", "lipid", "cholesterol",
        "myocardial", "arrhythm", "statin", "hfref", "hfpef",
    ),
    "nephrology": ("kidney", "renal", "nephro", "dialysis", "ckd", "albuminuria", "egfr"),
    "endocrinology": (
        "diabet", "insulin", "glp-1", "obesity", "thyroid", "endocrin", "hba1c",
        "osteoporos", "testosterone",
    ),
    "rheumatology": (
        "rheumat", "arthritis", "lupus", "gout", "psoriatic", "spondyl", "vasculitis",
        "fibromyalgia", "sjogren",
    ),
    "infectious_disease": (
        "infect", "antibiotic", "antimicrob", "hiv", "sepsis", "vaccin", "hepatitis c",
        "tuberculos", "covid", "influenza", "c. diff", "stewardship",
    ),
    "pediatrics": ("paediatr", "pediatr", "child", "infant", "adolescent", "neonat"),
    "psychiatry": (
        "depress", "schizophren", "bipolar", "anxiety", "psychiatr", "ssri", "antipsychot",
        "suicid", "ptsd", "substance use",
    ),
    "adhd": ("adhd", "attention deficit", "attention-deficit", "hyperactivity", "stimulant"),
    "primary_care": ("primary care", "family medicine", "general practice", "screening", "preventive"),
    "pain": ("pain", "opioid", "analgesi", "nsaid", "morphine", "oxycodone", "buprenorphine"),
    "palliative": ("palliative", "hospice", "end of life", "advanced cancer", "supportive care"),
    "pulmonology": ("asthma", "copd", "pulmonary", "respirat", "bronch", "cystic fibrosis"),
    "sleep": ("insomnia", "sleep apnoea", "sleep apnea", "narcoleps", "circadian"),
    "urology": ("urolog", "prostate", "bladder", "incontinence", "erectile"),
    "emergency": ("emergency", "resuscitat", "critical care", "icu", "intensive care", "sepsis"),
}


def areas_for_text(*texts: Any) -> tuple[str, ...]:
    """Route free text to therapeutic areas, most-matched first.

    Multi-area on purpose: *"opioid-induced constipation in advanced cancer"* is
    a GI question, a pain question and a palliative question at once, and the
    gold list should reflect all three rather than pick one.
    """
    haystack = " ".join(str(t or "") for t in _flatten(texts)).lower()
    if not haystack.strip():
        return ()
    scored: list[tuple[int, int, str]] = []
    for index, area in enumerate(AREAS):
        hits = sum(1 for word in AREA_KEYWORDS.get(area, ()) if word in haystack)
        if hits:
            scored.append((-hits, index, area))
    return tuple(area for _hits, _i, area in sorted(scored))


def areas_for_cluster(cluster: Mapping[str, Any]) -> tuple[str, ...]:
    """Areas for one lexicon cluster. Both miners route on exactly this."""
    return areas_for_text(cluster.get("label"), cluster.get("terms"))


def _flatten(value: Any) -> Iterable[Any]:
    if isinstance(value, (str, bytes)) or value is None:
        yield value
        return
    if isinstance(value, Mapping):
        yield from _flatten(list(value.values()))
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _flatten(item)
        return
    yield value


# --------------------------------------------------------------------------- #
# the registry                                                                 #
# --------------------------------------------------------------------------- #

_EVIDENCE: tuple[Venue, ...] = (
    Venue(
        domain="pubmed.ncbi.nlm.nih.gov", name="PubMed", kind="evidence",
        collection_tier="A", api_available=True,
        tos_posture="official NCBI E-utilities API; public abstracts",
        areas=("*",),
        robots="200; User-agent: * allows /, crawl-delay 1, /api and /rss disallowed",
    ),
    Venue(
        domain="pmc.ncbi.nlm.nih.gov", name="PubMed Central", kind="evidence",
        collection_tier="A", api_available=True,
        tos_posture="official NCBI API; open-access full text (per-article licence still applies)",
        areas=("*",),
        robots="200; Disallow: / with an explicit Allow: /articles/ — article pages permitted, "
               "the rest of the host is not",
    ),
    Venue(
        domain="europepmc.org", name="Europe PMC", kind="evidence",
        collection_tier="A", api_available=True,
        tos_posture="official REST API; abstracts and OA full text",
        areas=("*",),
        robots="200; Disallow: / for User-agent: *, crawl-delay 5 — metadata only, use the API",
        page_fetch_ok=False,
        notes="robots.txt blanket-disallows crawling; the REST API is the sanctioned route.",
    ),
    Venue(
        domain="clinicaltrials.gov", name="ClinicalTrials.gov", kind="evidence",
        collection_tier="A", api_available=True,
        tos_posture="official API v2; US federal registry, public domain",
        areas=("*",),
        robots="200; allows /, crawl-delay 1, /api/ and /search? disallowed",
    ),
    Venue(
        domain="cochranelibrary.com", name="Cochrane Library", kind="evidence",
        collection_tier="A", api_available=False,
        tos_posture="public abstracts; Wiley subscription for full text — no paywall bypass",
        areas=("*",),
        robots="200; no User-agent: * group at all, and named AI crawlers (Claude, PerplexityBot, "
               "Bytespider, Amazonbot, Applebot) are Disallow: /",
        page_fetch_ok=False,
        notes="No * group means our agent is not addressed, but the file's intent toward automated "
              "readers is explicit. Metadata only; a human reads the review.",
    ),
    Venue(
        domain="medrxiv.org", name="medRxiv", kind="evidence",
        collection_tier="A", api_available=True,
        tos_posture="public preprints, official API; NOT peer reviewed — label it",
        areas=("*",),
        robots="200; allows /, crawl-delay 7",
        notes="Preprint. Never cite as evidence without saying it is unreviewed.",
    ),
    Venue(
        domain="biorxiv.org", name="bioRxiv", kind="evidence",
        collection_tier="A", api_available=True,
        tos_posture="public preprints, official API; NOT peer reviewed — label it",
        areas=("*",),
        robots="200; allows /, crawl-delay 7",
        notes="Preprint. Never cite as evidence without saying it is unreviewed.",
    ),
    Venue(
        domain="cancer.gov", name="NCI (PDQ summaries)", kind="evidence",
        collection_tier="A", api_available=True,
        tos_posture="US federal, public domain; PDQ has an API",
        areas=("oncology", "palliative"),
        robots="200; User-agent: * present with no rules — nothing disallowed",
    ),
    Venue(
        domain="gastrojournal.org", name="Gastroenterology (AGA journal)", kind="evidence",
        collection_tier="B", api_available=False,
        tos_posture="publisher site; abstracts public, full text subscription — no paywall bypass",
        areas=("gastroenterology",),
        robots="200; allows /, /action /search /help disallowed",
    ),
    Venue(
        domain="diabetesjournals.org", name="ADA journals (Diabetes Care, Standards of Care)",
        kind="evidence", collection_tier="B", api_available=False,
        tos_posture="publisher site; Standards of Care is free to read",
        areas=("endocrinology",),
        robots="200; allows /, infrastructure paths disallowed",
    ),
    Venue(
        domain="ninds.nih.gov", name="NINDS", kind="evidence",
        collection_tier="B", api_available=False,
        tos_posture="US federal, public domain",
        areas=("neurology", "headache"),
        robots="403 to our User-Agent on 2026-08-02 — unreadable, so treated as disallow "
               "(metadata only)",
        page_fetch_ok=False,
    ),
)

_GUIDELINES: tuple[Venue, ...] = (
    Venue(
        domain="gastro.org", name="American Gastroenterological Association (AGA)",
        kind="guideline_body", collection_tier="B", api_available=False,
        tos_posture="public web; robots.txt blanket-disallows non-search agents",
        areas=("gastroenterology",),
        robots="200; Disallow: / for User-agent: *, crawl-delay 15 (Googlebot/Bingbot allowed) "
               "— metadata only for us",
        page_fetch_ok=False,
        notes="The AGA OIC guideline is the anchor reference for this campaign and is still the "
              "current edition (2019). Read the PDF via PMC or by hand — not through the unlocker.",
    ),
    Venue(
        domain="gi.org", name="American College of Gastroenterology (ACG)",
        kind="guideline_body", collection_tier="B", api_available=False,
        tos_posture="public web; clinical guidelines free to read",
        areas=("gastroenterology",),
        robots="200; User-agent: * with an empty Disallow (allow all) except /*?rul",
    ),
    Venue(
        domain="aan.com", name="American Academy of Neurology (AAN)",
        kind="guideline_body", collection_tier="B", api_available=False,
        tos_posture="public web; guideline summaries free",
        areas=("neurology", "headache"),
        robots="200; allows /, only /home-page/ disallowed",
    ),
    Venue(
        domain="americanheadachesociety.org", name="American Headache Society (AHS)",
        kind="guideline_body", collection_tier="B", api_available=False,
        tos_posture="public web; position statements free",
        areas=("headache",),
        robots="200; allows /, build paths (/cpresources/, /vendor/, /cache/) disallowed",
    ),
    Venue(
        domain="acc.org", name="American College of Cardiology (ACC)",
        kind="guideline_body", collection_tier="B", api_available=False,
        tos_posture="public web; guideline hub free, member sections gated",
        areas=("cardiology",),
        robots="200; allows / BUT /guideline-recommendations and member sections are Disallow — "
               "the guideline hub itself is off limits to crawlers",
        notes="robots.txt disallows exactly the path you want. SERP metadata routes a human there; "
              "the run layer will not fetch it.",
    ),
    Venue(
        domain="professional.heart.org", name="American Heart Association (professional)",
        kind="guideline_body", collection_tier="B", api_available=False,
        tos_posture="public web; statements and guidelines free",
        areas=("cardiology",),
        robots="200; allows /, Sitecore CMS paths disallowed",
    ),
    Venue(
        domain="asco.org", name="American Society of Clinical Oncology (ASCO)",
        kind="guideline_body", collection_tier="B", api_available=False,
        tos_posture="public web; guidelines free to read",
        areas=("oncology", "palliative"),
        robots="403 to our User-Agent on 2026-08-02 (apex and www) — unreadable, treated as "
               "disallow (metadata only)",
        page_fetch_ok=False,
    ),
    Venue(
        domain="nccn.org", name="NCCN", kind="guideline_body",
        collection_tier="B", api_available=False,
        tos_posture="public web; guidelines free after registration — registration is NOT a login "
                    "we hold, so treat as metadata only",
        areas=("oncology", "hematology"),
        robots="200; allows /, guideline-process and compendium admin paths disallowed",
        page_fetch_ok=False,
        notes="The guideline PDFs sit behind a free account. We do not create accounts to collect.",
    ),
    Venue(
        domain="hematology.org", name="American Society of Hematology (ASH)",
        kind="guideline_body", collection_tier="B", api_available=False,
        tos_posture="public web; ASH clinical practice guidelines free",
        areas=("hematology", "oncology"),
        robots="200 (read at www.hematology.org; the apex cert chain fails verification); allows /, "
               "Sitecore paths disallowed",
    ),
    Venue(
        domain="kdigo.org", name="KDIGO", kind="guideline_body",
        collection_tier="B", api_available=False,
        tos_posture="public web; guidelines free PDFs",
        areas=("nephrology",),
        robots="200; allows /, only /wp-admin/ disallowed",
    ),
    Venue(
        domain="diabetes.org", name="American Diabetes Association (ADA)",
        kind="guideline_body", collection_tier="B", api_available=False,
        tos_posture="public web; Standards of Care free",
        areas=("endocrinology",),
        robots="200; allows /, Drupal infrastructure paths disallowed",
    ),
    Venue(
        domain="rheumatology.org", name="American College of Rheumatology (ACR)",
        kind="guideline_body", collection_tier="B", api_available=False,
        tos_posture="public web; guidelines free",
        areas=("rheumatology",),
        robots="200; global Disallow: /api and /documentation, no other * restrictions; several "
               "named SEO/AI bots blocked",
    ),
    Venue(
        domain="idsociety.org", name="Infectious Diseases Society of America (IDSA)",
        kind="guideline_body", collection_tier="B", api_available=False,
        tos_posture="public web; guidelines free",
        areas=("infectious_disease",),
        robots="200; allows /, three internal folders disallowed",
    ),
    Venue(
        domain="aap.org", name="American Academy of Pediatrics (AAP)",
        kind="guideline_body", collection_tier="B", api_available=False,
        tos_posture="public web; policy statements free, some content member-gated",
        areas=("pediatrics", "adhd"),
        robots="200; empty Disallow (allow all) except /en/my-account/login/* and /en/search/*",
    ),
    Venue(
        domain="psychiatry.org", name="American Psychiatric Association (APA)",
        kind="guideline_body", collection_tier="B", api_available=False,
        tos_posture="public web; practice guidelines partly free",
        areas=("psychiatry", "adhd"),
        robots="200; allows /, dashboard and a few documents disallowed",
    ),
    Venue(
        domain="aafp.org", name="American Academy of Family Physicians (AAFP)",
        kind="guideline_body", collection_tier="B", api_available=False,
        tos_posture="public web; AFP articles largely free",
        areas=("primary_care", "*"),
        robots="200; allows /, /login, /chapter and AFP accessory paths disallowed",
    ),
    Venue(
        domain="acponline.org", name="American College of Physicians (ACP)",
        kind="guideline_body", collection_tier="B", api_available=False,
        tos_posture="public web; clinical guidelines free",
        areas=("primary_care", "*"),
        robots="200; allows /, Drupal infrastructure paths disallowed",
    ),
    Venue(
        domain="nice.org.uk", name="NICE (UK)", kind="guideline_body",
        collection_tier="A", api_available=True,
        tos_posture="public web, NICE syndication API available; Open Government Licence terms",
        areas=("*",),
        robots="200; allows /, crawl-delay 1, two CKS licence pages disallowed",
    ),
    Venue(
        domain="sign.ac.uk", name="SIGN (Scotland)", kind="guideline_body",
        collection_tier="B", api_available=False,
        tos_posture="public web; guidelines free PDFs",
        areas=("*",),
        robots="404 — no robots.txt exists (2026-08-02). RobotsCache treats an unreadable file as "
               "disallow, so this is metadata-only until a human decides otherwise",
        page_fetch_ok=False,
    ),
    Venue(
        domain="uspreventiveservicestaskforce.org", name="USPSTF",
        kind="guideline_body", collection_tier="A", api_available=False,
        tos_posture="US federal advisory body; recommendations public domain",
        areas=("primary_care", "*"),
        robots="200; allows /, crawl-delay 5, admin and user paths disallowed",
    ),
    Venue(
        domain="thoracic.org", name="American Thoracic Society (ATS)",
        kind="guideline_body", collection_tier="B", api_available=False,
        tos_posture="public web; guidelines free",
        areas=("pulmonology",),
        robots="200; allows /, only asset folders disallowed",
    ),
    Venue(
        domain="aasm.org", name="American Academy of Sleep Medicine (AASM)",
        kind="guideline_body", collection_tier="B", api_available=False,
        tos_posture="public web; practice parameters partly free",
        areas=("sleep",),
        robots="200; allows /, crawl-delay 10, WordPress admin paths disallowed",
    ),
    Venue(
        domain="auanet.org", name="American Urological Association (AUA)",
        kind="guideline_body", collection_tier="B", api_available=False,
        tos_posture="public web; guidelines free",
        areas=("urology",),
        robots="200 (read at www.auanet.org; the apex certificate does not cover the apex name); "
               "single * group, nothing disallowed",
    ),
    Venue(
        domain="guidelinecentral.com", name="Guideline Central", kind="guideline_body",
        collection_tier="B", api_available=False,
        tos_posture="commercial aggregator; summaries free, some products paid",
        areas=("*",),
        robots="200; allows /, cart/search/feed paths disallowed",
        notes="Aggregator, not an issuing body. Useful for finding *that* a guideline exists; the "
              "claim must be traced to the society's own current edition before it is cited.",
    ),
)

_REGULATORY: tuple[Venue, ...] = (
    Venue(
        domain="dailymed.nlm.nih.gov", name="DailyMed (FDA labels)", kind="regulatory",
        collection_tier="A", api_available=True,
        tos_posture="official NLM API; SPL labelling, public domain",
        areas=("*",),
        robots="200 but the body is the site's HTML page, not a robots file (2026-08-02) — i.e. no "
               "rules are expressed; the API is the sanctioned route anyway",
    ),
    Venue(
        domain="fda.gov", name="FDA (Drugs@FDA, labels, safety)", kind="regulatory",
        collection_tier="A", api_available=True,
        tos_posture="US federal, public domain; openFDA API",
        areas=("*",),
        robots="apex returns 404; www.fda.gov returns 200 — allows /, crawl-delay 30, /health and "
               "Drupal paths disallowed",
    ),
    Venue(
        domain="ema.europa.eu", name="European Medicines Agency", kind="regulatory",
        collection_tier="A", api_available=False,
        tos_posture="EU agency, reuse permitted with attribution",
        areas=("*",),
        robots="200; allows /, Drupal infrastructure paths disallowed",
    ),
)

_DRUG_REFERENCE: tuple[Venue, ...] = (
    Venue(
        domain="medlineplus.gov", name="MedlinePlus", kind="drug_reference",
        collection_tier="A", api_available=True,
        tos_posture="NLM, public domain; web service available",
        areas=("*",),
        robots="200; allows /, CGI and log paths disallowed",
    ),
    Venue(
        domain="merckmanuals.com", name="Merck Manual (Professional)", kind="drug_reference",
        collection_tier="B", api_available=False,
        tos_posture="free professional reference; publisher terms restrict republication",
        areas=("*",),
        robots="200; allows /, crawl-delay 5, Sitecore paths disallowed",
        notes="Published by a manufacturer but editorially independent and not promotional. Not on "
              "the denylist for that reason — the corporate site merck.com is.",
    ),
    Venue(
        domain="empr.com", name="MPR (Monthly Prescribing Reference)", kind="drug_reference",
        collection_tier="B", api_available=False,
        tos_posture="public web; Content-Signal: search=yes, ai-train=no, use=reference",
        areas=("*",),
        robots="200; User-agent: * Allow: / with Content-Signal search=yes,ai-train=no,use=reference; "
               "named AI crawlers (GPTBot, ClaudeBot, CCBot, …) blocked",
        notes="Our use is reference, not training, and our agent is not one of the named crawlers.",
    ),
)

#: Named clinical subreddits. Google honours ``site:reddit.com/r/<name>``, so this
#: is what turns "Reddit" from a firehose into a targeted venue.
REDDIT_SUBREDDITS: tuple[tuple[str, str], ...] = (
    ("*", "reddit.com/r/medicine"),
    ("*", "reddit.com/r/FamilyMedicine"),
    ("*", "reddit.com/r/Residency"),
    ("*", "reddit.com/r/Noctor"),
    ("*", "reddit.com/r/InternalMedicine"),
    ("gastroenterology", "reddit.com/r/gastroenterology"),
    ("oncology", "reddit.com/r/oncology"),
    ("hematology", "reddit.com/r/hematology"),
    ("neurology", "reddit.com/r/Neurology"),
    ("headache", "reddit.com/r/migraine"),
    ("cardiology", "reddit.com/r/Cardiology"),
    ("nephrology", "reddit.com/r/nephrology"),
    ("endocrinology", "reddit.com/r/endocrinology"),
    ("rheumatology", "reddit.com/r/rheumatology"),
    ("infectious_disease", "reddit.com/r/ID_Medicine"),
    ("pediatrics", "reddit.com/r/pediatrics"),
    ("psychiatry", "reddit.com/r/Psychiatry"),
    ("adhd", "reddit.com/r/ADHD"),
    ("adhd", "reddit.com/r/ADHDers"),
    ("pain", "reddit.com/r/painmanagement"),
    ("palliative", "reddit.com/r/hospice"),
    ("pulmonology", "reddit.com/r/pulmonology"),
    ("sleep", "reddit.com/r/SleepApnea"),
    ("urology", "reddit.com/r/Urology"),
    ("emergency", "reddit.com/r/emergencymedicine"),
    ("primary_care", "reddit.com/r/FamilyMedicine"),
)

_HCP_DISCUSSION: tuple[Venue, ...] = (
    Venue(
        domain="reddit.com", name="Reddit (named clinical subreddits)", kind="hcp_discussion",
        collection_tier="B", api_available=True,
        tos_posture="public web; robots.txt blanket-disallows crawlers and the Public Content "
                    "Policy governs reuse — search metadata only, no page fetch",
        areas=("*",),
        robots="200; User-agent: * Disallow: / — Reddit's Public Content Policy is cited in the "
               "file itself",
        path_scopes=REDDIT_SUBREDDITS,
        distribution_mode="organic_participation",
        page_fetch_ok=False,
        notes="Never page-fetched. The subreddit scopes are what make the SERP query useful; the "
              "row keeps title/snippet only. Author identifiers are stripped either way (§9.3).",
    ),
    Venue(
        domain="studentdoctor.net", name="Student Doctor Network forums", kind="hcp_discussion",
        collection_tier="B", api_available=False,
        tos_posture="public forum; Content-Signal: search=yes, ai-train=no, use=reference",
        areas=("*",),
        robots="200; User-agent: * Allow: / with Content-Signal search=yes,ai-train=no,"
               "use=reference; named AI crawlers blocked by name",
        distribution_mode="organic_participation",
        notes="Trainee-heavy. Good for what is confusing, weaker for what attendings actually do.",
    ),
    # --------------------------------------------- band 2: opinion / KOL / press
    Venue(
        domain="medpagetoday.com", name="MedPage Today", kind="hcp_discussion",
        collection_tier="B", api_available=False,
        tos_posture="public trade press; a long list of named AI crawlers is blocked, our agent is "
                    "not among them",
        areas=("*",),
        robots="200; allows /, four utility paths disallowed; ~100 named AI agents Disallow: /",
        band=BAND_OPINION,
    ),
    Venue(
        domain="healio.com", name="Healio", kind="hcp_discussion",
        collection_tier="B", api_available=False,
        tos_posture="public trade press; some content registration-gated",
        areas=("*",),
        robots="200; allows /, internal and user paths disallowed",
        band=BAND_OPINION,
    ),
    Venue(
        domain="clinicaladvisor.com", name="Clinical Advisor (NP/PA)", kind="hcp_discussion",
        collection_tier="B", api_available=False,
        tos_posture="public web; Content-Signal: search=yes, ai-train=no, use=reference",
        areas=("primary_care", "*"),
        robots="200; User-agent: * Allow: / with Content-Signal search=yes,ai-train=no,use=reference",
        band=BAND_OPINION,
    ),
    Venue(
        domain="medcentral.com", name="MedCentral", kind="hcp_discussion",
        collection_tier="B", api_available=False,
        tos_posture="public web; robots.txt unreadable to our agent, so metadata only",
        areas=("pain", "*"),
        robots="403 to our User-Agent on 2026-08-02 — unreadable, treated as disallow",
        page_fetch_ok=False, band=BAND_OPINION,
    ),
    Venue(
        domain="statnews.com", name="STAT News", kind="hcp_discussion",
        collection_tier="B", api_available=False,
        tos_posture="trade press; some content subscription-gated — no paywall bypass",
        areas=("*",),
        robots="200; allows /, WordPress and search paths disallowed; named AI crawlers blocked",
        band=BAND_OPINION,
        notes="Reporting and named-author opinion. Journalism, not evidence.",
    ),
    Venue(
        domain="kevinmd.com", name="KevinMD", kind="hcp_discussion",
        collection_tier="B", api_available=False,
        tos_posture="public web; physician-authored opinion, republished with permission",
        areas=("*",),
        robots="200; User-agent: * with an empty Disallow — allow all (and AI agents explicitly "
               "Allow: /)",
        band=BAND_OPINION,
        notes="Named clinicians writing in their own voice — the clearest opinion/KOL surface on "
              "the open web. One author's view, never a position statement.",
    ),
    Venue(
        domain="emcrit.org", name="EMCrit", kind="hcp_discussion",
        collection_tier="B", api_available=False,
        tos_posture="public FOAM blog; CC-licensed in part; GPTBot/ClaudeBot/CCBot blocked by name",
        areas=("emergency", "pain"),
        robots="200; User-agent: * empty Disallow (allow all) except /wp-content/uploads/",
        band=BAND_OPINION,
        notes="Individual clinician commentary, not a society position. Treat as opinion.",
    ),
    Venue(
        domain="litfl.com", name="Life in the Fast Lane", kind="hcp_discussion",
        collection_tier="B", api_available=False,
        tos_posture="public FOAM blog",
        areas=("emergency",),
        robots="200; allows /, only /wp-admin/ disallowed",
        band=BAND_OPINION,
        notes="Individual clinician commentary, not a society position.",
    ),
    Venue(
        domain="thennt.com", name="The NNT", kind="hcp_discussion",
        collection_tier="B", api_available=False,
        tos_posture="public web; clinician-authored evidence appraisal",
        areas=("*",),
        robots="200; User-agent: * empty Disallow — allow all, one JSON path excluded",
        band=BAND_OPINION,
        notes="Appraisal with a stated colour rating — an opinion about evidence, and labelled as "
              "one. Useful for what clinicians argue about, not as a guideline.",
    ),
    # -------------------------------------------------- tier C: human read only
    Venue(
        domain="medscape.com", name="Medscape", kind="hcp_discussion",
        collection_tier="C", api_available=False,
        tos_posture="restricted — registration-gated clinical content; human-read only (PRD §9.1)",
        areas=("*",),
        robots="200; allows / for the public shell, member paths disallowed — irrelevant, tier C "
               "is refused in code before robots is consulted",
        distribution_mode="paid_endemic",
        page_fetch_ok=False,
    ),
    Venue(
        domain="doximity.com", name="Doximity", kind="hcp_discussion",
        collection_tier="C", api_available=False,
        tos_posture="restricted — NPI-verified member network; human-read only. Paid endemic media "
                    "is a separate axis and remains available",
        areas=("*",),
        robots="200; allows the marketing shell — irrelevant, tier C is refused in code",
        distribution_mode="paid_endemic",
        page_fetch_ok=False,
    ),
    Venue(
        domain="sermo.com", name="Sermo", kind="hcp_discussion",
        collection_tier="C", api_available=False,
        tos_posture="restricted — verified-physician network; human-read only",
        areas=("*",),
        robots="200; allows the marketing shell — irrelevant, tier C is refused in code",
        distribution_mode="paid_endemic",
        page_fetch_ok=False,
    ),
)

_PATIENT: tuple[Venue, ...] = (
    Venue(
        domain="inspire.com", name="Inspire", kind="patient_community",
        collection_tier="B", api_available=False,
        tos_posture="patient community; PRD §9.3 — themes only, no verbatim, no author identifiers",
        areas=("*",),
        robots="403 to our User-Agent on 2026-08-02 — unreadable, treated as disallow",
        patient_generated=True, page_fetch_ok=False,
    ),
    Venue(
        domain="healthunlocked.com", name="HealthUnlocked", kind="patient_community",
        collection_tier="B", api_available=False,
        tos_posture="patient community; PRD §9.3 — themes only, no verbatim, no author identifiers",
        areas=("*",),
        robots="200; allows public posts, and Disallow covers /profile, /messages, /settings and "
               "private posts — the member surface is off limits by the venue's own rules too",
        patient_generated=True,
    ),
    Venue(
        domain="patientslikeme.com", name="PatientsLikeMe", kind="patient_community",
        collection_tier="B", api_available=False,
        tos_posture="patient community; PRD §9.3 — themes only, no verbatim, no author identifiers",
        areas=("*",),
        robots="200; allows /, and /patients, /dailyme, /mood_score are disallowed — i.e. the "
               "member-level surface is excluded by the venue",
        patient_generated=True,
    ),
    Venue(
        domain="patient.info", name="Patient.info forums", kind="patient_community",
        collection_tier="B", api_available=False,
        tos_posture="patient community; PRD §9.3 — themes only. /forums/profiles/ is disallowed by "
                    "the venue, which matches our own rule",
        areas=("*",),
        robots="200; allows /forums/, disallows /forums/profiles/, /forums/me/, search and print",
        patient_generated=True,
    ),
    Venue(
        domain="chadd.org", name="CHADD (ADHD)", kind="patient_community",
        collection_tier="B", api_available=False,
        tos_posture="advocacy organisation; public education content",
        areas=("adhd",),
        robots="200; User-agent: * with an empty Disallow — allow all",
        patient_generated=True,
        notes="The reference point for ADHD lay guidance in the US; pairs with AAP and APA.",
    ),
    Venue(
        domain="americanmigrainefoundation.org", name="American Migraine Foundation",
        kind="patient_community", collection_tier="B", api_available=False,
        tos_posture="AHS's patient-facing arm; public education content",
        areas=("headache",),
        robots="200; allows /, event/find-a-doctor and query-string paths disallowed",
        patient_generated=True,
    ),
    Venue(
        domain="kidney.org", name="National Kidney Foundation", kind="patient_community",
        collection_tier="B", api_available=False,
        tos_posture="advocacy organisation; public education content",
        areas=("nephrology",),
        robots="200; allows /, Drupal infrastructure paths disallowed",
        patient_generated=True,
    ),
    Venue(
        domain="cancer.org", name="American Cancer Society", kind="patient_community",
        collection_tier="B", api_available=False,
        tos_posture="advocacy organisation; public education content",
        areas=("oncology",),
        robots="200; allows /, glossary and content-mirror paths disallowed",
        patient_generated=True,
    ),
    Venue(
        domain="csn.cancer.org", name="Cancer Survivors Network (ACS)", kind="patient_community",
        collection_tier="B", api_available=False,
        tos_posture="patient community; PRD §9.3 — themes only, no verbatim, no author identifiers",
        areas=("oncology",),
        robots="406 to our User-Agent on 2026-08-02 — unreadable, treated as disallow",
        patient_generated=True, page_fetch_ok=False,
    ),
    Venue(
        domain="lls.org", name="Leukemia & Lymphoma Society", kind="patient_community",
        collection_tier="B", api_available=False,
        tos_posture="advocacy organisation; public education content",
        areas=("hematology", "oncology"),
        robots="403 to our User-Agent on 2026-08-02 — unreadable, treated as disallow",
        patient_generated=True, page_fetch_ok=False,
    ),
    Venue(
        domain="breastcancer.org", name="Breastcancer.org", kind="patient_community",
        collection_tier="B", api_available=False,
        tos_posture="patient community; PRD §9.3 — themes only, no verbatim, no author identifiers",
        areas=("oncology",),
        robots="200; allows /, /chat and several campaign paths disallowed",
        patient_generated=True,
    ),
    Venue(
        domain="macmillan.org.uk", name="Macmillan Cancer Support (UK)", kind="patient_community",
        collection_tier="B", api_available=False,
        tos_posture="charity; public education plus a community forum — §9.3 applies to the forum",
        areas=("oncology", "palliative"),
        robots="200; allows /, /login and /search disallowed",
        patient_generated=True,
        notes="UK. Useful for the patient-side vocabulary of a symptom, not for US practice.",
    ),
    Venue(
        domain="crohnscolitisfoundation.org", name="Crohn's & Colitis Foundation",
        kind="patient_community", collection_tier="B", api_available=False,
        tos_posture="advocacy organisation; public education content",
        areas=("gastroenterology",),
        robots="200 (read at www.; the apex cert chain fails verification); allows /, Drupal "
               "infrastructure paths disallowed",
        patient_generated=True,
    ),
)

#: The gold list. Order is stable and is the order queries are planned in.
GOLD_VENUES: tuple[Venue, ...] = (
    _EVIDENCE + _GUIDELINES + _REGULATORY + _DRUG_REFERENCE + _HCP_DISCUSSION + _PATIENT
)

GOLD_DOMAINS: frozenset[str] = frozenset(v.domain for v in GOLD_VENUES)

_BY_DOMAIN: dict[str, Venue] = {}
for _venue in GOLD_VENUES:
    _BY_DOMAIN.setdefault(_venue.domain, _venue)
    _BY_DOMAIN.setdefault(_venue.registrable, _venue)


# --------------------------------------------------------------------------- #
# lookups                                                                      #
# --------------------------------------------------------------------------- #


def venue_for(url_or_domain: str) -> Venue | None:
    """The gold-list venue for a URL or host, matching parent domains too."""
    host = domain_of(url_or_domain)
    if not host:
        return None
    parts = [p for p in host.split(".") if p]
    for index in range(len(parts) - 1):
        found = _BY_DOMAIN.get(".".join(parts[index:]))
        if found is not None:
            return found
    return None


def is_gold(url_or_domain: str) -> bool:
    """``True`` when this host is on the curated list."""
    return venue_for(url_or_domain) is not None


def kind_of(url_or_domain: str) -> str:
    venue = venue_for(url_or_domain)
    return venue.kind if venue else ""


def is_recency_filtered(url_or_domain: str) -> bool:
    """``True`` when the recency window applies to this host's kind."""
    venue = venue_for(url_or_domain)
    return bool(venue and venue.recency_filtered)


def gold_page_fetch_allowed(url_or_domain: str) -> bool:
    """May the Web Unlocker be pointed at this host at all?

    Gold list **and** tier A/B **and** the venue's own ``page_fetch_ok``. robots.txt
    is checked separately and later, at run time, and can still say no.
    """
    venue = venue_for(url_or_domain)
    if venue is None:
        return False
    return venue.page_fetch_ok and venue.collection_tier in ("A", "B")


def venues_for(
    areas: Sequence[str] = (),
    *,
    kinds: Sequence[str] | None = None,
    tiers: Sequence[str] = ("A", "B"),
    include_general: bool = True,
    bands: Sequence[int] | None = None,
) -> list[Venue]:
    """The gold-list venues to point a campaign at, in **spend order**.

    Sorted by ``(spend_band, kind, area-specific first, registry order)``:

    * band before everything else — conversation is what Stage 2 is buying;
    * then kind, so *HCP discussion comes before patient community* inside the
      conversation band and guideline bodies before journals inside the substrate
      band;
    * then area-specific before general, so ADHD reaches CHADD and r/ADHD before
      it reaches PubMed-at-large;
    * then registry order, which is stable, so a plan is reproducible.
    """
    wanted = list(areas)
    rows: list[tuple[int, int, int, int, Venue]] = []
    for index, venue in enumerate(GOLD_VENUES):
        if venue.collection_tier not in tiers:
            continue
        if kinds is not None and venue.kind not in kinds:
            continue
        if bands is not None and venue.spend_band not in bands:
            continue
        specific = bool(wanted) and any(area in venue.areas for area in wanted)
        if not specific and not (include_general and "*" in venue.areas):
            continue
        rows.append((venue.spend_band, KIND_ORDER.get(venue.kind, 9), 0 if specific else 1, index, venue))
    return [venue for *_key, venue in sorted(rows, key=lambda r: r[:4])]


def site_tokens(venue: Venue, areas: Sequence[str] = (), *, max_tokens: int = 4) -> list[str]:
    """``site:`` targets for one venue — subreddit-level where we named them.

    Area-specific scopes come **first** and the list is capped: Reddit alone has
    five general clinical subreddits, and without the ordering an ADHD campaign
    spends its whole ``site:`` budget on r/medicine and never reaches r/ADHD.
    """
    specific = [path for area, path in venue.path_scopes if area != "*" and area in areas]
    general = [path for area, path in venue.path_scopes if area == "*"]
    ordered = specific + general
    if not ordered:
        return [venue.domain]
    seen: set[str] = set()
    out: list[str] = []
    for scope in ordered:
        if scope not in seen:
            seen.add(scope)
            out.append(scope)
    return out[: max(int(max_tokens), 1)]


def catalogue_entries(venues: Iterable[Venue] | None = None) -> tuple[dict[str, Any], ...]:
    """The registry in the dict shape Stage 2 and :mod:`vsm.mining.tiers` speak."""
    return tuple(v.as_catalogue_entry() for v in (venues if venues is not None else GOLD_VENUES))
