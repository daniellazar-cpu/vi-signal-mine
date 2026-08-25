"""The app factory: routes over the engine's two stores, and nothing else.

Every route either reads an artifact the engine already wrote, or calls one
of the three ``vsm.modes`` entry points and redirects to the run it created.
No route computes a business number the engine has not already computed —
the one exception is presentation-only reshaping (sorting, grouping display
strings, building the forest-plot SVG from numbers that are already final).

``StrictUndefined`` is load-bearing here: a typo'd template variable must
500, not silently render blank, because a blank cell reads exactly like a
zero and this whole tool exists to keep the two apart. Every route below
therefore builds a complete context dict rather than leaning on Jinja
defaults.
"""

from __future__ import annotations

import re
from html import escape as _esc
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from starlette.templating import Jinja2Templates

from vsm.config import get_settings
from vsm.errors import NoSuchRun, NoSuchTopic, VsmError
from vsm.guards.cost import estimate_run_usd
from vsm.llm.client import get_client
from vsm.mining.venues import kind_of
from vsm.modes.insight import run_insight
from vsm.modes.mine import run_mine
from vsm.modes.report import run_report
from vsm.topics.model import BANDS
from vsm.ui.render import forest_plot_svg, fmt_dt, net_stance_text, pct, sparkline_svg, usd

__all__ = ["create_app"]

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"

_TIER_LABELS = {
    "corroborated": "Corroborated",
    "emerging": "Emerging",
    "single_source": "Single source",
}
_KIND_LABELS = {
    "hcp_discussion": "Clinician discussion",
    "patient_community": "Patient community",
    "evidence": "Evidence",
    "guideline_body": "Guideline body",
    "regulatory": "Regulatory",
    "drug_reference": "Drug reference",
}
_AUTHOR_CLASS_LABELS = {
    "hcp": "HCP",
    "patient": "Patient",
    "institutional": "Institutional",
    "unknown": "Unknown",
}
_STANCE_LABELS = {
    "positive": "Positive",
    "negative": "Negative",
    "mixed": "Mixed",
    "neutral": "Neutral",
    "unclear": "Unclear",
}
_ANOMALY_KIND_LABELS = {
    "theme_appeared": "Theme appeared",
    "theme_vanished": "Theme vanished",
    "volume_spike": "Volume spike",
    "volume_collapse": "Volume collapse",
}

_STAGES: dict[str, list[tuple[str, str]]] = {
    "mine": [
        ("plan.json", "Lexicon and plan"),
        ("signals.json", "Sweep"),
        ("coverage.json", "Coverage"),
        ("provenance.json", "Provenance"),
        ("cost.json", "Cost accounting"),
    ],
    "insight": [
        ("entities.json", "Entities"),
        ("themes.json", "Themes"),
        ("stance.json", "Stance by author class"),
        ("duallens.json", "Dual-lens gap"),
        ("momentum.json", "Momentum"),
        ("anomaly.json", "Anomalies"),
        ("findings.json", "Corroboration"),
    ],
    "report": [
        ("pulse_report.md", "Pulse report"),
        ("provenance_appendix.md", "Provenance appendix"),
        ("methodology.md", "Methodology"),
        ("worth_considering.md", "Worth considering"),
    ],
}

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
# Deliberately narrow: only a `_..._` span whose underscores sit at a word
# boundary counts as emphasis. Without the boundary check this matches straight
# through identifiers like `hcp_discussion, patient_community` — the first
# `_` and the next unrelated `_` pair up and swallow everything between them,
# including the space and comma. `kind_mix`/`venue_mix` keys are exactly that
# shape, so this is not a hypothetical.
_ITALIC_RE = re.compile(r"(?<!\w)_([^_\s][^_]*?)_(?!\w)")
_PIPE_TABLE_ROW = re.compile(r"^\s*\|")


def _tier_label(tier: str | None) -> str:
    return _TIER_LABELS.get(tier or "", tier or "not scored")


def _kind_label(kind: str | None) -> str:
    return _KIND_LABELS.get(kind or "", "Not on the gold-list registry")


def _class_label(value: str | None) -> str:
    return _AUTHOR_CLASS_LABELS.get(value or "", value or "unknown")


def _stance_label(value: str | None) -> str:
    return _STANCE_LABELS.get(value or "", value or "unclear")


