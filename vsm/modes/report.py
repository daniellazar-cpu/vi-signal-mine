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
from vsm.modes.vocabulary import SWEEP_SIZE
from vsm.storage import ReadDeadline, read_required
from vsm.analysis.momentum import NO_BASELINE
from vsm.guards.advisory import assert_advisory
from vsm.guards.citations import Citation, bind_citations
from vsm.guards.claims import assert_no_unmeasured_claims
from vsm.guards.corroboration import assert_body_is_corroborated
from vsm.guards.terms import assert_no_banned_terms
from vsm.llm.prompts import REPORT_SYSTEM
from vsm.llm.schema import REPORT_SCHEMA
from vsm.mining.signals import any_synthetic
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

#: The safety rail's REPORT-facing sentence (Task: offline demonstration
#: miner). Stated once here so the wording is identical everywhere it
#: appears — the pulse report banner, the methodology scope section and the
#: worth-considering note all cite this exact string, never a paraphrase.
_SYNTHETIC_NOTICE = (
    "Every signal behind this document was fabricated by the offline "
    "demonstration miner, not collected from the web. Do not treat any "
    "figure, excerpt or citation here as real, and do not share this as a "
    "client deliverable."
)

_INDEPENDENT_SOURCE_DEFINITION = (
    "An independent source is defined as a distinct post or a distinct "
    "publisher: a true forum or patient community counts one post as one "
    "source, and every other venue counts one publisher (its registrable "
    "domain) as one source, no matter how many pages that publisher runs."
)


#: A net-stance cell in the dual-lens table. ``None`` is not a zero and is
#: not a blank: ``net_stance`` returns ``None`` when *nothing* of that author
#: class was classified for the theme, so the cell states that fact. Printing
#: Python's ``None`` here — which is what an f-string does with it, and what
#: this table used to do — puts leaked internals in the one artifact a client
#: reads, and printing ``0`` would assert neutrality nobody expressed.
_NET_CELL_REASON = {
    "hcp": "not read — no clinician-class signal in this theme",
    "patient": "not read — no patient-class signal in this theme",
}


def _net_cell(value: float | None, which: str) -> str:
    if value is None:
        return _NET_CELL_REASON[which]
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}"


