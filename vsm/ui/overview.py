"""What the landing screen shows, computed without touching HTTP or Jinja.

**Why this module exists.** The app had no overview. The landing screen was a
table of topics, one row each, and everything a person actually opens the tool
to find out — what moved, where the two audiences disagree, what has become
sayable — lived inside a single snapshot's page, three clicks in and only for
one topic at a time. So the tool held the answers and never surfaced them.

Every figure here is read from artifacts the pipeline already writes. Nothing is
recomputed and nothing is inferred: ``momentum.json`` carries the deltas,
``duallens.json`` the divergences, ``findings.json`` the confidence tier. If a
number appears on the dashboard it exists in a file with a run id behind it,
which is the claim the whole product rests on.

Pure functions taking already-loaded data, so the interesting logic — ranking,
what counts as "moved", what counts as "needs attention" — is testable without a
client, a store, or a template.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

__all__ = [
    "ArtifactReader",
    "artifacts_to_warm",
    "build_overview",
    "latest_insight_per_topic",
]

#: ``(run_id, name) -> parsed artifact``, raising ``FileNotFoundError`` when
#: absent. Matches ``RunStoreLike.read_artifact`` so a caller passes the store's
#: bound method straight in.
ArtifactReader = Callable[[str, str], Any]

#: How many rows each panel shows. Six because a panel is meant to be read at a
#: glance and then acted on: a ranked list long enough to scroll is a table, and
#: the tool already has tables. Every panel links to the full detail.
PANEL_ROWS = 6

#: A theme has to move by more than this to be reported as having moved. Every
#: sweep re-queries a live web, so a one-signal wobble is noise, and a panel
#: that fills with ±3% churn teaches people to ignore it — which costs more than
#: showing nothing would.
MOVED_MIN_PCT = 10.0


def latest_insight_per_topic(
    runs_by_topic: Mapping[str, Sequence[Any]],
) -> dict[str, Any]:
    """The most recent completed INSIGHT run for each topic, or nothing.

    Latest only, deliberately. Ranking across every insight run a topic ever had
    would let one topic's history crowd out five other topics, and an older run's
    momentum figure is a statement about a comparison that has since been
    superseded — true when it was written, misleading on a screen headed "what
    moved".
    """
    out: dict[str, Any] = {}
    for topic_id, runs in runs_by_topic.items():
        done = [r for r in runs if r.mode == "insight" and r.status == "complete"]
        if done:
            out[topic_id] = done[-1]      # `for_topic` order is oldest first
    return out


def _rows(read: ArtifactReader, run_id: str, name: str) -> list[dict]:
    """An artifact's rows, or none. A missing or malformed artifact must not take
    the dashboard down: this screen aggregates across every topic, so one bad
    run would otherwise cost a person the view of all the others."""
    try:
        value = read(run_id, name)
    except (FileNotFoundError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _moved(
    topics_by_id: Mapping[str, Any],
    insights: Mapping[str, Any],
    read: ArtifactReader,
) -> list[dict[str, Any]]:
    """Themes whose volume changed against the prior snapshot, biggest first.

    Rows with no prior snapshot are skipped rather than shown as 0%: a theme
    being measured for the first time has not "not moved", and rendering it at
    zero is the exact confusion this codebase has fought everywhere else.
    """
    out: list[dict[str, Any]] = []
    for topic_id, run in insights.items():
        for row in _rows(read, run.run_id, "momentum.json"):
            prior = row.get("volume_prior")
            pct = row.get("delta_pct")
            if prior is None or pct is None:
                continue
            if abs(pct) < MOVED_MIN_PCT:
                continue
            out.append({
                "topic": topics_by_id[topic_id],
                "theme": row.get("theme_name", ""),
                "delta": row.get("delta"),
                "delta_pct": pct,
                "volume_now": row.get("volume_now"),
                "volume_prior": prior,
                "run_id": run.run_id,
                "synthetic": bool(row.get("synthetic")),
            })
    out.sort(key=lambda r: (-abs(r["delta_pct"]), r["theme"]))
    return out


def _divergence(
    topics_by_id: Mapping[str, Any],
    insights: Mapping[str, Any],
    read: ArtifactReader,
) -> tuple[list[dict[str, Any]], int]:
    """The clinician-versus-patient gaps, widest first, plus how many themes
    could not be compared at all.

    Both halves are returned because reporting only the comparable ones would
    overstate coverage. A theme only one audience discussed has no gap and is
    not a gap of zero — it is a theme where silence is being mistaken for
    agreement if anyone reads it that way, which is why the count is surfaced
    next to the list rather than dropped.
    """
    rows: list[dict[str, Any]] = []
    not_comparable = 0
    for topic_id, run in insights.items():
        for row in _rows(read, run.run_id, "duallens.json"):
            gap = row.get("divergence")
            if gap is None:
                not_comparable += 1
                continue
            rows.append({
                "topic": topics_by_id[topic_id],
                "theme": row.get("theme_name", ""),
                "divergence": gap,
                "hcp_net": row.get("hcp_net"),
                "patient_net": row.get("patient_net"),
                "run_id": run.run_id,
                "synthetic": bool(row.get("synthetic")),
            })
    rows.sort(key=lambda r: (-abs(r["divergence"]), r["theme"]))
    return rows, not_comparable


def _sayable(
    topics_by_id: Mapping[str, Any],
    insights: Mapping[str, Any],
    read: ArtifactReader,
) -> tuple[list[dict[str, Any]], int]:
    """Findings that reached the corroboration threshold, and how many have not.

    This is the panel that answers "what can I actually put in front of a
    client?", which is the question the whole confidence tiering exists to
    settle. Corroborated findings first, then the count still emerging, so the
    ratio is visible rather than implied.
    """
    rows: list[dict[str, Any]] = []
    emerging = 0
    for topic_id, run in insights.items():
        for row in _rows(read, run.run_id, "findings.json"):
            if row.get("tier") != "corroborated":
                emerging += 1
                continue
            rows.append({
                "topic": topics_by_id[topic_id],
                "statement": row.get("statement", ""),
                "sources": row.get("independent_sources"),
                "run_id": run.run_id,
                "synthetic": bool(row.get("synthetic")),
            })
    rows.sort(key=lambda r: (-(r["sources"] or 0), r["statement"]))
    return rows, emerging


def _attention(
    topics: Sequence[Any],
    runs_by_topic: Mapping[str, Sequence[Any]],
) -> list[dict[str, Any]]:
    """Topics that cannot answer the questions above, and why.

    The point is that each of these is a *fixable* state with one obvious next
    action, not a list of complaints. Ordered by how close the topic is to being
    useful, so the cheapest wins come first: a topic with one snapshot needs one
    more sweep to produce a trend, whereas one never run needs a decision about
    whether it was wanted at all.
    """
    out: list[dict[str, Any]] = []
    for topic in topics:
        runs = runs_by_topic.get(topic.topic_id, ())
        snapshots = [r for r in runs if r.mode == "mine" and r.status == "complete"]
        stopped = [r for r in runs if r.status == "stopped_on_budget"]
        failed = [r for r in runs if r.status == "failed"]
        insights = [r for r in runs if r.mode == "insight" and r.status == "complete"]
        if stopped:
            out.append({"topic": topic, "rank": 0, "why": "stopped on budget",
                        "detail": "Partial rows were kept. Raise the cap or "
                                  "accept the sweep as it stands.",
                        "action": "Review", "href": f"/runs/{stopped[-1].run_id}"})
        elif failed:
            out.append({"topic": topic, "rank": 1, "why": "last run failed",
                        "detail": "Nothing was written for that run.",
                        "action": "See why", "href": f"/runs/{failed[-1].run_id}"})
        elif len(snapshots) == 1 and not insights:
            out.append({"topic": topic, "rank": 2, "why": "collected, not analysed",
                        "detail": "One snapshot with no insight pass over it.",
                        "action": "Analyse",
                        "href": f"/runs/{snapshots[-1].run_id}/snapshot"})
        elif len(snapshots) == 1:
            out.append({"topic": topic, "rank": 3, "why": "no trend yet",
                        "detail": "One snapshot. Momentum and anomalies need a "
                                  "second to compare against.",
                        "action": "Sweep again",
                        "href": f"/topics/{topic.topic_id}/confirm"})
        elif not snapshots:
            out.append({"topic": topic, "rank": 4, "why": "never run",
                        "detail": "Defined but never swept, so nothing has been "
                                  "collected.",
                        "action": "Run first sweep",
                        "href": f"/topics/{topic.topic_id}/confirm"})
    out.sort(key=lambda r: (r["rank"], r["topic"].name.lower()))
    return out


def build_overview(
    topics: Sequence[Any],
    runs_by_topic: Mapping[str, Sequence[Any]],
    read: ArtifactReader,
    *,
    panel_rows: int = PANEL_ROWS,
) -> dict[str, Any]:
    """Everything the landing screen needs, in one pass over already-loaded data.

    Takes the runs mapping rather than a store so the caller can fetch it in one
    batched query (``RunStoreLike.for_topics``) and warm the artifacts it is
    about to read — this screen touches every topic, and doing that a request at
    a time is what made the old index take eleven seconds.

    Each panel carries its own ``total`` alongside the rows shown, because a
    panel that displays six of forty and says only "six" is the silent-truncation
    problem in a different costume.
    """
    topics_by_id = {t.topic_id: t for t in topics}
    insights = latest_insight_per_topic(runs_by_topic)

    moved = _moved(topics_by_id, insights, read)
    divergence, not_comparable = _divergence(topics_by_id, insights, read)
    sayable, emerging = _sayable(topics_by_id, insights, read)
    attention = _attention(topics, runs_by_topic)

    all_runs = [r for runs in runs_by_topic.values() for r in runs]
    snapshots = [r for r in all_runs if r.mode == "mine" and r.status == "complete"]

    signals = 0
    for run in snapshots:
        signals += len(_rows(read, run.run_id, "signals.json"))

    return {
        # Every counter carries the same keys, `money` included. The templates
        # run under StrictUndefined, so an optional key is a rendering error on
        # the row that happens not to have it — a uniform shape is cheaper than
        # a guard at every call site.
        "counters": [
            {"label": "Topics", "value": len(topics), "href": "/topics",
             "note": "watched", "money": False},
            {"label": "Snapshots", "value": len(snapshots), "href": "/topics",
             "note": "collected", "money": False},
            {"label": "Signals", "value": signals, "href": "/topics",
             "note": "rows behind the figures", "money": False},
            {"label": "Spend", "value": round(sum(r.cost_usd for r in all_runs), 2),
             "href": "/topics", "note": "to date", "money": True},
        ],
        "moved": moved[:panel_rows],
        "moved_total": len(moved),
        "divergence": divergence[:panel_rows],
        "divergence_total": len(divergence),
        "not_comparable": not_comparable,
        "sayable": sayable[:panel_rows],
        "sayable_total": len(sayable),
        "emerging": emerging,
        "attention": attention[:panel_rows],
        "attention_total": len(attention),
        "analysed_topics": len(insights),
        "synthetic": any(
            r.get("synthetic")
            for panel in (moved, divergence, sayable)
            for r in panel
        ),
    }


def artifacts_to_warm(
    runs_by_topic: Mapping[str, Sequence[Any]],
) -> list[tuple[str, str]]:
    """Every ``(run_id, name)`` :func:`build_overview` will read.

    Kept next to the reader rather than in the route so the two cannot drift: a
    prefetch list that misses an artifact silently costs a round trip per topic,
    which is invisible in tests and obvious only in production latency.
    """
    pairs: list[tuple[str, str]] = []
    for run in latest_insight_per_topic(runs_by_topic).values():
        pairs += [(run.run_id, name) for name in
                  ("momentum.json", "duallens.json", "findings.json")]
    for runs in runs_by_topic.values():
        pairs += [(r.run_id, "signals.json") for r in runs
                  if r.mode == "mine" and r.status == "complete"]
    return pairs
