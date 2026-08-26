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
    "WHAT_IT_IS",
    "MODES",
    "PLOT_GUIDE",
    "TIERS",
    "GLOSSARY",
    "FIRST_RUN_STEPS",
    "explainer",
]

TAGLINE = "What people are saying about a brand or product online — and what changed."

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
        "cost": "A probe run is about 3 cents. A deep run is a few dollars.",
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
    ("Create a topic", "Name the brand or molecule, its competitors, and the area."),
    ("Run a snapshot", "Pick a spend band. You see the estimate before anything is spent."),
    (
        "Run it again next week",
        "Momentum and anomalies need something to compare against. One snapshot "
        "tells you what is being said; two tell you what is changing.",
    ),
)

#: Short inline notes, keyed by screen. One sentence each.
_EXPLAINERS = {
    "topics": (
        "Each topic is watched over time. The sparkline is its signal volume "
        "across snapshots."
    ),
    "topic_form": (
        "Competitors matter: they are how a conversation refers to the category, "
        "so naming them widens what gets found."
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
}


def explainer(screen: str) -> str:
    """The one-line note for a screen, or empty when it has none.

    Returns `""` rather than raising, because a missing explainer is a copy gap
    and must never take a page down with it.
    """
    return _EXPLAINERS.get(screen, "")
