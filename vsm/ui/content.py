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
    "DELIVERABLE_TIERS",
    "WHAT_IT_IS",
    "MODES",
    "PLOT_GUIDE",
    "TIERS",
    "GLOSSARY",
    "FIELD_GUIDE",
    "FIRST_RUN_STEPS",
    "EPHEMERAL_STORAGE_NOTICE",
    "READ_ONLY_CONTROL_NOTE",
    "explainer",
]

TAGLINE = "What people are saying about a brand or product online — and what changed."

#: Said once, clearly, at the top of every page — see the site-wide banner
#: in ``_base.html``, driven by ``vsm.platform.storage_is_durable`` (a Jinja
#: global, so no route needs to pass it). Never repeated screen by screen:
#: that was the previous, incomplete version of this notice, and a warning
#: read on every page trains a reader to stop reading it.
#:
#: This is not merely a caveat any more. ``storage_is_durable() is False``
#: means every mutating route actually refuses (409) — creating or editing a
#: topic, running a snapshot, insight or report all fail outright — so the
#: words say that plainly rather than soften it into "might not survive".
EPHEMERAL_STORAGE_NOTICE = (
    "This instance is a read-only demonstration: no database is connected, "
    "so nothing created here would survive the next request landing on a "
    "different container. Connect Postgres, or run it locally, to create "
    "your own topics."
)

#: Stands in for a hidden mutating control (a button, a form) wherever one
#: is not rendered — never the full notice above repeated: that has already
#: run once, at the top of the page, and repeating it at every button-shaped
#: hole is exactly the "sprawl" this whole approach exists to avoid. Deliberately
#: the same short line everywhere, rather than a bespoke sentence per control.
READ_ONLY_CONTROL_NOTE = "Not available — this instance is read-only. See the note above."

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
    ("3+ sources", "Three or more independent sources. Safe to state as-is."),
    ("2 sources", "Two independent sources. Attribute it rather than stating it flat."),
    ("1 source", "One source. Quote it, don't generalise from it."),
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
        "Sweep size",
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
    ("Run a sweep", "Pick a sweep size. You see the estimate before anything is spent."),
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
        "Four documents written to be handed over, and the evidence behind them."
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
# `sample` is written in the same markdown the real artifact writes, and is
# rendered through the same converter the report body uses — never handed to a
# template as raw text. It is illustrative of the *shape* of a line, not a
# quote from a particular run, and the page says so in those words: claiming a
# hard-coded string is "real output" was itself a small dishonesty, and the
# numbers in it matched no run in the system.

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
        "sample": (
            "**Cost of access** — 12 independent sources, "
            "(14 signals). Volume is up 40% versus the prior snapshot "
            "(10 to 14)."
        ),
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
        "sample": (
            "| ref | source | captured | method |\n"
            "|---|---|---|---|\n"
            "| 1 | studentdoctor.net | 25 August 2026 | search result |"
        ),
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

#: The two tiers the deliverables are shown in. The four client-ready
#: artifacts are the offer and get the top of the page; the six behind them
#: are the evidence for it and read as a list. Ten cards at one weight said
#: `coverage.json` was worth as much as the report, which is exactly the
#: impression this split exists to correct.
DELIVERABLE_TIERS = (
    {
        "key": "primary",
        "groups": ("report",),
        "label": "Client-ready documents",
        "lede": (
            "Four documents, written to be handed over without editing. Every "
            "sample below is rendered as it will appear in the report — never "
            "as markdown source."
        ),
    },
    {
        "key": "secondary",
        "groups": ("analysis", "data"),
        "label": "The evidence underneath",
        "lede": (
            "Six machine-readable files behind those four documents — every "
            "theme, stance, delta and collected row, for your own analysis."
        ),
    },
)

#: How the deliverables screen groups them, in the order a reader should meet them.
DELIVERABLE_GROUPS = (
    ("report", "Client-ready", "Written to be handed over without editing."),
    ("analysis", "Analysis", "The findings behind the report, as data."),
    ("data", "Raw collection", "Everything gathered, with full provenance."),
)


