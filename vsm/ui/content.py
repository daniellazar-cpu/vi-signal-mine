"""The words the interface uses to explain itself.

Kept in one module, away from templates, for two reasons. Copy this specific is
edited far more often than markup, and holding it together is the only way to
keep the register consistent — every explainer here is one idea, plain words,
under about forty of them. A reader who wants depth opens a `<details>`; a
reader who does not is never made to scroll past it.

Rules that keep this from turning into a wall of text:

* No internal shorthand. Decision codes and guard numbers are how the team
  talks, not how the tool talks.
* Concrete over abstract. "About 3 cents" beats "low cost".
* Say the limitation in the same breath as the capability, once, then stop.
"""

from __future__ import annotations

__all__ = [
    "TAGLINE",
    "DELIVERABLES",
    "DELIVERABLE_GROUPS",
    "WHAT_IT_IS",
    "MODES",
    "PLOT_GUIDE",
    "TIERS",
    "GLOSSARY",
    "FIELD_GUIDE",
    "FIRST_RUN_STEPS",
    "EPHEMERAL_STORAGE_NOTICE",
    "explainer",
]

TAGLINE = "What people are saying about a brand or product online — and what changed."

#: Shown at the one point the risk is real — the topic-creation form, and
#: the screen a user lands on right after creating one — never elsewhere.
#: One quiet, specific line, not a warning repeated on every screen: what is
#: missing (a database), what it costs (a topic outlives this container only
#: by luck), and the fix (Postgres). Whether this shows at all is computed
#: from whether a database URL resolves (vsm.backends.dburl.resolve_db_url),
#: never from any one topic's own data.
EPHEMERAL_STORAGE_NOTICE = (
    "This instance has no database connected, so topics created here last "
    "only as long as this container keeps running. Connecting Postgres "
    "keeps them for good."
)

WHAT_IT_IS = (
    "Vi Signal Mine watches a topic over time. It collects what is being said "
    "in medical forums, patient communities, journals and guideline bodies, "
    "then works out which findings hold up, who is saying them, and what moved "
    "since last time. Every number on every screen traces back to a dated row "
    "with a URL you can open."
)

#: The three modes, in the order they run. `produces` is what lands on disk.
MODES = (
    {
        "key": "mine",
        "name": "Mine",
        "one_liner": "Go and collect. Produces one dated snapshot of the topic.",
        "detail": (
            "Searches a hand-checked list of medical venues first — journals, "
            "guideline bodies, clinician forums, patient communities — before "
            "spending anything on the open web. Every result is recorded with "
            "where it came from, when it was captured, and what it cost."
        ),
        "produces": "Signals, provenance, coverage, cost",
        # Say the number the form shows, not a flattering slice of it. A probe
        # estimates near 6 cents: about a penny of search and 5 cents of model
        # time. "About 3 cents" was the search half quoted as the whole, which
        # is the kind of small dishonesty that makes a reader stop trusting
        # every other figure on the page.
        "cost": (
            "A probe run estimates at about 6 cents — roughly a penny of "
            "search and 5 cents of model time. A deep run is a few dollars."
        ),
    },
    {
        "key": "insight",
        "name": "Insight",
        "one_liner": "Work out what it means. Seven passes over one snapshot.",
        "detail": (
            "Groups signals into themes, counts how many independent sources "
            "back each one, reads stance separately for clinicians and for "
            "patients, and compares everything against earlier snapshots of the "
            "same topic to find what moved and what is new."
        ),
        "produces": "Themes, findings, stance, the clinician–patient gap, momentum, anomalies",
        "cost": "Model time only — typically under a dollar.",
    },
    {
        "key": "report",
        "name": "Report",
        "one_liner": "Write it up. A report you can hand to a client as-is.",
        "detail": (
            "Assembles the findings into a readable report, an appendix listing "
            "every source behind every claim, and a methodology note saying what "
            "was searched and what was not. Claims that cannot be traced to real "
            "collected rows are refused rather than printed."
        ),
        "produces": "Pulse report, provenance appendix, methodology, things worth considering",
        "cost": "One model call.",
    },
)

#: How to read the forest plot. Shown beside it, not buried in a help page.
PLOT_GUIDE = {
    "lede": (
        "Each row is a theme. The box is how much is being said about it. "
        "The whisker shows how differently clinicians and patients feel about it."
    ),
    "marks": (
        ("Box size", "How many signals mention this theme."),
        ("Whisker", "The distance between clinician stance and patient stance."),
        ("Centre line", "No gap — both sides feel the same way."),
        ("Left", "Patients are more negative than clinicians."),
        ("Right", "Clinicians are more negative than patients."),
        ("NE", "Not comparable — only one side discussed it. Not zero."),
    ),
    "why_ne": (
        "When only clinicians or only patients discussed a theme, there is "
        "nothing to compare and we say so rather than showing a gap of zero. "
        "Silence from one side is not agreement."
    ),
}

#: What the confidence tiers mean, in the order a reader meets them.
TIERS = (
    ("corroborated", "Three or more independent sources. Can be stated as a finding."),
    ("emerging", "Two independent sources. Worth watching, shown separately."),
    ("single source", "One source. Kept in the data, never stated as a finding."),
)

