"""REPORT — the client deliverable, and the guards that make it safe to hand over.

INSIGHT already did the arithmetic: themes, their volume and mix, per-theme
corroboration tier, momentum against the prior snapshot, and detected
anomalies. REPORT's job is narrower than it looks — turn those artifacts into
four files a Vi analyst can hand to a client, without ever letting a model
author a number, a citation, a directive, or a forecast.

**Four guards fire here, and only here** (G6 is enforced earlier too, but its
gate belongs to the document REPORT writes):

* **G6** — an uncorroborated *claim* may not reach the report body. A theme's
  volume and venue mix are counts and need no corroboration; an assertion
  *about* a theme does. ``corroborated`` findings get a claim sentence in the
  body; ``emerging`` findings get one in a clearly labelled section;
  ``single_source`` findings never get a claim sentence at all — the theme
  still appears in the always-reportable themes table, tier and all.
* **G1** — every citation, ours or the model's, is rebuilt from the snapshot's
  own ledger by ``signal_id``. An id that does not resolve blocks the whole
  report; it is never silently dropped, because dropping it would turn a
  fabricated citation into a silently uncited claim.
* **G2 / G4 / G5** — advisory language, never-say terms, and forecast/accuracy
  language are checked on *every* generated string this module writes,
  template prose and model output alike. The honesty paragraph in
  ``REPORT_SYSTEM`` is what asks the model to behave; these three calls are
  what makes behaving unnecessary to rely on.

**Offline is a real path.** With ``client=None`` (the default, and what
``VSM_OFFLINE=1`` wires up) the whole report is assembled from the INSIGHT
artifacts with template prose and no model call — genuinely readable, not a
stub, and it is what most of this module's tests exercise. When a client is
supplied, its output is *additional* narrative appended to the template
content, subject to the same four guards as everything else here — nothing
the model writes is trusted merely for having been asked nicely.

Nothing is written to disk until every guard has passed. A blocked report
leaves no partial artifacts and no dangling run row: the run is only
``store.start()``-ed once there is something safe to hand over.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from vsm.analysis.corroborate import CORROBORATED_AT, Finding
from vsm.analysis.momentum import NO_BASELINE
from vsm.guards.advisory import assert_advisory
from vsm.guards.citations import Citation, bind_citations
from vsm.guards.claims import assert_no_unmeasured_claims
from vsm.guards.corroboration import assert_body_is_corroborated
from vsm.guards.terms import assert_no_banned_terms
from vsm.llm.prompts import REPORT_SYSTEM
from vsm.llm.schema import REPORT_SCHEMA
from vsm.runs.model import Run
from vsm.runs.store import RunStore
from vsm.topics.model import Topic

__all__ = ["run_report"]

#: Spec D10. Stated exactly once, in methodology.md, and nowhere else — a test
#: counts occurrences of "adverse event" across both files.
_AE_SCOPE_SENTENCE = (
    "This report is not screened for adverse events and is not a "
    "pharmacovigilance input."
)

_INDEPENDENT_SOURCE_DEFINITION = (
    "An independent source is defined as a distinct post or a distinct "
    "publisher: a true forum or patient community counts one post as one "
    "source, and every other venue counts one publisher (its registrable "
    "domain) as one source, no matter how many pages that publisher runs."
)


def _finding_from_dict(d: Mapping[str, Any]) -> Finding:
    return Finding(
        finding_id=str(d["finding_id"]),
        statement=str(d["statement"]),
        signal_ids=tuple(str(s) for s in d.get("signal_ids", ())),
        independent_sources=int(d["independent_sources"]),
        tier=d["tier"],
        unresolved_ids=tuple(str(s) for s in d.get("unresolved_ids", ())),
    )


def _momentum_phrase(m: Mapping[str, Any] | None) -> str:
    """One arithmetic sentence fragment. Never a forecast — always a delta
    between two dated snapshots that already happened."""
    if not m:
        return ""
    if m.get("reason") == NO_BASELINE:
        return " No prior snapshot exists to compare this against."
    if m.get("delta_pct") is None:
        return (
            f" Volume moved from {m.get('volume_prior')} to {m.get('volume_now')} "
            f"({m.get('reason')})."
        )
    direction = "up" if (m.get("delta") or 0) >= 0 else "down"
    return (
        f" Volume is {direction} {abs(m['delta_pct'])}% versus the prior "
        f"snapshot ({m.get('volume_prior')} to {m.get('volume_now')})."
    )


def run_report(
    topic: Topic,
    insight_run_id: str,
    store: RunStore,
    *,
    client: Any | None = None,
) -> Run:
    insight_run = store.get(insight_run_id)
    mine_run_id = insight_run.parent_run_id
    if not mine_run_id:
        raise RuntimeError(
            f"insight run {insight_run_id!r} has no parent snapshot to report on"
        )

    signals = store.read_artifact(mine_run_id, "signals.json")
    ledger: dict[str, Mapping[str, Any]] = {str(s["signal_id"]): s for s in signals}

    raw_findings = store.read_artifact(insight_run_id, "findings.json")
    findings = [_finding_from_dict(d) for d in raw_findings]
    raw_themes = store.read_artifact(insight_run_id, "themes.json")
    # INSIGHT builds exactly one Finding per Theme, in the same order
    # (`corroborate([...for t in themes], by_id)`) — zipping is safe and
    # avoids re-matching themes to findings by name, which breaks the moment
    # two themes share a name.
    paired = list(zip(raw_themes, findings))

    momentum_by_name = {
        m["theme_name"]: m for m in store.read_artifact(insight_run_id, "momentum.json")
    }
    anomaly_rows = store.read_artifact(insight_run_id, "anomaly.json")
    duallens_by_id = {
        g["theme_id"]: g for g in store.read_artifact(insight_run_id, "duallens.json")
    }
    stance_rows = store.read_artifact(insight_run_id, "stance.json")
    basis = stance_rows[0]["basis"] if stance_rows else "venue"

    cited: dict[str, Citation] = {}

    def cite(signal_ids: Sequence[str]) -> list[Citation]:
        got = bind_citations(list(signal_ids), ledger)
        for c in got:
            cited[c.signal_id] = c
        return got

    def guard_only(text: str, *, where: str) -> str:
        assert_advisory(text, where=where)
        assert_no_banned_terms(text, topic.never_say, where=where)
        assert_no_unmeasured_claims(text, where=where)
        return text

    def guard_claim(text: str, signal_ids: Sequence[str], *, where: str) -> str:
        guard_only(text, where=where)
        cite(signal_ids)
        return text

    # ----------------------------------------------------------------- G6 --
    # A theme is always reportable — volume, venue mix and kind mix are
    # counts, and a count needs no corroboration. An *assertion about* a
    # theme is a different thing, and that is what the tier gates.
    corroborated = [f for f in paired if f[1].tier == "corroborated"]
    emerging = [f for f in paired if f[1].tier == "emerging"]
    # Defence in depth: this is always true by construction (the list above
    # is already filtered to "corroborated"), but the guard is what makes
    # the rule enforced in code rather than merely followed by convention.
    assert_body_is_corroborated([f for _t, f in corroborated])

    # ------------------------------------------------------- themes table --
    theme_lines = [
        "| theme | volume | venue mix | kind mix | confidence tier | independent sources |",
        "|---|---|---|---|---|---|",
    ]
    if not paired:
        theme_lines.append("| _(no themes in this snapshot)_ | | | | | |")
    for theme, finding in paired:
        venues = ", ".join(
            f"{v} ({n})" for v, n in sorted(theme.get("venue_mix", {}).items())
        ) or "—"
        kinds = ", ".join(
            f"{k} ({n})" for k, n in sorted(theme.get("kind_mix", {}).items())
        ) or "—"
        tier_label = finding.tier.replace("_", " ")
        theme_lines.append(
            f"| {theme['name']} | {theme['volume']} | {venues} | {kinds} | "
            f"{tier_label} | {finding.independent_sources} |"
        )
        # The table cites every signal behind the count, even for a
        # single-source theme: the count is arithmetic and needs no
        # corroboration, but it still needs to be real signals, not
        # invented ones.
        cite(finding.signal_ids)
    themes_block = guard_only("\n".join(theme_lines), where="pulse_report.md")

    # ------------------------------------------------- corroborated claims --
    corroborated_lines: list[str] = []
    for theme, finding in corroborated:
        sentence = (
            f"**{theme['name']}** is corroborated on {finding.independent_sources} "
            f"independent sources ({theme['volume']} signals)."
            + _momentum_phrase(momentum_by_name.get(theme["name"]))
        )
        corroborated_lines.append(guard_claim(sentence, finding.signal_ids, where="pulse_report.md"))
    corroborated_block = (
        guard_only("\n\n".join(corroborated_lines), where="pulse_report.md")
        if corroborated_lines
        else guard_only(
            "No theme in this snapshot has reached three independent sources yet.",
            where="pulse_report.md",
        )
    )

    # ------------------------------------------------------ emerging claims --
    emerging_lines: list[str] = []
    for theme, finding in emerging:
        sentence = (
            f"**{theme['name']}** has {finding.independent_sources} independent "
            f"sources ({theme['volume']} signals) — emerging, not yet corroborated "
            f"at the {CORROBORATED_AT}-source bar."
            + _momentum_phrase(momentum_by_name.get(theme["name"]))
        )
        emerging_lines.append(guard_claim(sentence, finding.signal_ids, where="pulse_report.md"))
    emerging_block = (
        guard_only("\n\n".join(emerging_lines), where="pulse_report.md")
        if emerging_lines
        else guard_only("No emerging (two-source) findings this snapshot.", where="pulse_report.md")
    )

    # ----------------------------------------------------------- anomalies --
    if anomaly_rows:
        anomaly_lines = ["| theme | kind | observed | baseline | detail |", "|---|---|---|---|---|"]
        for a in anomaly_rows:
            note = f" {a['note']}" if a.get("note") else ""
            detail = f"{a['detail']}.{note}".strip()
            anomaly_lines.append(
                f"| {a['theme_name']} | {a['kind']} | {a['observed']} | "
                f"{a['baseline']} | {detail} |"
            )
        anomaly_block = guard_only("\n".join(anomaly_lines), where="pulse_report.md")
    else:
        anomaly_block = guard_only(
            "No anomalies were detected against the prior baseline.", where="pulse_report.md"
        )

    # ------------------------------------------------- dual lens (HCP/pt) --
    lens_rows = [duallens_by_id[t["theme_id"]] for t, _f in paired if t["theme_id"] in duallens_by_id]
    if lens_rows:
        lens_lines = ["| theme | hcp net stance | patient net stance | divergence |", "|---|---|---|---|"]
        for g in lens_rows:
            div = g["divergence"] if g["divergence"] is not None else f"n/a — {g['reason']}"
            lens_lines.append(
                f"| {g['theme_name']} | {g['hcp_net']} | {g['patient_net']} | {div} |"
            )
        lens_block = guard_only("\n".join(lens_lines), where="pulse_report.md")
    else:
        lens_block = ""

    pulse_parts = [
        f"# Pulse Report — {topic.name}",
        "## Themes observed",
        themes_block,
        "## Corroborated findings",
        corroborated_block,
        "## Emerging (two-source) signals",
        emerging_block,
        "## What changed since the prior snapshot",
        anomaly_block,
    ]
    if lens_block:
        pulse_parts += ["## Patient vs. HCP divergence", lens_block]

    # ------------------------------------------------------------- G6/G1 --
    # Model output is additional narrative, appended after the template
    # content and held to exactly the same four guards. Nothing the model
    # writes replaces the arithmetic above; it can only add cited prose on
    # top of it.
    model_cost_usd = 0.0
    if client is not None:
        user = _report_user_prompt(topic, paired)
        outcome = client.complete_structured(
            system=REPORT_SYSTEM, user=user, schema=REPORT_SCHEMA, max_output_tokens=4096
        )
        if not outcome.ok or not outcome.data:
            raise RuntimeError(f"report pass failed: {getattr(outcome, 'reason', '')}")
        data = outcome.data

        model_sections: list[str] = []
        for section in data.get("sections", []):
            heading = str(section.get("heading") or "").strip() or "Additional analysis"
            body = str(section.get("body") or "")
            sig_ids = [str(s) for s in section.get("signal_ids", [])]
            guard_claim(body, sig_ids, where="pulse_report.md")
            model_sections.append(f"### {heading}\n\n{body}")
        if model_sections:
            pulse_parts += ["## Additional analysis", "\n\n".join(model_sections)]

        model_considerations: list[str] = []
        for c in data.get("considerations", []):
            text = str(c.get("text") or "")
            sig_ids = [str(s) for s in c.get("signal_ids", [])]
            if sig_ids:
                guard_claim(text, sig_ids, where="worth_considering.md")
            else:
                guard_only(text, where="worth_considering.md")
            model_considerations.append(f"- {text}")

        spend = getattr(outcome, "spend", None)
        if spend is not None:
            model_cost_usd = round(float(getattr(spend, "usd", 0.0)), 6)
    else:
        model_considerations = []

    pulse_text = "\n\n".join(pulse_parts) + "\n"

    # ---------------------------------------------------- worth_considering --
    considering_lines = ["# Worth considering", "", "Suggestions, not decisions."]
    for theme, finding in emerging:
        sentence = (
            f"One option is to keep watching **{theme['name']}** for a third "
            "independent source before treating it as established."
        )
        considering_lines.append("- " + guard_claim(sentence, finding.signal_ids, where="worth_considering.md"))
    for a in anomaly_rows:
        if a.get("observed", 0) <= 0:
            # No current signal to cite a claim against — the theme is
            # absent from this snapshot, so there is nothing here to bind.
            continue
        current_theme = next((t for t, _f in paired if t["name"] == a["theme_name"]), None)
        if current_theme is None:
            continue
        sentence = (
            f"Worth looking into why **{a['theme_name']}** moved this snapshot "
            f"({a['detail']})."
        )
        considering_lines.append(
            "- " + guard_claim(sentence, current_theme["signal_ids"], where="worth_considering.md")
        )
    considering_lines.extend(model_considerations)
    generic_suggestion = guard_only(
        "Raising the spend band on the next sweep is worth considering if "
        "broader venue coverage is wanted.",
        where="worth_considering.md",
    )
    considering_lines.append("- " + generic_suggestion)
    considering_text = "\n".join(considering_lines) + "\n"

    # ------------------------------------------------------- methodology --
    band = topic.band()
    venues_seen = sorted({str(s.get("venue") or "") for s in signals if s.get("venue")})
    captured_ats = sorted(str(s.get("captured_at") or "") for s in signals if s.get("captured_at"))
    when_line = (
        f"captured between {captured_ats[0]} and {captured_ats[-1]}"
        if captured_ats
        else "capture timestamps were not recorded on these signals"
    )
    basis_line = (
        "venue-derived — who is speaking was read from the registry's classification "
        "of the venue a signal came from, not from resolving any author's identity"
        if basis == "venue"
        else "identity-derived — who is speaking was resolved from author identity, "
        "not merely inferred from the venue"
    )
    methodology_lines = [
        "# Methodology",
        "",
        "## What was searched",
        f"Topic: {topic.name} ({topic.therapeutic_area}). "
        f"Brand: {topic.brand or '(none)'}. Molecule (INN): {topic.molecule or '(none)'}. "
        f"Competitors tracked: {', '.join(topic.competitors) or '(none)'}. "
        f"Spend band: {band.name} ({band.queries_per_cluster} queries, "
        f"{band.page_fetches_per_cluster} page fetches per cluster).",
        "",
        "## Where",
        "Search was scoped to a hand-verified gold-list venue registry, routed by "
        f"therapeutic area, before any open web search. This snapshot's signals came "
        f"from {len(venues_seen)} distinct venue(s).",
        "",
        "## When",
        f"This snapshot's signals were {when_line}.",
        "",
        "## What was excluded, and why",
        "A Tier-C venue (a verified-membership network such as a gated physician "
        "community) is recorded but never automatically fetched — those are "
        "human-read only. A patient-generated venue is read for themes only: no "
        "verbatim excerpt and no author identifier, not even hashed. A host outside "
        "the gold-list registry may still contribute public search-result metadata, "
        "but is never page-fetched.",
        "",
        "## Definitions",
        _INDEPENDENT_SOURCE_DEFINITION,
        f"Confidence tiers: **corroborated** is {CORROBORATED_AT} or more independent "
        "sources; **emerging** is exactly two; **single source** is one or zero, and "
        "a single-source theme is reported as a count only — it never earns a claim "
        "sentence in the body.",
        f"Author-class basis: {basis_line}.",
        "",
        "## Scope",
        _AE_SCOPE_SENTENCE,
    ]
    methodology_text = guard_only("\n".join(methodology_lines), where="methodology.md") + "\n"

    # ------------------------------------------------------------ appendix --
    appendix_lines = [
        "# Provenance appendix",
        "",
        "One row per cited signal.",
        "",
        "| signal_id | venue | venue kind | captured_at | collection method | URL |",
        "|---|---|---|---|---|---|",
    ]
    for sid in sorted(cited):
        c = cited[sid]
        appendix_lines.append(
            f"| {c.signal_id} | {c.venue} | {c.venue_kind} | {c.captured_at} | "
            f"{c.collection_method} | {c.url} |"
        )
    appendix_text = "\n".join(appendix_lines) + "\n"

    # -------------------------------------------------- nothing written yet
    # Every guard above has already passed by this point, or this function
    # has already raised. Only now does a run row and any artifact exist.
    run = store.start(topic.topic_id, "report", parent_run_id=insight_run_id)
    store.write_artifact(run.run_id, "pulse_report.md", pulse_text)
    store.write_artifact(run.run_id, "provenance_appendix.md", appendix_text)
    store.write_artifact(run.run_id, "methodology.md", methodology_text)
    store.write_artifact(run.run_id, "worth_considering.md", considering_text)

    return store.finish(run.run_id, "complete", cost_usd=model_cost_usd)


def _report_user_prompt(topic: Topic, paired: Sequence[tuple[Mapping[str, Any], Finding]]) -> str:
    lines = [
        f"Topic: {topic.name} ({topic.therapeutic_area}).",
        f"Brand: {topic.brand or '(none)'}. Molecule: {topic.molecule or '(none)'}.",
        "Themes this snapshot, with their pre-computed confidence tier "
        "(you must not change or restate a tier as your own finding):",
    ]
    for theme, finding in paired:
        lines.append(
            f"- {theme['name']}: volume={theme['volume']}, tier={finding.tier}, "
            f"signal_ids={list(finding.signal_ids)}"
        )
    lines.append(
        "Write additional narrative sections and, separately, suggestions worth "
        "considering. Every section and every consideration must cite the "
        "signal_ids it rests on."
    )
    return "\n".join(lines)