#: How the topics index can be ordered. Server-side, because a list that is
#: only sortable once JavaScript runs is not sortable on a printed page, in a
#: shared link, or with a screen reader driving it.
SORTS: tuple[tuple[str, str], ...] = (
    ("recent", "Newest first"),
    ("oldest", "Oldest first"),
    ("name", "Name A–Z"),
    ("activity", "Most snapshots"),
    ("spend", "Highest spend"),
    ("volume", "Largest volume"),
)

#: Coarse buckets, chosen because they answer the question people actually
#: have when a list has grown noisy: which of these are real, and which did I
#: create once and never run?
FILTERS: tuple[tuple[str, str], ...] = (
    ("all", "All topics"),
    ("watched", "Has snapshots"),
    ("trend", "Has a trend (2+)"),
    ("empty", "Never run"),
)

FILTER_HELP = {
    "all": "Everything in the store.",
    "watched": "Mined at least once, so there is something to read.",
    "trend": "Mined twice or more — the only topics where momentum and anomaly mean anything.",
    "empty": "Created but never mined. Usually a false start, or a test.",
}

#: Shown above the list once it is long enough that scanning it is work.
FILTER_LEDE = (
    "Search matches the topic name, brand, molecule and therapeutic area. "
    "Sort and filter are links, so the view you are looking at is the view you "
    "can share or bookmark."
)

DELETE_WARNING = (
    "Deleting a topic removes every snapshot, insight and report under it, and "
    "every artifact those runs wrote. Downloads you have already taken are "
    "yours and are unaffected. Nothing else references this topic, so nothing "
    "else breaks — but the collected signal rows are gone, and re-mining "
    "collects today's web, not the web as it was on the snapshot's date."
)


#: Terms explained **at the word, on demand** — never pre-emptively in a
#: paragraph. Each is rendered as a native popover (see the `define` macro), so
#: the definition costs nothing until someone asks for it.
#:
#: This is what replaces the glossary page and the parenthetical asides. The
#: owner's reaction to the old vocabulary was "wtf is Corroborated" — a word
#: invented in this codebase, surfaced raw, with its meaning nowhere near it.
#: Every entry below is a term a reader could reasonably not know; the second
#: string, where present, is the consequence rather than the restatement.
DEFINITIONS: dict[str, tuple[str, str]] = {
    "sources": (
        "How many independent sources say this.",
        "One forum post counts as one source. One publisher counts as one "
        "source however many pages it runs — so five outlets carrying the same "
        "press release count once, not five times.",
    ),
    "3+ sources": (
        "Three or more independent sources. Safe to state as-is.",
        "Two sources: attribute it. One: quote it, don't generalise from it.",
    ),
    "gap": (
        "How differently clinicians and patients read the same theme.",
        "Each side's tone runs from −1 to +1. The gap is the distance between "
        "them, so a large gap means the two audiences disagree about it.",
    ),
    "no comparison": (
        "Only one audience discussed this theme, so there is no gap to measure.",
        "This is not agreement. It means one side did not raise it at all.",
    ),
    "sweep": (
        "One dated collection run against the live web.",
        "Comparisons are always between two sweeps, so a theme's change is "
        "measured against a specific earlier date rather than a rolling window.",
    ),
    "tone": (
        "The balance of positive and negative mentions, from −1 to +1.",
        "Mentions we could not read either way are excluded from the balance "
        "and counted separately, so they never look like neutral opinions.",
    ),
    "mention": (
        "One collected post, comment or page.",
        "Every figure in this tool is an aggregate of these, and each one keeps "
        "its URL and the date it was captured.",
    ),
    "access basis": (
        "How this site may lawfully be collected from.",
        "A site's own API and public pages may be fetched. Others are used only "
        "as search results and are never page-fetched.",
    ),
    "sweep size": (
        "How wide and how expensive the collection run is.",
        "It sets the number of queries and page fetches. Page fetches cost "
        "about twenty times a search call, so they set the bill.",
    ),
    "returned nothing": (
        "The site was queried and gave back no rows.",
        "Named rather than hidden: a site that returned nothing looks identical "
        "to a site nobody asked, and only one of those is a finding.",
    ),
}


#: Run modes as verbs. `mine` is an internal word for what the step does, and
#: "Mine run" told a reader nothing they could act on.
from vsm.modes.vocabulary import MODE_LABEL as MODE_LABELS