def _anomaly_label(kind: str | None) -> str:
    return _ANOMALY_KIND_LABELS.get(kind or "", kind or "change")


def _inline_md(text: str) -> str:
    escaped = _BOLD_RE.sub(r"<strong>\1</strong>", _esc(text))
    return _ITALIC_RE.sub(r"<em>\1</em>", escaped)


def _render_pipe_table(lines: list[str]) -> str:
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines]
    header, rest = rows[0], rows[1:]
    if rest and set("".join(rest[0])) <= {"-", " "}:
        rest = rest[1:]
    thead = "".join(f"<th>{_inline_md(h)}</th>" for h in header)
    tbody = "".join(
        "<tr>" + "".join(f"<td>{_inline_md(c)}</td>" for c in row) + "</tr>"
        for row in rest
    )
    return f'<table class="md-table"><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>'


def _markdown_lite_to_html(text: str | None) -> str:
    """Just enough Markdown to preview the four REPORT artifacts honestly.

    Not a general renderer — a line-based pass for exactly the shapes
    ``vsm.modes.report`` is known to emit: ``#``/``##``/``###`` headings,
    pipe tables, ``- `` bullet lists, and plain paragraphs with ``**bold**``,
    in any mix of blank-line-separated or tight (heading directly followed
    by its body, as ``methodology.md`` writes it) grouping. No third-party
    Markdown dependency is on the allowed list, so this is deliberately
    narrow rather than general — but it walks line by line rather than
    classifying a whole blank-line-delimited block at once, because both
    real artifacts mix a heading or a paragraph directly against the next
    element with no blank line in between, and a whole-block classifier
    either drops that trailing content or flattens a bullet list into one
    run-on paragraph.
    """
    if not text:
        return ""
    lines = text.strip("\n").split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
        elif stripped.startswith("### "):
            out.append(f"<h3>{_inline_md(stripped[4:])}</h3>")
            i += 1
        elif stripped.startswith("## "):
            out.append(f"<h2>{_inline_md(stripped[3:])}</h2>")
            i += 1
        elif stripped.startswith("# "):
            out.append(f"<h1>{_inline_md(stripped[2:])}</h1>")
            i += 1
        elif _PIPE_TABLE_ROW.match(stripped):
            block = []
            while i < n and _PIPE_TABLE_ROW.match(lines[i].strip()):
                block.append(lines[i].strip())
                i += 1
            out.append(_render_pipe_table(block))
        elif stripped.startswith("- "):
            items = []
            while i < n and lines[i].strip().startswith("- "):
                items.append(f"<li>{_inline_md(lines[i].strip()[2:])}</li>")
                i += 1
            out.append(f"<ul>{''.join(items)}</ul>")
        else:
            block = []
            while (
                i < n
                and lines[i].strip()
                and not lines[i].strip().startswith(("#", "- "))
                and not _PIPE_TABLE_ROW.match(lines[i].strip())
            ):
                block.append(lines[i].strip())
                i += 1
            out.append(f"<p>{_inline_md(' '.join(block))}</p>")
    return "".join(out)


def _parse_pipe_table_rows(text: str | None) -> list[list[str]]:
    """The provenance appendix's one table, as raw cell lists.

    Written against the exact shape ``run_report`` emits: a header row, a
    ``|---|...`` separator, then one data row per cited signal.
    """
    if not text:
        return []
    lines = [ln for ln in text.splitlines() if _PIPE_TABLE_ROW.match(ln)]
    if len(lines) < 2:
        return []
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines]
    return rows[2:]


def _split_lines(text: str) -> tuple[str, ...]:
    return tuple(ln.strip() for ln in text.splitlines() if ln.strip())


def _band_cards() -> list[dict[str, Any]]:
    cards = []
    for name in ("probe", "standard", "deep"):
        band = BANDS[name]
        cards.append({"band": band, "estimate": estimate_run_usd(band, cluster_count=1)})
    return cards