#: One line each. Only terms a first-time reader actually hits.
GLOSSARY = (
    (
        "Topic",
        "The thing you watch — a brand, a molecule, its competitors and a "
        "therapeutic area. Topics persist so you can run them again.",
    ),
    (
        "Snapshot",
        "One dated collection run against a topic. Run a topic twice and the "
        "second snapshot can be compared to the first.",
    ),
    (
        "Spend band",
        "How wide to search: probe, standard or deep. Each shows its estimated "
        "cost before you commit.",
    ),
    (
        "Independent source",
        "A distinct post or a distinct publisher. Five outlets running the same "
        "press release count as one; twenty people in a forum count as twenty.",
    ),
    (
        "Author class",
        "Whether something came from a clinician venue, a patient community, or "
        "an institution like a journal. Taken from the venue, not from anyone's "
        "identity.",
    ),
    (
        "Stance",
        "How a theme is talked about — positive, negative, mixed, neutral, or "
        "unclear. Always reported separately for clinicians and patients, never "
        "blended into one number.",
    ),
    (
        "Momentum",
        "How a theme's volume changed against the previous snapshot. Measured, "
        "not predicted — this tool does not forecast.",
    ),
    (
        "Anomaly",
        "Something that changed on its own: a theme that appeared, vanished, "
        "spiked or collapsed against its recent baseline.",
    ),
    (
        "Coverage",
        "Which venues answered and which came back with nothing. An empty venue "
        "is a finding, so it is named rather than dropped.",
    ),
)

#: Shown on the empty state. Three steps, no more.
FIRST_RUN_STEPS = (
    ("Name a topic", "A brand, a molecule, a category — whatever you want watched. That is the only thing required."),
    ("Run a snapshot", "Pick a spend band. You see the estimate before anything is spent."),
    (
        "Run it again next week",
        "Momentum and anomalies need something to compare against. One snapshot "
        "tells you what is being said; two tell you what is changing.",
    ),
)

#: Per-field guidance for the topic form. Only `name` is required; every other
#: field earns its place by saying what it changes about the result, so a user
#: can decide to skip it rather than guess. `when_blank` is what happens if
#: they do — never a warning, just the consequence.
FIELD_GUIDE = {
    "name": {
        "label": "Topic",
        "required": True,
        "help": "What you want watched. A brand, a molecule, a category, a question.",
        "placeholder": "e.g. Zepbound — obesity",
        "when_blank": "",
    },
    "brand": {
        "label": "Brand name",
        "required": False,
        "help": "The product as patients and clinicians actually write it.",
        "placeholder": "e.g. Zepbound",
        "when_blank": "Searches on the topic name alone.",
    },
    "molecule": {
        "label": "Molecule (INN)",
        "required": False,
        "help": "The generic name. Clinicians often use it where patients use the brand — including it finds conversation the brand name misses.",
        "placeholder": "e.g. tirzepatide",
        "when_blank": "Fine to skip — not every topic has one, and some categories have several.",
    },
    "competitors": {
        "label": "Competitors",
        "required": False,
        "help": "How a conversation refers to the category. Naming them widens what gets found and lets the report compare.",
        "placeholder": "e.g. Wegovy, Saxenda",
        "when_blank": "The run still works; it just will not tell you about the category around you.",
    },
    "therapeutic_area": {
        "label": "Therapeutic area",
        "required": False,
        "help": "Routes the search to the venues that matter for this area, before spending anything on the open web.",
        "placeholder": "e.g. obesity",
        "when_blank": "Searches a general venue set, which costs the same and finds less.",
    },
    "questions": {
        "label": "Questions you care about",
        "required": False,
        "help": "What you would ask if you could ask the internet directly. Shapes which themes get surfaced first.",
        "placeholder": "e.g. what do prescribers say about tolerability?",
        "when_blank": "Themes are ranked by volume alone.",
    },
}

#: Short inline notes, keyed by screen. One sentence each.
_EXPLAINERS = {
    "topics": (
        "Each topic is watched over time. The sparkline is its signal volume "
        "across snapshots."
    ),
    "topic_form": (
        "Only the topic is required. Everything else narrows or widens the "
        "search — add what you know, skip what you do not."
    ),
    "confirm": (
        "This is the only screen that spends money. The estimate is a ceiling, "
        "not a guess — a run stops cleanly rather than exceeding it."
    ),
    "run": "Each stage writes its output as it finishes, so nothing is lost if a run stops early.",
    "snapshot": (
        "Everything collected, with where it came from and when. Filter here and "
        "the plot above re-weights."
    ),
    "insight": (
        "Seven passes over one snapshot. The clinician–patient gap leads because "
        "it is the finding nobody thinks to ask for."
    ),
    "report": (
        "Every claim links to the rows behind it. A claim that cannot be traced "
        "is refused rather than printed."
    ),
    "how": "The whole process, start to finish, in about two minutes of reading.",
    "deliverables": (
        "What lands when a run finishes — before you spend anything on one. "
        "Ten artifacts, grouped by who they are for."
    ),
}