_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def _long_date(stamp: str) -> str:
    """`31 July 2026` from an ISO stamp — the date a client reads.

    A raw `2026-07-31T00:00:00+00:00` in the one artifact whose job is to be
    checked reads as machine output, and the time-of-day is a crawl
    timestamp precise to a second that means nothing to the reader. The full
    stamp is still in `signals.json` and in the provenance appendix, which is
    where a reader who wants the exact second goes. A string that does not
    parse comes back unchanged rather than guessed at.
    """
    head = stamp[:10]
    parts = head.split("-")
    if len(parts) != 3 or not all(x.isdigit() for x in parts):
        return stamp
    year, month, day = (int(x) for x in parts)
    if not 1 <= month <= 12:
        return stamp
    return f"{day} {_MONTHS[month - 1]} {year}"


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
    run_id: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> Run:
    # See vsm.modes.mine.run_mine's identical comment: these overrides exist
    # only for vsm.demo.seed_demo_topic, are `None` for every real caller, and
    # are spread in as an empty dict in that case so this still works against
    # a backend (PostgresRunStore) whose start()/finish() take no such
    # parameters at all.
    start_overrides = {
        k: v for k, v in {"run_id": run_id, "started_at": started_at}.items()
        if v is not None
    }
    finish_overrides = {"finished_at": finished_at} if finished_at is not None else {}
    insight_run = store.get(insight_run_id)
    mine_run_id = insight_run.parent_run_id
    if not mine_run_id:
        raise RuntimeError(
            f"insight run {insight_run_id!r} has no parent snapshot to report on"
        )

    # One waiting budget for all seven required reads, not one each — see
    # ReadDeadline. The first read absorbs the lag; the rest draw on the
    # remainder, so a genuine absence costs the budget once rather than
    # seven times and cannot push this past the function ceiling.
    deadline = ReadDeadline()
    # `read_required`, not a plain read: a transient 404 from a blob that has
    # not propagated to this region yet used to surface to the user as "No
    # snapshot to report on" — telling them their snapshot was lost while it
    # sat in the store. See vsm/storage.py:read_required.
    signals = read_required(store, mine_run_id, "signals.json", deadline=deadline)
    ledger: dict[str, Mapping[str, Any]] = {str(s["signal_id"]): s for s in signals}
    # The safety rail. One fabricated row is enough to mark every artifact
    # this call writes — see vsm.mining.signals.any_synthetic.
    synthetic = any_synthetic(signals)

    raw_findings = read_required(store, insight_run_id, "findings.json", deadline=deadline)
    findings = [_finding_from_dict(d) for d in raw_findings]
    raw_themes = read_required(store, insight_run_id, "themes.json", deadline=deadline)
    # INSIGHT builds exactly one Finding per Theme, in the same order
    # (`corroborate([...for t in themes], by_id)`) — zipping is safe and
    # avoids re-matching themes to findings by name, which breaks the moment
    # two themes share a name.
    paired = list(zip(raw_themes, findings))

    momentum_by_name = {
        m["theme_name"]: m for m in read_required(store, insight_run_id, "momentum.json", deadline=deadline)
    }
    anomaly_rows = read_required(store, insight_run_id, "anomaly.json", deadline=deadline)
    duallens_by_id = {
        g["theme_id"]: g for g in read_required(store, insight_run_id, "duallens.json", deadline=deadline)
    }
    stance_rows = read_required(store, insight_run_id, "stance.json", deadline=deadline)
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
                f"| {g['theme_name']} | {_net_cell(g['hcp_net'], 'hcp')} | "
                f"{_net_cell(g['patient_net'], 'patient')} | {div} |"
            )
        lens_block = guard_only("\n".join(lens_lines), where="pulse_report.md")
    else:
        lens_block = ""

    pulse_parts = [f"# Pulse Report — {topic.name}"]
    if synthetic:
        pulse_parts.append(
            guard_only(f"**Synthetic demonstration run.** {_SYNTHETIC_NOTICE}", where="pulse_report.md")
        )
    pulse_parts += [
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
    if synthetic:
        considering_lines.append(guard_only(_SYNTHETIC_NOTICE, where="worth_considering.md"))
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
        # "band" is banned from anything a reader sees, and these strings go to
        # a client inside the methodology and worth-considering documents — the
        # same vocabulary problem one layer deeper than the interface.
        "Running a wider sweep next time is worth considering if "
        "broader venue coverage is wanted.",
        where="worth_considering.md",
    )
    considering_lines.append("- " + generic_suggestion)
    considering_text = "\n".join(considering_lines) + "\n"

    # ------------------------------------------------------- methodology --
    band = topic.band()
    venues_seen = sorted({str(s.get("venue") or "") for s in signals if s.get("venue")})
    captured_ats = sorted(str(s.get("captured_at") or "") for s in signals if s.get("captured_at"))
    if not captured_ats:
        when_line = "capture timestamps were not recorded on these signals"
    elif captured_ats[0][:10] == captured_ats[-1][:10]:
        # One day is one date, not a range. "between X and X" is a
        # zero-width window presented as a window — the sort of detail that
        # makes a reader distrust every other figure in the document.
        when_line = f"all captured on {_long_date(captured_ats[0])}"
    else:
        when_line = (
            f"captured between {_long_date(captured_ats[0])} and "
            f"{_long_date(captured_ats[-1])}"
        )
    # Written so the claim is assertable, not just gesturable: the exact
    # phrases "author class" and "derived from the venue" / "derived from
    # resolved author identity" state the basis in words a test — or a
    # reader — can pin, rather than relying on the word "venue" appearing
    # somewhere in the document for an unrelated reason (it does, in the
    # "Where" section above, which is why a bare substring check on "venue"
    # is not a real assertion about this claim).
    basis_line = (
        "author class was derived from the venue a signal came from — the "
        "registry's classification of the venue, not any resolved author identity"
        if basis == "venue"
        else "author class was derived from resolved author identity, not merely "
        "from the venue a signal came from"
    )
    methodology_lines = [
        "# Methodology",
        "",
        "## What was searched",
        f"Topic: {topic.name} ({topic.therapeutic_area}). "
        f"Brand: {topic.brand or '(none)'}. Molecule (INN): {topic.molecule or '(none)'}. "
        f"Competitors tracked: {', '.join(topic.competitors) or '(none)'}. "
        f"Sweep size: {SWEEP_SIZE.get(band.name, band.name)} "
        f"({band.queries_per_cluster} queries, "
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
    if synthetic:
        # Stated once, in the scope section, beside the other limits this
        # report carries — the safety rail for the offline demonstration
        # miner (Task: get_miner). Same sentence everywhere it appears; see
        # _SYNTHETIC_NOTICE.
        methodology_lines.append(_SYNTHETIC_NOTICE)
    methodology_text = guard_only("\n".join(methodology_lines), where="methodology.md") + "\n"

    # ------------------------------------------------------------ appendix --
    appendix_lines = [
        "# Provenance appendix",
        "",
        "One row per cited signal.",
    ]
    if synthetic:
        appendix_lines.append(f"**{_SYNTHETIC_NOTICE}**")
    appendix_lines += [
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
    run = store.start(
        topic.topic_id, "report", parent_run_id=insight_run_id, **start_overrides
    )
    store.write_artifact(run.run_id, "pulse_report.md", pulse_text)
    store.write_artifact(run.run_id, "provenance_appendix.md", appendix_text)
    store.write_artifact(run.run_id, "methodology.md", methodology_text)
    store.write_artifact(run.run_id, "worth_considering.md", considering_text)

    return store.finish(
        run.run_id, "complete", cost_usd=model_cost_usd, **finish_overrides
    )


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