def create_app(topic_store: Any | None = None, run_store: Any | None = None) -> FastAPI:
    if topic_store is None or run_store is None:
        from vsm.storage import open_stores

        ts, rs = open_stores(get_settings())
        topic_store = topic_store if topic_store is not None else ts
        run_store = run_store if run_store is not None else rs

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        undefined=StrictUndefined,
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["usd"] = usd
    env.filters["pct"] = pct
    env.filters["net"] = net_stance_text
    env.filters["dt"] = fmt_dt
    env.globals["tier_label"] = _tier_label
    env.globals["kind_label"] = _kind_label
    env.globals["class_label"] = _class_label
    env.globals["stance_label"] = _stance_label
    env.globals["anomaly_label"] = _anomaly_label

    templates = Jinja2Templates(env=env)

    app = FastAPI(title="Vi Signal Mine")
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    def render(request: Request, name: str, status_code: int = 200, **ctx: Any) -> HTMLResponse:
        return templates.TemplateResponse(request, name, ctx, status_code=status_code)

    def error_page(request: Request, status_code: int, title: str, message: str) -> HTMLResponse:
        return render(request, "error.html", status_code=status_code, title=title, message=message)

    # --------------------------------------------------------------- topics --

    def _topic_row(topic: Any) -> dict[str, Any]:
        snapshots = run_store.snapshots(topic.topic_id)
        all_runs = run_store.for_topic(topic.topic_id)
        spend = round(sum(r.cost_usd for r in all_runs), 4)
        volumes: list[int] = []
        for run in snapshots:
            try:
                rows = run_store.read_artifact(run.run_id, "signals.json")
            except FileNotFoundError:
                rows = []
            volumes.append(len(rows))
        return {
            "topic": topic,
            "snapshot_count": len(snapshots),
            "last_snapshot_run_id": snapshots[-1].run_id if snapshots else None,
            "last_snapshot_at": snapshots[-1].started_at if snapshots else None,
            "spend_to_date": spend,
            "latest_volume": volumes[-1] if volumes else None,
            "sparkline": sparkline_svg(volumes) if len(volumes) >= 2 else "",
        }

    @app.get("/", response_class=HTMLResponse)
    def topics_index(request: Request) -> HTMLResponse:
        rows = [_topic_row(t) for t in topic_store.list()]
        return render(request, "topics.html", rows=rows)

    _BLANK_TOPIC_VALUES = {
        "name": "", "therapeutic_area": "", "spend_band": "probe", "brand": "",
        "molecule": "", "competitors": "", "questions": "", "never_say": "",
    }

    @app.get("/topics/new", response_class=HTMLResponse)
    def topic_new(request: Request) -> HTMLResponse:
        return render(
            request, "topic_form.html", mode="create", topic=None,
            band_cards=_band_cards(), errors={}, values=dict(_BLANK_TOPIC_VALUES),
        )

    @app.get("/topics/{topic_id}/edit", response_class=HTMLResponse)
    def topic_edit(request: Request, topic_id: str) -> HTMLResponse:
        try:
            topic = topic_store.get(topic_id)
        except NoSuchTopic:
            return error_page(request, 404, "Topic not found", f"No topic with id {topic_id!r}.")
        values = {
            "name": topic.name,
            "therapeutic_area": topic.therapeutic_area,
            "spend_band": topic.spend_band,
            "brand": topic.brand or "",
            "molecule": topic.molecule or "",
            "competitors": "\n".join(topic.competitors),
            "questions": "\n".join(topic.questions),
            "never_say": "\n".join(topic.never_say),
        }
        return render(
            request, "topic_form.html", mode="edit", topic=topic,
            band_cards=_band_cards(), errors={}, values=values,
        )

    def _validate_topic_form(name: str, therapeutic_area: str, spend_band: str) -> dict[str, str]:
        errors: dict[str, str] = {}
        if not name.strip():
            errors["name"] = "A topic needs a name."
        if not therapeutic_area.strip():
            errors["therapeutic_area"] = "A therapeutic area is required — it routes the venue registry."
        if spend_band not in BANDS:
            errors["spend_band"] = "Choose one of the three spend bands."
        return errors

    @app.post("/topics", response_class=HTMLResponse)
    async def topics_create(
        request: Request,
        name: str = Form(""),
        therapeutic_area: str = Form(""),
        spend_band: str = Form(""),
        brand: str = Form(""),
        molecule: str = Form(""),
        competitors: str = Form(""),
        questions: str = Form(""),
        never_say: str = Form(""),
    ) -> Any:
        errors = _validate_topic_form(name, therapeutic_area, spend_band)
        values = {
            "name": name, "therapeutic_area": therapeutic_area, "spend_band": spend_band,
            "brand": brand, "molecule": molecule, "competitors": competitors,
            "questions": questions, "never_say": never_say,
        }
        if errors:
            return render(
                request, "topic_form.html", status_code=422, mode="create", topic=None,
                band_cards=_band_cards(), errors=errors, values=values,
            )
        topic_store.create(
            name=name.strip(), therapeutic_area=therapeutic_area.strip(), spend_band=spend_band,
            brand=(brand.strip() or None), molecule=(molecule.strip() or None),
            competitors=_split_lines(competitors), questions=_split_lines(questions),
            never_say=_split_lines(never_say),
        )
        return RedirectResponse(url="/", status_code=303)

    @app.post("/topics/{topic_id}", response_class=HTMLResponse)
    async def topics_update(
        request: Request,
        topic_id: str,
        name: str = Form(""),
        therapeutic_area: str = Form(""),
        spend_band: str = Form(""),
        brand: str = Form(""),
        molecule: str = Form(""),
        competitors: str = Form(""),
        questions: str = Form(""),
        never_say: str = Form(""),
    ) -> Any:
        try:
            topic = topic_store.get(topic_id)
        except NoSuchTopic:
            return error_page(request, 404, "Topic not found", f"No topic with id {topic_id!r}.")
        errors = _validate_topic_form(name, therapeutic_area, spend_band)
        values = {
            "name": name, "therapeutic_area": therapeutic_area, "spend_band": spend_band,
            "brand": brand, "molecule": molecule, "competitors": competitors,
            "questions": questions, "never_say": never_say,
        }
        if errors:
            return render(
                request, "topic_form.html", status_code=422, mode="edit", topic=topic,
                band_cards=_band_cards(), errors=errors, values=values,
            )
        topic_store.update(
            topic_id,
            name=name.strip(), therapeutic_area=therapeutic_area.strip(), spend_band=spend_band,
            brand=(brand.strip() or None), molecule=(molecule.strip() or None),
            competitors=_split_lines(competitors), questions=_split_lines(questions),
            never_say=_split_lines(never_say),
        )
        return RedirectResponse(url="/", status_code=303)

    @app.get("/topics/{topic_id}/confirm", response_class=HTMLResponse)
    def topic_confirm(request: Request, topic_id: str, band: str = "") -> HTMLResponse:
        try:
            topic = topic_store.get(topic_id)
        except NoSuchTopic:
            return error_page(request, 404, "Topic not found", f"No topic with id {topic_id!r}.")
        chosen = band or topic.spend_band
        if chosen not in BANDS:
            return error_page(
                request, 400, "Unknown spend band",
                f"{chosen!r} is not one of probe, standard, deep.",
            )
        settings = get_settings()
        estimate = estimate_run_usd(BANDS[chosen], cluster_count=1)
        return render(
            request, "confirm.html", topic=topic, band=BANDS[chosen], estimate=estimate,
            cap_usd=settings.run_cost_cap_usd, changes_band=(chosen != topic.spend_band),
        )

    @app.post("/topics/{topic_id}/mine")
    def topic_mine(request: Request, topic_id: str, band: str = Form("")) -> Any:
        try:
            topic = topic_store.get(topic_id)
        except NoSuchTopic:
            return error_page(request, 404, "Topic not found", f"No topic with id {topic_id!r}.")
        chosen = band or topic.spend_band
        if chosen not in BANDS:
            return error_page(
                request, 400, "Unknown spend band",
                f"{chosen!r} is not one of probe, standard, deep.",
            )
        if chosen != topic.spend_band:
            topic = topic_store.update(topic_id, spend_band=chosen)
        settings = get_settings()
        try:
            client = get_client(settings)
            run = run_mine(topic, run_store, client=client, cap_usd=settings.run_cost_cap_usd)
        except VsmError as exc:
            return error_page(request, 400, "The sweep could not run", str(exc))
        return RedirectResponse(url=f"/runs/{run.run_id}", status_code=303)

    # ----------------------------------------------------------------- runs --

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_stream(request: Request, run_id: str) -> HTMLResponse:
        try:
            run = run_store.get(run_id)
        except NoSuchRun:
            return error_page(request, 404, "Run not found", f"No run with id {run_id!r}.")
        try:
            topic = topic_store.get(run.topic_id)
        except NoSuchTopic:
            topic = None
        art_dir = run_store.artifacts_dir(run.run_id)
        stages = [
            {"label": label, "file": fname, "done": (art_dir / fname).exists()}
            for fname, label in _STAGES.get(run.mode, [])
        ]
        cost_detail = None
        if run.mode == "mine":
            try:
                cost_detail = run_store.read_artifact(run.run_id, "cost.json")
            except FileNotFoundError:
                cost_detail = None
        next_snapshot_run_id = run.run_id if run.mode == "mine" else None
        next_insight_run_id = run.run_id if run.mode == "insight" else None
        return render(
            request, "run.html", run=run, topic=topic, stages=stages,
            cost_detail=cost_detail, next_snapshot_run_id=next_snapshot_run_id,
            next_insight_run_id=next_insight_run_id,
        )

    @app.get("/runs/{run_id}/events")
    def run_events(run_id: str) -> JSONResponse:
        try:
            run = run_store.get(run_id)
        except NoSuchRun:
            return JSONResponse({"error": f"no run {run_id!r}"}, status_code=404)
        return JSONResponse(
            {"run_id": run.run_id, "mode": run.mode, "status": run.status,
             "cost_usd": run.cost_usd, "note": run.note}
        )

    @app.get("/runs/{run_id}/snapshot", response_class=HTMLResponse)
    def run_snapshot(
        request: Request, run_id: str,
        venue: str = "", kind: str = "", tier: str = "", date: str = "",
    ) -> HTMLResponse:
        try:
            run = run_store.get(run_id)
        except NoSuchRun:
            return error_page(request, 404, "Run not found", f"No run with id {run_id!r}.")
        try:
            topic = topic_store.get(run.topic_id)
        except NoSuchTopic:
            topic = None
        try:
            raw_rows = run_store.read_artifact(run.run_id, "signals.json")
        except FileNotFoundError:
            raw_rows = []
        try:
            coverage = run_store.read_artifact(run.run_id, "coverage.json")
        except FileNotFoundError:
            coverage = None

        enriched = []
        for r in raw_rows:
            row = dict(r)
            row["venue_kind"] = kind_of(str(row.get("venue") or "")) or ""
            row["date_only"] = str(row.get("captured_at") or "")[:10]
            enriched.append(row)

        venues = sorted({r["venue"] for r in enriched if r.get("venue")})
        kinds = sorted({r["venue_kind"] for r in enriched if r["venue_kind"]})
        tiers = sorted({r.get("collection_tier") for r in enriched if r.get("collection_tier")})
        dates = sorted({r["date_only"] for r in enriched if r["date_only"]})

        filtered = enriched
        if venue:
            filtered = [r for r in filtered if r.get("venue") == venue]
        if kind:
            filtered = [r for r in filtered if r["venue_kind"] == kind]
        if tier:
            filtered = [r for r in filtered if r.get("collection_tier") == tier]
        if date:
            filtered = [r for r in filtered if r["date_only"] == date]

        mix_counts: dict[str, int] = {}
        for r in filtered:
            label = _kind_label(r["venue_kind"]) if r["venue_kind"] else "Not on the gold-list registry"
            mix_counts[label] = mix_counts.get(label, 0) + 1
        max_count = max(mix_counts.values(), default=0) or 1
        mix = [
            {"label": label, "count": c, "pct": round(100 * c / max_count)}
            for label, c in sorted(mix_counts.items(), key=lambda kv: -kv[1])
        ]

        return render(
            request, "snapshot.html", run=run, topic=topic, rows=filtered,
            total_rows=len(enriched), coverage=coverage, mix=mix,
            filters={"venue": venue, "kind": kind, "tier": tier, "date": date},
            options={"venues": venues, "kinds": kinds, "tiers": tiers, "dates": dates},
            any_filter_active=bool(venue or kind or tier or date),
        )

    @app.post("/runs/{run_id}/insight")
    def insight_create(request: Request, run_id: str) -> Any:
        try:
            mine_run = run_store.get(run_id)
        except NoSuchRun:
            return error_page(request, 404, "Run not found", f"No run with id {run_id!r}.")
        try:
            topic = topic_store.get(mine_run.topic_id)
        except NoSuchTopic:
            return error_page(request, 404, "Topic not found", "The parent topic no longer exists.")
        settings = get_settings()
        try:
            client = get_client(settings)
            insight_run = run_insight(topic, run_id, run_store, client=client)
        except FileNotFoundError:
            return error_page(
                request, 400, "No snapshot to analyse",
                f"Run {run_id!r} has no signals.json on disk — mine a snapshot first.",
            )
        except VsmError as exc:
            return error_page(request, 400, "Insight could not run", str(exc))
        return RedirectResponse(url=f"/runs/{insight_run.run_id}/insight", status_code=303)

    @app.get("/runs/{run_id}/insight", response_class=HTMLResponse)
    def insight_view(request: Request, run_id: str) -> HTMLResponse:
        try:
            run = run_store.get(run_id)
        except NoSuchRun:
            return error_page(request, 404, "Run not found", f"No run with id {run_id!r}.")
        if run.mode != "insight":
            return error_page(
                request, 400, "Not an insight run",
                f"Run {run_id!r} is a {run.mode!r} run, not an insight run.",
            )
        try:
            topic = topic_store.get(run.topic_id)
        except NoSuchTopic:
            topic = None

        def _read(name: str, default: Any) -> Any:
            try:
                return run_store.read_artifact(run.run_id, name)
            except FileNotFoundError:
                return default

        themes = _read("themes.json", [])
        findings = _read("findings.json", [])
        stances = _read("stance.json", [])
        duallens = _read("duallens.json", [])
        momentum_rows = _read("momentum.json", [])
        anomaly_rows = _read("anomaly.json", [])
        entities = _read("entities.json", {"entities": [], "by_signal": {}, "unmapped_mentions": []})

        # `corroborate()` builds exactly one Finding per Theme, same order —
        # see vsm/modes/insight.py. Zipping is the same pairing run_report
        # relies on, done here for display rather than re-derived by name.
        paired = list(zip(themes, findings))
        finding_by_theme_id = {t["theme_id"]: f for t, f in paired}
        volume_by_theme_id = {t["theme_id"]: t["volume"] for t in themes}

        forest_rows = []
        for gap in duallens:
            finding = finding_by_theme_id.get(gap["theme_id"])
            forest_rows.append({
                "name": gap["theme_name"],
                "volume": volume_by_theme_id.get(gap["theme_id"], 0),
                "hcp_net": gap["hcp_net"], "patient_net": gap["patient_net"],
                "divergence": gap["divergence"], "reason": gap.get("reason") or "",
                "independent_sources": finding["independent_sources"] if finding else None,
                "tier": finding["tier"] if finding else "",
            })
        forest_rows.sort(key=lambda r: -r["volume"])
        forest_svg = forest_plot_svg(forest_rows)

        mine_run_id = run.parent_run_id
        has_baseline = False
        snapshot_rail: list[dict[str, Any]] = []
        if topic is not None:
            snapshots = run_store.snapshots(topic.topic_id)
            snapshot_rail = [
                {"run_id": r.run_id, "started_at": r.started_at, "is_current": r.run_id == mine_run_id}
                for r in snapshots
            ]
            series = [r.run_id for r in snapshots]
            if mine_run_id in series:
                has_baseline = series.index(mine_run_id) > 0

        theme_rows = []
        for t, f in paired:
            theme_rows.append({
                "theme": t, "tier": f["tier"], "sources": f["independent_sources"],
                "venue_mix": sorted(t.get("venue_mix", {}).items()),
                "kind_mix": sorted(t.get("kind_mix", {}).items()),
            })

        stance_by_theme_id = {s["theme_id"]: s for s in stances}
        stance_rows = []
        for t in themes:
            s = stance_by_theme_id.get(t["theme_id"])
            by_class = s["by_class"] if s else {}
            stance_rows.append({
                "name": t["name"],
                "basis": s["basis"] if s else "venue",
                "by_class": sorted(by_class.items()),
            })

        from collections import Counter
        entity_counts = Counter(
            eid for eids in entities.get("by_signal", {}).values() for eid in eids
        )
        entity_rows = [
            {**e, "signal_count": entity_counts.get(e["entity_id"], 0)}
            for e in entities.get("entities", [])
        ]

        return render(
            request, "insight.html", run=run, topic=topic, mine_run_id=mine_run_id,
            snapshot_rail=snapshot_rail,
            forest_svg=forest_svg, forest_rows=forest_rows,
            momentum_rows=momentum_rows, has_baseline=has_baseline,
            anomaly_rows=anomaly_rows, theme_rows=theme_rows,
            stance_rows=stance_rows, entity_rows=entity_rows,
            unmapped_count=len(entities.get("unmapped_mentions", [])),
        )

    @app.post("/runs/{run_id}/report")
    def report_create(request: Request, run_id: str) -> Any:
        try:
            insight_run = run_store.get(run_id)
        except NoSuchRun:
            return error_page(request, 404, "Run not found", f"No run with id {run_id!r}.")
        try:
            topic = topic_store.get(insight_run.topic_id)
        except NoSuchTopic:
            return error_page(request, 404, "Topic not found", "The parent topic no longer exists.")
        settings = get_settings()
        try:
            client = get_client(settings)
            rep = run_report(topic, run_id, run_store, client=client)
        except VsmError as exc:
            return error_page(
                request, 422, "A guard blocked the report",
                f"{exc} — nothing was written; a blocked report leaves no partial artifacts.",
            )
        return RedirectResponse(url=f"/runs/{rep.run_id}/report", status_code=303)

    @app.get("/runs/{run_id}/report", response_class=HTMLResponse)
    def report_view(request: Request, run_id: str) -> HTMLResponse:
        try:
            run = run_store.get(run_id)
        except NoSuchRun:
            return error_page(request, 404, "Run not found", f"No run with id {run_id!r}.")
        if run.mode != "report":
            return error_page(
                request, 400, "Not a report run",
                f"Run {run_id!r} is a {run.mode!r} run, not a report run.",
            )
        try:
            topic = topic_store.get(run.topic_id)
        except NoSuchTopic:
            topic = None

        insight_run_id = run.parent_run_id
        mine_run_id = None
        if insight_run_id:
            try:
                mine_run_id = run_store.get(insight_run_id).parent_run_id
            except NoSuchRun:
                mine_run_id = None

        def _read_md(name: str) -> str | None:
            try:
                return run_store.read_artifact(run.run_id, name)
            except FileNotFoundError:
                return None

        pulse_text = _read_md("pulse_report.md")
        appendix_text = _read_md("provenance_appendix.md")
        methodology_text = _read_md("methodology.md")
        considering_text = _read_md("worth_considering.md")

        appendix_rows = _parse_pipe_table_rows(appendix_text)
        # Header: signal_id | venue | venue kind | captured_at | collection method | URL
        citations = [
            {"signal_id": r[0], "venue": r[1], "venue_kind": r[2],
             "captured_at": r[3], "method": r[4], "url": r[5]}
            for r in appendix_rows if len(r) >= 6
        ]
        cited_ids = {c["signal_id"] for c in citations}

        raw_themes = run_store.read_artifact(insight_run_id, "themes.json") if insight_run_id else []
        raw_findings = run_store.read_artifact(insight_run_id, "findings.json") if insight_run_id else []
        theme_vms = []
        for t, f in zip(raw_themes, raw_findings):
            sids = [sid for sid in f.get("signal_ids", []) if sid in cited_ids]
            theme_vms.append({
                "name": t["name"], "volume": t["volume"],
                "tier": f["tier"], "sources": f["independent_sources"],
                "signal_ids": sids,
            })

        return render(
            request, "report.html", run=run, topic=topic,
            insight_run_id=insight_run_id, mine_run_id=mine_run_id,
            theme_vms=theme_vms, citations=citations,
            pulse_html=_markdown_lite_to_html(pulse_text) if pulse_text else None,
            methodology_html=_markdown_lite_to_html(methodology_text) if methodology_text else None,
            considering_html=_markdown_lite_to_html(considering_text) if considering_text else None,
            has_pulse=pulse_text is not None,
        )

    @app.get("/runs/{run_id}/artifact/{name:path}")
    def artifact_download(request: Request, run_id: str, name: str) -> Any:
        try:
            run = run_store.get(run_id)
        except NoSuchRun:
            return error_page(request, 404, "Run not found", f"No run with id {run_id!r}.")
        base = run_store.artifacts_dir(run.run_id).resolve()
        candidate = (base / name).resolve()
        if base != candidate.parent or not candidate.is_file():
            return error_page(
                request, 404, "Artifact not found",
                f"No artifact named {name!r} on run {run_id!r}.",
            )
        media = (
            "application/json" if candidate.suffix == ".json"
            else "text/markdown; charset=utf-8" if candidate.suffix == ".md"
            else "text/plain; charset=utf-8"
        )
        return FileResponse(candidate, media_type=media, filename=candidate.name)

    return app