def explainer(screen: str) -> str:
    """The one-line note for a screen, or empty when it has none.

    Returns `""` rather than raising, because a missing explainer is a copy gap
    and must never take a page down with it.
    """
    return _EXPLAINERS.get(screen, "")


# --------------------------------------------------------------------------- #
# The deliverables — the thing the tool is actually for                        #
# --------------------------------------------------------------------------- #
#
# Everything above explains the process. This explains the product. A user
# deciding whether to spend money needs to know what lands on the other side,
# so this is shown BEFORE a run as much as after — the pre-run screen is the
# same list with nothing filled in yet.
#
# `sample` is one real line from a real run, not a mockup. It is what makes
# "provenance appendix" mean something to someone who has never seen one.

DELIVERABLES = (
    {
        "key": "pulse_report",
        "file": "pulse_report.md",
        "name": "Pulse report",
        "group": "report",
        "headline": "The read you hand over.",
        "body": (
            "What is being said, where, by which kind of source, moving which "
            "way, and what changed since last time. Every claim carries its "
            "confidence tier on the page."
        ),
        "for_whom": "The client, as-is.",
        "sample": "**cost** is corroborated on 12 independent sources. Volume is up 500% versus the prior snapshot (2 to 12).",
    },
    {
        "key": "provenance_appendix",
        "file": "provenance_appendix.md",
        "name": "Provenance appendix",
        "group": "report",
        "headline": "Every claim, traced to the rows behind it.",
        "body": (
            "One row per cited signal: id, venue, what kind of venue, when it "
            "was captured, how, and the URL. This is what lets someone check "
            "the report instead of believing it."
        ),
        "for_whom": "Anyone who asks 'where did this come from?'",
        "sample": "sig-h2 · studentdoctor.net · hcp_discussion · 2026-08-25 · serp_result · https://…",
    },
    {
        "key": "methodology",
        "file": "methodology.md",
        "name": "Methodology note",
        "group": "report",
        "headline": "What was searched, and what was not.",
        "body": (
            "Venues queried, the date window, what was excluded and why, how "
            "confidence tiers are defined, and the limits of the run. Written "
            "so the method can be checked, not just described."
        ),
        "for_whom": "Medical, legal, or a client's own analyst.",
        "sample": "An independent source is a distinct post or a distinct publisher.",
    },
    {
        "key": "worth_considering",
        "file": "worth_considering.md",
        "name": "Worth considering",
        "group": "report",
        "headline": "Options, never instructions.",
        "body": (
            "What the findings might mean for what you do next, framed as "
            "things to weigh. The tool suggests; the decision stays with the "
            "person who has the context it does not."
        ),
        "for_whom": "Whoever owns the brand.",
        "sample": "Cost is the dominant patient theme and absent from clinician venues — worth checking whether access messaging reaches patients directly.",
    },
    {
        "key": "signals",
        "file": "signals.json",
        "name": "Signal ledger",
        "group": "data",
        "headline": "Everything collected, row by row.",
        "body": "Each result with its venue, capture time, collection method, tier and URL.",
        "for_whom": "Your own analysis.",
        "sample": "",
    },
    {
        "key": "coverage",
        "file": "coverage.json",
        "name": "Coverage",
        "group": "data",
        "headline": "Which venues answered, and which came back empty.",
        "body": "An empty venue is a finding, so it is named rather than dropped.",
        "for_whom": "Judging whether the sweep was wide enough.",
        "sample": "",
    },
    {
        "key": "themes",
        "file": "themes.json",
        "name": "Themes",
        "group": "analysis",
        "headline": "What is being discussed, grouped and counted.",
        "body": "Volume, venue mix and venue-kind mix per theme.",
        "for_whom": "Charting and re-cuts.",
        "sample": "",
    },
    {
        "key": "duallens",
        "file": "duallens.json",
        "name": "Clinician–patient gap",
        "group": "analysis",
        "headline": "Where the two audiences diverge.",
        "body": "Per theme, each side's stance and the distance between them — or a stated reason when they cannot be compared.",
        "for_whom": "The finding nobody thinks to ask for.",
        "sample": "",
    },
    {
        "key": "momentum",
        "file": "momentum.json",
        "name": "Momentum",
        "group": "analysis",
        "headline": "What moved since the last snapshot.",
        "body": "Volume change per theme. Measured, never forecast.",
        "for_whom": "The half a client cannot get by reading forums themselves.",
        "sample": "",
    },
    {
        "key": "anomaly",
        "file": "anomaly.json",
        "name": "Anomalies",
        "group": "analysis",
        "headline": "What changed that nobody asked about.",
        "body": "Themes that appeared, vanished, spiked or collapsed against their recent baseline.",
        "for_whom": "Catching the thing you were not watching for.",
        "sample": "",
    },
)

#: How the deliverables screen groups them, in the order a reader should meet them.
DELIVERABLE_GROUPS = (
    ("report", "Client-ready", "Written to be handed over without editing."),
    ("analysis", "Analysis", "The findings behind the report, as data."),
    ("data", "Raw collection", "Everything gathered, with full provenance."),
)
