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

import json
import logging
import re
from html import escape as _esc
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import PlainTextResponse, Response
from starlette.templating import Jinja2Templates
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

from vsm.config import get_settings
from vsm.errors import GuardViolation, NoSuchRun, NoSuchTopic, VsmError
from vsm.guards.cost import estimate_run_usd
from vsm.llm.client import get_client
from vsm.mining import get_miner
from vsm.mining.signals import any_synthetic
from vsm.mining.venues import kind_of
from vsm.modes.insight import run_insight
from vsm.modes.mine import run_mine
from vsm.modes.report import run_report
from vsm.platform import assert_serveable, storage_is_durable
from vsm.topics.model import BANDS
from vsm.ui.content import (
    DELETE_WARNING,
    DELIVERABLE_GROUPS,
    DELIVERABLE_TIERS,
    DELIVERABLES,
    EPHEMERAL_STORAGE_NOTICE,
    FIELD_GUIDE,
    FILTER_HELP,
    FILTER_LEDE,
    FILTERS,
    FIRST_RUN_STEPS,
    GLOSSARY,
    MODES,
    PLOT_GUIDE,
    READ_ONLY_CONTROL_NOTE,
    SORTS,
    TAGLINE,
    TIERS,
    WHAT_IT_IS,
    explainer,
)
from vsm.ui.render import (
    fmt_date_long,
    fmt_dt,
    forest_plot_svg,
    markdown_excerpt_html,
    markdown_inline_html,
    markdown_paragraphs,
    markdown_sections,
    markdown_to_html,
    net_stance_text,
    pct,
    sparkline_svg,
    usd,
)

__all__ = ["create_app"]


class ProductionRefusalMiddleware:
    """Spec D15, wired as raw ASGI rather than a per-route dependency.

    A dependency has to be attached to every route by hand, which means the
    very next route someone adds is exempt until they remember it. ASGI
    middleware sits above the router entirely — it runs before FastAPI's
    routing even looks at the path, so it covers every route this app has
    today (including the mounted ``/static`` files) and every route it gains
    later, with no per-route action required to keep it that way.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            assert_serveable()
        except GuardViolation as exc:
            response = PlainTextResponse(str(exc), status_code=503)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


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

_PIPE_TABLE_ROW = re.compile(r"^\s*\|")


# content.TIERS keys use a space ("single source"); run data uses an
# underscore ("single_source"). Normalised once so a tier shown anywhere in
# the templates can carry its own definition, and so the tier badge and the
# glossary can never drift into two different definitions of the same word.
_TIER_NOTES = {key.replace(" ", "_"): note for key, note in TIERS}


def _tier_label(tier: str | None) -> str:
    return _TIER_LABELS.get(tier or "", tier or "not scored")


def _tier_note(tier: str | None) -> str:
    return _TIER_NOTES.get(tier or "", "")


def _kind_label(kind: str | None) -> str:
    return _KIND_LABELS.get(kind or "", "Not on the gold-list registry")


def _class_label(value: str | None) -> str:
    return _AUTHOR_CLASS_LABELS.get(value or "", value or "unknown")


def _stance_label(value: str | None) -> str:
    return _STANCE_LABELS.get(value or "", value or "unclear")


def _anomaly_label(kind: str | None) -> str:
    return _ANOMALY_KIND_LABELS.get(kind or "", kind or "change")


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
    # `(?<!\\)\|` and not a bare `split("|")`: a venue or URL carrying an
    # escaped pipe would otherwise hand this table one cell too many and
    # shift every column after it.
    rows = [
        [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", ln.strip().strip("|"))]
        for ln in lines
    ]
    return rows[2:]


def _split_lines(text: str) -> tuple[str, ...]:
    return tuple(ln.strip() for ln in text.splitlines() if ln.strip())


def _band_cards() -> list[dict[str, Any]]:
    cards = []
    for name in ("probe", "standard", "deep"):
        band = BANDS[name]
        cards.append({"band": band, "estimate": estimate_run_usd(band, cluster_count=1)})
    return cards


# --------------------------------------------------------------------- #
# The deliverables surface — the moat, rendered.                        #
# --------------------------------------------------------------------- #
#
# One shared shape feeds three places: the standalone /deliverables
# catalog, the pre-run empty state (a topic never run, and confirm-spend),
# and the real, produced-artifact cards on the run/insight/report screens.
# Only `available`/`href`/`preview` change between them — same ten items,
# same groups, same card. That sameness is the point: a user should
# recognise the thing they previewed before spending money as the exact
# thing that lands after.


_FORMAT_LABELS = {".md": "Markdown", ".json": "JSON", ".csv": "CSV"}


def _format_label(filename: str) -> str:
    return _FORMAT_LABELS.get(Path(filename).suffix, "Text")


def _size_label(n: int | None) -> str | None:
    """A file's weight, or `None` when there is no file to weigh.

    `None` rather than `0 B`, for this codebase's one non-negotiable reason:
    a zero-byte artifact and an artifact that was never written are different
    facts, and `0 B` is what makes them look the same.
    """
    if n is None:
        return None
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _empty_deliverable_cards() -> list[dict[str, Any]]:
    """Every deliverable, nothing filled in — the pre-run state.

    The sample line is rendered through the one converter, exactly as the
    real artifact will be, so what a reader sees before spending money is
    the *shape* of the output and never its source syntax.
    """
    return [
        {
            **d,
            "available": False,
            "href": None,
            "excerpt": markdown_to_html(d["sample"]) if d["sample"] else "",
            "excerpt_is_real": False,
            "format_label": _format_label(d["file"]),
            "size_label": None,
        }
        for d in DELIVERABLES
    ]


def _deliverable_cards(
    run_store: Any, *, mine_run: Any = None, insight_run: Any = None, report_run: Any = None
) -> list[dict[str, Any]]:
    """Every deliverable, real where a producing run exists and has written it."""
    run_by_group = {"data": mine_run, "analysis": insight_run, "report": report_run}
    # Warm every artifact this is about to look for, in one concurrent batch.
    # The loop below reads up to ten names per run and several are legitimately
    # absent, so sequentially it was ten round trips to render one card set —
    # on every run, snapshot, insight and report page.
    warm = getattr(run_store, "prefetch_artifacts", None)
    if warm is not None:
        warm([
            (run.run_id, d["file"])
            for d in DELIVERABLES
            if (run := run_by_group.get(d["group"])) is not None
        ])
    cards: list[dict[str, Any]] = []
    for d in DELIVERABLES:
        run = run_by_group.get(d["group"])
        available, href, size = False, None, None
        excerpt = markdown_to_html(d["sample"]) if d["sample"] else ""
        excerpt_is_real = False
        if run is not None:
            try:
                content = run_store.read_artifact(run.run_id, d["file"])
            except FileNotFoundError:
                content = None
            if content is not None:
                available = True
                href = f"/runs/{run.run_id}/artifact/{d['file']}"
                # Derived from `content`, never from a filesystem path — see
                # `_artifact_bytes`. A path here is a key on two of the three
                # backends, and `.stat()` on it is an `AttributeError`.
                size = len(_artifact_bytes(content, d["file"]))
                if d["file"].endswith(".md") and isinstance(content, str):
                    real = markdown_excerpt_html(content)
                    if real:
                        excerpt, excerpt_is_real = real, True
        cards.append({
            **d,
            "available": available,
            "href": href,
            "excerpt": excerpt,
            "excerpt_is_real": excerpt_is_real,
            "format_label": _format_label(d["file"]),
            "size_label": _size_label(size),
        })
    return cards


def _deliverable_groups_ctx(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # `cards`, never `items`: a plain dict's real `.items()` method wins over
    # a same-named key under Jinja's attribute lookup (`g.items` resolves to
    # the builtin before it falls back to `g["items"]`), so a key called
    # "items" silently returns a bound method instead of the list.
    return [
        {"key": key, "label": label, "description": desc,
         "cards": [c for c in cards if c["group"] == key]}
        for key, label, desc in DELIVERABLE_GROUPS
    ]


def _deliverable_tiers_ctx(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The same ten deliverables, in two tiers of unequal weight.

    The four client-ready artifacts are the offer; the six behind them are
    the evidence for it. Rendering all ten as one grid of identical cards
    said they were worth the same, which is the specific error this splits
    apart — the primary tier gets presence and a rendered excerpt, the
    secondary tier is a list.
    """
    groups = {g["key"]: g for g in _deliverable_groups_ctx(cards)}
    tiers = []
    for tier in DELIVERABLE_TIERS:
        member_groups = [groups[k] for k in tier["groups"] if k in groups]
        tiers.append({
            **tier,
            "member_groups": member_groups,
            "cards": [c for g in member_groups for c in g["cards"]],
        })
    return tiers


def _forest_rows(
    themes: Any, findings: Any, duallens: Any
) -> list[dict[str, Any]]:
    """One row per dual-lens gap, ordered by weight — the forest plot's input.

    Shared by the insight screen's plot and the report's Figure 1 so the
    figure a client sees and the figure an analyst reads are the same rows,
    sorted the same way, built once. `reason` is carried through rather than
    dropped: a row whose divergence is `None` has to be able to say why on
    the page, not only in an `aria-label` nobody can reach.
    """
    paired = list(zip(themes, findings))
    finding_by_theme_id = {t["theme_id"]: f for t, f in paired}
    volume_by_theme_id = {t["theme_id"]: t["volume"] for t in themes}
    rows = []
    for gap in duallens:
        finding = finding_by_theme_id.get(gap["theme_id"])
        rows.append({
            "name": gap["theme_name"],
            "volume": volume_by_theme_id.get(gap["theme_id"], 0),
            "hcp_net": gap["hcp_net"], "patient_net": gap["patient_net"],
            "divergence": gap["divergence"], "reason": gap.get("reason") or "",
            "independent_sources": finding["independent_sources"] if finding else None,
            "tier": finding["tier"] if finding else "",
        })
    rows.sort(key=lambda r: -r["volume"])
    return rows


def _flow_chain(run_store: Any, topic_id: str, run: Any) -> dict[str, str | None]:
    """The mine/insight/report run ids of one flow, found from any run in it.

    The store has no "children of this run" index — a run only records its
    own parent — so the forward direction (mine -> insight -> report) is
    found by scanning this topic's runs of the next mode for one whose
    parent is the id we already have, taking the most recent if more than
    one insight or report was ever generated from the same snapshot.
    """

    def child(mode: str, parent_id: str | None) -> Any | None:
        if not parent_id:
            return None
        matches = [r for r in run_store.for_topic(topic_id, mode) if r.parent_run_id == parent_id]
        return matches[-1] if matches else None

    mine_run_id = insight_run_id = report_run_id = None
    if run.mode == "mine":
        mine_run_id = run.run_id
        ins = child("insight", mine_run_id)
        insight_run_id = ins.run_id if ins else None
        rep = child("report", insight_run_id) if insight_run_id else None
        report_run_id = rep.run_id if rep else None
    elif run.mode == "insight":
        insight_run_id = run.run_id
        mine_run_id = run.parent_run_id
        rep = child("report", insight_run_id)
        report_run_id = rep.run_id if rep else None
    else:  # report
        report_run_id = run.run_id
        insight_run_id = run.parent_run_id
        if insight_run_id:
            try:
                mine_run_id = run_store.get(insight_run_id).parent_run_id
            except NoSuchRun:
                mine_run_id = None
    return {"mine_run_id": mine_run_id, "insight_run_id": insight_run_id, "report_run_id": report_run_id}


def _flow_runs(run_store: Any, run: Any) -> dict[str, Any]:
    """`_flow_chain`'s ids, resolved to the `Run`s themselves (or `None`).

    Fetches whichever of mine/insight/report this ``run`` is not — the run
    passed in is reused rather than re-fetched, so a run mid-flight (no
    finished_at yet) is never masked by a stale re-read.
    """
    flow = _flow_chain(run_store, run.topic_id, run)

    def get(run_id: str | None) -> Any | None:
        if not run_id:
            return None
        try:
            return run_store.get(run_id)
        except NoSuchRun:
            return None

    return {
        "flow": flow,
        "mine_run": run if run.mode == "mine" else get(flow["mine_run_id"]),
        "insight_run": run if run.mode == "insight" else get(flow["insight_run_id"]),
        "report_run": run if run.mode == "report" else get(flow["report_run_id"]),
    }


def _mine_run_is_synthetic(run_store: Any, mine_run_id: str | None) -> bool:
    """Did the snapshot at ``mine_run_id`` come from the offline demonstration
    miner? The banner and every screen it appears on read this, not a run
    field — the marker lives in the data (``signals.json``, and every
    artifact derived from it), never in run metadata alone, so a downloaded
    artifact carries the same fact this page shows."""
    if not mine_run_id:
        return False
    try:
        rows = run_store.read_artifact(mine_run_id, "signals.json")
    except FileNotFoundError:
        return False
    return any_synthetic(rows)


def _artifact_bytes(content: Any, name: str) -> bytes:
    """The exact bytes a backend holds for this artifact, from content already
    read — no second fetch, and **no filesystem**.

    This exists because the deliverable cards and the download route used to
    reach for ``artifacts_dir(run_id) / name`` and treat it as a real
    ``pathlib.Path``. On the local backend it is one. On Vercel Blob it is a
    ``PurePosixPath`` subclass standing in for a key, with no ``.stat()`` and
    no file behind it — so ``.stat().st_size`` raised ``AttributeError`` (not
    the ``OSError`` that was being caught) and took down every route that
    renders a deliverable card, while ``FileResponse`` broke every download.
    Production served reads of pre-seeded data fine and 500ed the moment a run
    was created through it, which is exactly the "it doesn't work" this app was
    reported with.

    Reconstruction is byte-exact rather than approximate: every backend writes
    a mapping as ``json.dumps(payload, indent=2, sort_keys=True)`` encoded
    UTF-8, and a string verbatim. If that ever stops being true, the size on a
    card drifts and a download stops matching the stored blob — so the writers
    and this reader are pinned together by
    ``tests/test_ui_artifact_bytes.py``.
    """
    if isinstance(content, str):
        return content.encode("utf-8")
    return json.dumps(content, indent=2, sort_keys=True).encode("utf-8")


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
    env.filters["date_long"] = fmt_date_long
    env.globals["tier_label"] = _tier_label
    env.globals["tier_note"] = _tier_note
    env.globals["kind_label"] = _kind_label
    env.globals["class_label"] = _class_label
    env.globals["stance_label"] = _stance_label
    env.globals["anomaly_label"] = _anomaly_label
    env.globals["explainer"] = explainer
    # The product in one line, for the document head on every page — and the
    # link-preview card, which is part of the deliverable when a report gets
    # pasted into chat.
    env.globals["tagline"] = TAGLINE
    env.globals["ephemeral_storage_notice"] = EPHEMERAL_STORAGE_NOTICE
    env.globals["read_only_control_note"] = READ_ONLY_CONTROL_NOTE
    # A callable, not a value computed once here: every template that wants
    # to know whether to render a mutating control calls this itself
    # (`{% if not storage_is_durable() %}`), so it is read fresh on every
    # request — the same freshness `resolve_db_url` and `open_stores`
    # already guarantee — rather than baked in at app-startup time.
    env.globals["storage_is_durable"] = storage_is_durable

    templates = Jinja2Templates(env=env)

    app = FastAPI(title="Vi Signal Mine")
    # Spec D15. Added before anything is mounted or routed so it wraps the
    # whole app — static files included, with no route exempt.
    app.add_middleware(ProductionRefusalMiddleware)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    def render(request: Request, name: str, status_code: int = 200, **ctx: Any) -> HTMLResponse:
        return templates.TemplateResponse(request, name, ctx, status_code=status_code)

    def error_page(request: Request, status_code: int, title: str, message: str) -> HTMLResponse:
        return render(request, "error.html", status_code=status_code, title=title, message=message)

    @app.exception_handler(StarletteHTTPException)
    async def _styled_http_error(request: Request, exc: StarletteHTTPException) -> Any:
        """Every unrouted path and unhandled HTTP status, in the app's own skin.

        A mistyped or stale URL used to return FastAPI's default
        ``{"detail":"Not Found"}`` — raw JSON, no navigation, no way back. Every
        404 the routes raise *themselves* was already a designed page, so the
        one 404 a visitor is most likely to reach was the only one that looked
        broken. A link shared into a chat and gone stale lands exactly here.

        Static assets keep the plain response: a stylesheet request that 404s
        should not be answered with a page of HTML, and nothing renders that
        would show it.
        """
        if request.url.path.startswith("/static/"):
            return PlainTextResponse(str(exc.detail), status_code=exc.status_code)
        titles = {
            404: ("Page not found", "There is nothing at this address. It may have "
                  "been a mistyped link, or a topic or run that has since been deleted."),
            405: ("That is not how this page is reached",
                  "The address exists but does not accept this kind of request."),
        }
        title, message = titles.get(
            exc.status_code,
            (f"Something went wrong ({exc.status_code})", str(exc.detail)),
        )
        return error_page(request, exc.status_code, title, message)

    def read_only_refusal(request: Request) -> HTMLResponse | None:
        """``None`` when this instance can honour a write; otherwise the one
        409 page every mutating route below returns. Centralised so a new
        mutating route added later starts from a call to this rather than a
        copy-pasted check that is easy to forget (spec: parametrise the
        routes in tests for exactly that reason).

        409, not 400 or 500: the request itself is well-formed and would
        succeed on a durable deployment — it is this *instance* that cannot
        honour it, which is what 409 Conflict means or nothing does.
        """
        if storage_is_durable():
            return None
        return error_page(
            request, 409, "This instance is read-only", EPHEMERAL_STORAGE_NOTICE,
        )

    # ------------------------------------------------------------------ how --

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Any:
        """Browsers request this from the site root regardless of what the page
        links, so without it every page load logged a 404. Serves the same SVG
        the `<link>` points at — modern browsers accept it under this name, and
        one asset cannot drift from another."""
        return FileResponse(
            _STATIC_DIR / "icon.svg", media_type="image/svg+xml",
            headers={"cache-control": "public, max-age=86400"},
        )

    @app.get("/how", response_class=HTMLResponse)
    def how_it_works(request: Request) -> HTMLResponse:
        return render(
            request, "how.html",
            what_it_is=WHAT_IT_IS, modes=MODES, tiers=TIERS, glossary=GLOSSARY,
            active_nav="how",
        )

    # ------------------------------------------------------------- deliverables --

    @app.get("/deliverables", response_class=HTMLResponse)
    def deliverables_catalog(request: Request) -> HTMLResponse:
        """"What you get" — the moat, on its own screen.

        Every deliverable content.py knows about, grouped by who it is for,
        with nothing filled in — this is not tied to any run, so there is
        nothing to fill in. This is the page someone reads to decide whether
        the tool is worth running at all.
        """
        tiers = _deliverable_tiers_ctx(_empty_deliverable_cards())
        # Cross-link, not a dead end: if this instance has ever produced a
        # report, the catalog page points at it. A page that describes a
        # document and cannot show you one is the shape of brochure this
        # whole pass exists to stop being.
        # Newest topic first, and stop at the first one that has a report.
        # This used to scan *every* topic and keep the last match, so the page
        # paid a full run-store fan-out per topic and then threw all but one
        # away — 10.3 seconds for a page with no run data on it. `list()` is
        # already newest-first, so the first hit is also the best example.
        example = None
        for topic in topic_store.list():
            reports = [
                r for r in run_store.for_topic(topic.topic_id, "report")
                if r.status == "complete"
            ]
            if reports:
                example = {"run_id": reports[-1].run_id, "topic_name": topic.name}
                break
        return render(
            request, "deliverables.html", tiers=tiers, example=example,
            active_nav="deliverables",
        )

    # --------------------------------------------------------------- topics --

    def _topic_row(topic: Any, all_runs: list[Any] | None = None) -> dict[str, Any]:
        # One pass, not two. `snapshots()` is a filter over `for_topic()`, so
        # calling both asked a store with no secondary index to list and read
        # every run blob twice per row — and this runs once per topic on the
        # index. Deriving the snapshots here keeps the filter identical (the
        # backend's own `snapshots()` is `mode == "mine" and status ==
        # "complete"`, in `for_topic` order) while halving the traffic.
        # `all_runs` is passed in by the index, which has already had to settle
        # which snapshots exist in order to prefetch their artifacts. Fetching
        # again here would be a second call per topic for a value the caller is
        # holding.
        if all_runs is None:
            all_runs = run_store.for_topic(topic.topic_id)
        snapshots = [r for r in all_runs if r.mode == "mine" and r.status == "complete"]
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

    @app.middleware("http")
    async def _fresh_reads_each_request(request: Request, call_next):
        """Drop each store's request-scoped identity map before handling.

        That map makes the fan-out reads on a page render affordable (see
        `vsm/backends/vercel_blob.py`'s `get_content`), and it is correct only
        within one request. A serverless container is reused, so without this a
        later request could be served bytes it never read. `getattr` because
        only the blob-backed stores have one — the filesystem and Postgres
        backends do not fan out this way and need no map.
        """
        for store in (topic_store, run_store):
            begin = getattr(store, "begin_request", None)
            if begin is not None:
                begin()
        return await call_next(request)

    def _prefetch(pairs: list[tuple[str, str]]) -> None:
        """Ask the store to warm several artifacts at once, if it can.

        `getattr` because this is an optimisation only the blob backend needs
        and only it implements — the filesystem store reads a local file and
        has nothing to overlap. Every read still works identically without it.
        """
        warm = getattr(run_store, "prefetch_artifacts", None)
        if warm is not None and pairs:
            warm(pairs)

    def _matches(topic: Any, needle: str) -> bool:
        """Substring match across the fields someone would actually type.

        Deliberately not the whole record: matching `never_say` or `questions`
        would make a search for a competitor's name return the topics that
        forbid mentioning it, which is the opposite of what was asked.
        """
        haystack = " ".join(filter(None, (
            topic.name, topic.therapeutic_area, topic.brand, topic.molecule,
            " ".join(topic.competitors),
        ))).lower()
        return all(word in haystack for word in needle.lower().split())

    _SORT_KEYS = {
        # `list()` is already newest-first, so "recent" is the identity sort and
        # must stay stable rather than re-deriving an order from timestamps.
        "recent": None,
        "oldest": None,
        "name": lambda r: r["topic"].name.lower(),
        "activity": lambda r: (-r["snapshot_count"], r["topic"].name.lower()),
        "spend": lambda r: (-r["spend_to_date"], r["topic"].name.lower()),
        "volume": lambda r: (-(r["latest_volume"] or 0), r["topic"].name.lower()),
    }

    def _filtered(rows: list[dict[str, Any]], which: str) -> list[dict[str, Any]]:
        if which == "watched":
            return [r for r in rows if r["snapshot_count"] >= 1]
        if which == "trend":
            return [r for r in rows if r["snapshot_count"] >= 2]
        if which == "empty":
            return [r for r in rows if r["snapshot_count"] == 0]
        return rows

    #: How many rows the index renders before it stops and says so. Measured at
    #: ~677 bytes of HTML per row, so this bounds the document at roughly 40KB
    #: however long the list gets. Not pagination: there is no page state to
    #: carry through sort, filter and search, and an internal tool with a search
    #: box does not need one. A cap that announces itself and offers the whole
    #: list is honest; silently rendering the first fifty would not be.
    _ROW_CAP = 50

    @app.get("/", response_class=HTMLResponse)
    def topics_index(
        request: Request, q: str = "", sort: str = "recent", show: str = "all",
        # `show_all`, not `all`: a parameter named `all` shadows the builtin for
        # the whole function body, and this one already calls `all()` indirectly
        # through the helpers above. The URL keeps the short spelling.
        show_all: str = Query("", alias="all"),
    ) -> HTMLResponse:
        # Unknown values fall back rather than 400: this is a shareable URL and
        # a stale bookmark should show the list, not an error page.
        if sort not in _SORT_KEYS:
            sort = "recent"
        if show not in dict(FILTERS):
            show = "all"
        q = q.strip()
        topics = topic_store.list()
        # Two passes on purpose. The first settles which snapshots exist —
        # cheap, because every `for_topic` after the first is served from the
        # request map — then every `signals.json` the sparklines need is
        # fetched in one concurrent batch. Interleaved, those reads were one
        # sequential round trip per snapshot, and with sixty topics that alone
        # was several seconds of a page that shows no run detail at all.
        total = len(topics)
        # Search is applied *before* any run lookup: a name match needs nothing
        # from the run store, and on a store with no secondary index every
        # topic excluded here is a fan-out avoided. With a narrow search this
        # turns the most expensive page in the app into one of the cheapest.
        if q:
            topics = [t for t in topics if _matches(t, q)]
        # One call for every topic, not one per topic. Asking per topic made
        # this page's cost grow with the length of the list — a query or a
        # fan-out each, so forty topics were forty round trips for one render.
        runs_by_topic = run_store.for_topics([t.topic_id for t in topics])
        _prefetch([
            (r.run_id, "signals.json")
            for runs in runs_by_topic.values()
            for r in runs
            if r.mode == "mine" and r.status == "complete"
        ])
        rows = [_topic_row(t, runs_by_topic[t.topic_id]) for t in topics]
        rows = _filtered(rows, show)
        if sort == "oldest":
            rows.reverse()
        elif _SORT_KEYS[sort] is not None:
            rows.sort(key=_SORT_KEYS[sort])
        matched = len(rows)
        uncapped = show_all.strip() == "1"
        capped = not uncapped and matched > _ROW_CAP
        if capped:
            rows = rows[:_ROW_CAP]
        return render(
            request, "topics.html", rows=rows, first_run_steps=FIRST_RUN_STEPS,
            active_nav="topics", sorts=SORTS, filters=FILTERS,
            filter_help=FILTER_HELP, filter_lede=FILTER_LEDE,
            q=q, sort=sort, show=show, total=total, shown=len(rows),
            matched=matched, capped=capped, row_cap=_ROW_CAP, uncapped=uncapped,
        )

    _BLANK_TOPIC_VALUES = {
        "name": "", "therapeutic_area": "", "spend_band": "probe", "brand": "",
        "molecule": "", "competitors": "", "questions": "", "never_say": "",
    }

    @app.get("/topics/new", response_class=HTMLResponse)
    def topic_new(request: Request) -> HTMLResponse:
        return render(
            request, "topic_form.html", mode="create", topic=None,
            band_cards=_band_cards(), errors={}, values=dict(_BLANK_TOPIC_VALUES),
            field_guide=FIELD_GUIDE,
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
            field_guide=FIELD_GUIDE,
        )

    @app.get("/topics/{topic_id}", response_class=HTMLResponse)
    def topic_detail(request: Request, topic_id: str) -> HTMLResponse:
        """A topic on its own: its run history, and — crucially — what it
        will produce. On a topic that has never been run this is exactly
        the pre-run empty state the owner asked for: the deliverables list,
        nothing filled in, reachable one click from the topic itself."""
        try:
            topic = topic_store.get(topic_id)
        except NoSuchTopic:
            return error_page(request, 404, "Topic not found", f"No topic with id {topic_id!r}.")

        all_runs = list(reversed(run_store.for_topic(topic_id)))
        snapshots = run_store.snapshots(topic_id)
        latest_mine = snapshots[-1] if snapshots else None

        latest_insight = None
        if latest_mine is not None:
            candidates = [
                r for r in run_store.for_topic(topic_id, "insight")
                if r.parent_run_id == latest_mine.run_id and r.status == "complete"
            ]
            latest_insight = candidates[-1] if candidates else None

        latest_report = None
        if latest_insight is not None:
            candidates = [
                r for r in run_store.for_topic(topic_id, "report")
                if r.parent_run_id == latest_insight.run_id and r.status == "complete"
            ]
            latest_report = candidates[-1] if candidates else None

        if all_runs:
            cards = _deliverable_cards(
                run_store, mine_run=latest_mine, insight_run=latest_insight, report_run=latest_report,
            )
        else:
            cards = _empty_deliverable_cards()

        return render(
            request, "topic_detail.html", topic=topic, history=all_runs,
            has_run=bool(all_runs), tiers=_deliverable_tiers_ctx(cards),
            latest_mine=latest_mine, latest_insight=latest_insight, latest_report=latest_report,
        )

    def _validate_topic_form(name: str, spend_band: str) -> dict[str, str]:
        """Only the topic's name is required (see content.FIELD_GUIDE) —
        every other field narrows or widens what the sweep finds, and a
        user must be free to skip it rather than guess at a value. A blank
        spend band cannot come from the form itself (each band card always
        submits a value); it is checked here anyway for a direct POST."""
        errors: dict[str, str] = {}
        if not name.strip():
            errors["name"] = FIELD_GUIDE["name"]["help"]
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
        refusal = read_only_refusal(request)
        if refusal is not None:
            return refusal
        # Only `name` is required (content.FIELD_GUIDE) — a blank spend band
        # defaults to `probe`, the cheapest, rather than being rejected: a
        # user who skipped every optional field still gets a topic they can
        # run, not a form bounced back at them for a choice they didn't make.
        chosen_band = spend_band or "probe"
        errors = _validate_topic_form(name, chosen_band)
        values = {
            "name": name, "therapeutic_area": therapeutic_area, "spend_band": chosen_band,
            "brand": brand, "molecule": molecule, "competitors": competitors,
            "questions": questions, "never_say": never_say,
        }
        if errors:
            return render(
                request, "topic_form.html", status_code=422, mode="create", topic=None,
                band_cards=_band_cards(), errors=errors, values=values,
                field_guide=FIELD_GUIDE,
            )
        topic_store.create(
            name=name.strip(), therapeutic_area=therapeutic_area.strip(), spend_band=chosen_band,
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
        refusal = read_only_refusal(request)
        if refusal is not None:
            return refusal
        try:
            topic = topic_store.get(topic_id)
        except NoSuchTopic:
            return error_page(request, 404, "Topic not found", f"No topic with id {topic_id!r}.")
        chosen_band = spend_band or topic.spend_band
        errors = _validate_topic_form(name, chosen_band)
        values = {
            "name": name, "therapeutic_area": therapeutic_area, "spend_band": chosen_band,
            "brand": brand, "molecule": molecule, "competitors": competitors,
            "questions": questions, "never_say": never_say,
        }
        if errors:
            return render(
                request, "topic_form.html", status_code=422, mode="edit", topic=topic,
                band_cards=_band_cards(), errors=errors, values=values,
                field_guide=FIELD_GUIDE,
            )
        topic_store.update(
            topic_id,
            name=name.strip(), therapeutic_area=therapeutic_area.strip(), spend_band=chosen_band,
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
            tiers=_deliverable_tiers_ctx(_empty_deliverable_cards()),
        )

    @app.get("/topics/{topic_id}/delete", response_class=HTMLResponse)
    def topic_delete_confirm(request: Request, topic_id: str) -> Any:
        """A page, not a dialog, and a GET that changes nothing.

        Deleting is the one irreversible thing this app can do, so it gets the
        same treatment as committing spend: say exactly what goes, count it,
        and make the destructive step a POST that cannot be reached by
        following a link or by a crawler.
        """
        try:
            topic = topic_store.get(topic_id)
        except NoSuchTopic:
            return error_page(request, 404, "Topic not found", f"No topic with id {topic_id!r}.")
        runs = run_store.for_topic(topic_id)
        return render(
            request, "topic_delete.html", topic=topic,
            counts={
                "runs": len(runs),
                "snapshots": len([r for r in runs if r.mode == "mine" and r.status == "complete"]),
                "insights": len([r for r in runs if r.mode == "insight"]),
                "reports": len([r for r in runs if r.mode == "report"]),
            },
            spend=round(sum(r.cost_usd for r in runs), 4),
            warning=DELETE_WARNING,
        )

    @app.post("/topics/{topic_id}/delete")
    def topic_delete(request: Request, topic_id: str) -> Any:
        refusal = read_only_refusal(request)
        if refusal is not None:
            return refusal
        try:
            topic_store.get(topic_id)
        except NoSuchTopic:
            return error_page(request, 404, "Topic not found", f"No topic with id {topic_id!r}.")
        # Runs first. If this fails halfway the topic is still there, so the
        # delete can be retried; the other order would orphan the runs behind a
        # topic that no longer exists and nothing would ever list them again.
        deleted = run_store.delete_for_topic(topic_id)
        topic_store.delete(topic_id)
        logger.info("deleted topic %s and %d run(s)", topic_id, deleted)
        return RedirectResponse(url="/", status_code=303)

    @app.post("/topics/{topic_id}/mine")
    def topic_mine(request: Request, topic_id: str, band: str = Form("")) -> Any:
        refusal = read_only_refusal(request)
        if refusal is not None:
            return refusal
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
            miner = get_miner(settings, band=topic.band())
            run = run_mine(
                topic, run_store, client=client, miner=miner, cap_usd=settings.run_cost_cap_usd
            )
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
        fr = _flow_runs(run_store, run)
        deliv_tiers = _deliverable_tiers_ctx(
            _deliverable_cards(
                run_store, mine_run=fr["mine_run"], insight_run=fr["insight_run"],
                report_run=fr["report_run"],
            )
        )
        current_step = {"mine": "snapshot", "insight": "insight", "report": "report"}[run.mode]
        return render(
            request, "run.html", run=run, topic=topic, stages=stages,
            cost_detail=cost_detail, next_snapshot_run_id=next_snapshot_run_id,
            next_insight_run_id=next_insight_run_id,
            flow=fr["flow"], current_step=current_step, deliv_tiers=deliv_tiers,
            synthetic=_mine_run_is_synthetic(run_store, fr["flow"]["mine_run_id"]),
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

        fr = _flow_runs(run_store, run)
        deliv_tiers = _deliverable_tiers_ctx(
            _deliverable_cards(
                run_store, mine_run=fr["mine_run"], insight_run=fr["insight_run"],
                report_run=fr["report_run"],
            )
        )
        return render(
            request, "snapshot.html", run=run, topic=topic, rows=filtered,
            total_rows=len(enriched), coverage=coverage, mix=mix,
            filters={"venue": venue, "kind": kind, "tier": tier, "date": date},
            options={"venues": venues, "kinds": kinds, "tiers": tiers, "dates": dates},
            any_filter_active=bool(venue or kind or tier or date),
            flow=fr["flow"], deliv_tiers=deliv_tiers,
            synthetic=any_synthetic(raw_rows),
        )

    @app.post("/runs/{run_id}/insight")
    def insight_create(request: Request, run_id: str) -> Any:
        refusal = read_only_refusal(request)
        if refusal is not None:
            return refusal
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

        forest_rows = _forest_rows(themes, findings, duallens)
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

        fr = _flow_runs(run_store, run)
        deliv_tiers = _deliverable_tiers_ctx(
            _deliverable_cards(
                run_store, mine_run=fr["mine_run"], insight_run=fr["insight_run"],
                report_run=fr["report_run"],
            )
        )
        return render(
            request, "insight.html", run=run, topic=topic, mine_run_id=mine_run_id,
            snapshot_rail=snapshot_rail, plot_guide=PLOT_GUIDE,
            forest_svg=forest_svg, forest_rows=forest_rows,
            momentum_rows=momentum_rows, has_baseline=has_baseline,
            anomaly_rows=anomaly_rows, theme_rows=theme_rows,
            stance_rows=stance_rows, entity_rows=entity_rows,
            unmapped_count=len(entities.get("unmapped_mentions", [])),
            flow=fr["flow"], deliv_tiers=deliv_tiers,
            synthetic=_mine_run_is_synthetic(run_store, mine_run_id),
        )

    @app.post("/runs/{run_id}/report")
    def report_create(request: Request, run_id: str) -> Any:
        refusal = read_only_refusal(request)
        if refusal is not None:
            return refusal
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
        except FileNotFoundError as exc:
            # `run_report` reads seven artifacts it cannot proceed without:
            # the snapshot's `signals.json`, to rebuild the citation ledger, and
            # six of the insight run's own. Any of them can be the one that
            # is missing, so **say which**. This message used to assert
            # `signals.json` unconditionally, which sent a reader looking at
            # the wrong run — and cost real time diagnosing a live failure that
            # was not about that file at all. The backends all raise
            # `FileNotFoundError("no artifact named X on run Y")`, so the
            # detail is already in hand.
            logger.warning("report %s could not read a required artifact: %s", run_id, exc)
            return error_page(
                request, 400, "A required artifact is missing",
                f"The report could not be built: {exc}. If this is a run that "
                "just completed, retry — otherwise mine a fresh snapshot and "
                "generate insight again.",
            )
        return RedirectResponse(url=f"/runs/{rep.run_id}/report", status_code=303)

    @app.get("/runs/{run_id}/report", response_class=HTMLResponse)
    def report_view(request: Request, run_id: str) -> HTMLResponse:
        """The client-facing document, typeset.

        This route does presentation-only reshaping of four artifacts the
        engine already wrote — it derives no number and authors no sentence.
        The claim sentences rendered as designed findings are lifted from
        ``pulse_report.md``'s own sections rather than rebuilt here, because
        rebuilding them would put the report's prose in two places and let
        the page and the downloaded file drift apart.
        """
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

        def _read_json(run_id_for_read: str | None, name: str) -> Any:
            # A REPORT run's own four markdown files can be intact while the
            # INSIGHT run it was built from has since lost the artifacts this
            # view re-reads — the same ephemeral-storage failure mode
            # `_read_md` guards for this run's own files. Unguarded, this
            # used to raise `FileNotFoundError` straight through to a 500 on
            # an otherwise perfectly viewable report.
            if not run_id_for_read:
                return []
            try:
                return run_store.read_artifact(run_id_for_read, name)
            except FileNotFoundError:
                return []

        pulse_text = _read_md("pulse_report.md")
        appendix_text = _read_md("provenance_appendix.md")
        methodology_text = _read_md("methodology.md")
        considering_text = _read_md("worth_considering.md")

        # ---- the citation ledger, numbered ------------------------------
        # Header: signal_id | venue | venue kind | captured_at | collection
        # method | URL. Reference numbers are assigned in the appendix's own
        # order, so [7] on the page and row 7 of the downloaded appendix are
        # the same source.
        citations = [
            {"signal_id": r[0], "venue": r[1], "venue_kind": r[2],
             "captured_at": r[3], "method": r[4], "url": r[5]}
            for r in _parse_pipe_table_rows(appendix_text) if len(r) >= 6
        ]
        for n, c in enumerate(citations, start=1):
            c["ref"] = n
            c["anchor"] = f"ref-{n}"
            c["back"] = []
        ref_by_sid = {c["signal_id"]: c for c in citations}

        def refs_for(signal_ids: Any, anchor: str, label: str) -> list[dict[str, Any]]:
            """Superscript references for one claim, and the reciprocal link
            recorded on each appendix row so the appendix is not a one-way
            street. Only ids that actually resolved to an appendix row are
            rendered: a reference to a row that does not exist is worse than
            no reference, and G1 in `vsm/modes/report.py` has already
            refused any report whose citations could not be rebuilt."""
            out = []
            for sid in signal_ids or []:
                c = ref_by_sid.get(str(sid))
                if c is None:
                    continue
                out.append({"ref": c["ref"], "anchor": c["anchor"], "signal_id": c["signal_id"]})
                if not any(b["anchor"] == anchor for b in c["back"]):
                    c["back"].append({"anchor": anchor, "label": label})
            return sorted(out, key=lambda r: r["ref"])

        raw_themes = _read_json(insight_run_id, "themes.json")
        raw_findings = _read_json(insight_run_id, "findings.json")
        duallens = _read_json(insight_run_id, "duallens.json")
        signals = _read_json(mine_run_id, "signals.json")

        paired = list(zip(raw_themes, raw_findings))

        # ---- the document's own sections --------------------------------
        # Four of the pulse report's sections are rendered as designed
        # components below (findings, the figure, the themes table) and are
        # therefore dropped from the prose pass — otherwise the page carries
        # each of them twice, which is what it used to do.
        designed = {
            "Themes observed",
            "Corroborated findings",
            "Emerging (two-source) signals",
            "Patient vs. HCP divergence",
        }
        lead_html_parts: list[str] = []
        extra_sections: list[dict[str, str]] = []
        designed_bodies: dict[str, str] = {}
        for section in markdown_sections(pulse_text):
            if section["level"] <= 1:
                # The document's own title is the cover; only its lead-in
                # prose (the synthetic-run notice, when there is one) is kept.
                if section["body"].strip():
                    lead_html_parts.append(markdown_to_html(section["body"], base_level=3))
                continue
            if section["heading"] in designed:
                designed_bodies[section["heading"]] = section["body"]
                continue
            extra_sections.append({
                "heading": section["heading"],
                "html": markdown_to_html(section["body"], base_level=3),
            })

        def _designed_findings(tier: str, heading: str) -> tuple[list[dict[str, Any]], str]:
            """One designed statement per finding of `tier`, and the note that
            stands in when there are none.

            `vsm/modes/report.py` writes exactly one paragraph per finding of
            this tier, in this order. When the counts disagree — a hand-edited
            artifact, a future change to that module — the claim falls back to
            the theme name and the counts stay beside it, because a count is
            arithmetic and safe to show while a mismatched sentence is not.
            """
            rows = [(i, t, f) for i, (t, f) in enumerate(paired) if f["tier"] == tier]
            paragraphs = markdown_paragraphs(designed_bodies.get(heading, ""))
            if not rows:
                return [], markdown_to_html(designed_bodies.get(heading, ""), base_level=3)
            out = []
            for slot, (index, theme, finding) in enumerate(rows):
                anchor = f"finding-{index + 1}"
                claim_md = paragraphs[slot] if slot < len(paragraphs) else theme["name"]
                out.append({
                    "anchor": anchor,
                    "name": theme["name"],
                    "claim_html": markdown_inline_html(claim_md),
                    "tier": finding["tier"],
                    "sources": finding["independent_sources"],
                    "volume": theme["volume"],
                    "refs": refs_for(finding.get("signal_ids"), anchor, theme["name"]),
                })
            return out, ""

        corroborated, corroborated_note = _designed_findings(
            "corroborated", "Corroborated findings"
        )
        emerging, emerging_note = _designed_findings(
            "emerging", "Emerging (two-source) signals"
        )

        # ---- the themes table ------------------------------------------
        theme_rows = []
        for index, (theme, finding) in enumerate(paired):
            anchor = (
                f"finding-{index + 1}"
                if finding["tier"] in ("corroborated", "emerging")
                else f"theme-{index + 1}"
            )
            theme_rows.append({
                "anchor": anchor,
                "row_anchor": f"theme-{index + 1}",
                "name": theme["name"],
                "volume": theme["volume"],
                "tier": finding["tier"],
                "sources": finding["independent_sources"],
                "refs": refs_for(finding.get("signal_ids"), anchor, theme["name"]),
            })

        # ---- Figure 1: the clinician–patient gap ------------------------
        figure_rows = _forest_rows(raw_themes, raw_findings, duallens)
        figure = None
        if figure_rows:
            figure = {
                "number": 1,
                "svg": forest_plot_svg(figure_rows),
                "rows": figure_rows,
                "estimable": sum(1 for r in figure_rows if r["divergence"] is not None),
                "not_estimable": sum(1 for r in figure_rows if r["divergence"] is None),
            }

        # ---- the cover's dated window ----------------------------------
        stamps = sorted(str(s.get("captured_at") or "") for s in signals if s.get("captured_at"))
        venues = {str(s.get("venue") or "") for s in signals if s.get("venue")}
        snapshot_at = None
        if mine_run_id:
            try:
                snapshot_at = run_store.get(mine_run_id).started_at
            except NoSuchRun:
                snapshot_at = None

        tier_counts = {
            "corroborated": sum(1 for _t, f in paired if f["tier"] == "corroborated"),
            "emerging": sum(1 for _t, f in paired if f["tier"] == "emerging"),
            "single_source": sum(1 for _t, f in paired if f["tier"] == "single_source"),
        }

        doc = {
            "title": topic.name if topic is not None else "Topic no longer exists",
            "window_from": stamps[0] if stamps else None,
            "window_to": stamps[-1] if stamps else None,
            # A sweep that ran inside one day is one date, not a range. "31
            # July 2026 to 31 July 2026" is a zero-width window presented as
            # a window, which is the kind of small tell that makes a reader
            # stop trusting the rest of the page.
            "window_single_day": bool(stamps) and stamps[0][:10] == stamps[-1][:10],
            # Said rather than left blank, per this codebase's one rule: a
            # snapshot whose rows carry no capture stamp has no window, and
            # an empty range would read as a window of zero length.
            "window_note": (
                None if stamps
                else "no capture timestamps were recorded on this snapshot's signals"
            ),
            "signal_count": len(signals) if signals else None,
            "signal_note": (
                None if signals
                else "the snapshot this rests on is no longer readable on this instance"
            ),
            "venue_count": len(venues) if signals else None,
            "snapshot_run_id": mine_run_id,
            "snapshot_at": snapshot_at,
            "insight_run_id": insight_run_id,
            "tier_counts": tier_counts,
            "theme_count": len(paired),
            "citation_count": len(citations),
        }

        fr = _flow_runs(run_store, run)
        deliv_tiers = _deliverable_tiers_ctx(
            _deliverable_cards(
                run_store, mine_run=fr["mine_run"], insight_run=fr["insight_run"],
                report_run=fr["report_run"],
            )
        )
        pulse_href = (
            f"/runs/{run.run_id}/artifact/pulse_report.md" if pulse_text else None
        )
        return render(
            request, "report.html", run=run, topic=topic, pulse_href=pulse_href,
            insight_run_id=insight_run_id, mine_run_id=mine_run_id,
            doc=doc, figure=figure, theme_rows=theme_rows,
            corroborated=corroborated, corroborated_note=corroborated_note,
            emerging=emerging, emerging_note=emerging_note,
            lead_html="".join(lead_html_parts), extra_sections=extra_sections,
            citations=citations,
            methodology_html=markdown_to_html(methodology_text, base_level=3, drop_title=True),
            considering_html=markdown_to_html(considering_text, base_level=3, drop_title=True),
            has_pulse=bool(pulse_text and pulse_text.strip()),
            flow=fr["flow"], deliv_tiers=deliv_tiers,
            synthetic=_mine_run_is_synthetic(run_store, mine_run_id),
        )

    @app.get("/runs/{run_id}/artifact/{name:path}")
    def artifact_download(request: Request, run_id: str, name: str) -> Any:
        try:
            run = run_store.get(run_id)
        except NoSuchRun:
            return error_page(request, 404, "Run not found", f"No run with id {run_id!r}.")
        # Read through the store, not the filesystem. `FileResponse` needs a
        # real local file, which only one of the three backends has; on Vercel
        # Blob every download 500ed. Each backend applies its own traversal
        # guard inside `read_artifact` (`RunStore._artifact_path` and
        # `vercel_blob._validated_key` both raise `ValueError`), so a name that
        # escapes the run is refused at the layer that knows what "escapes"
        # means for its own storage, rather than by path arithmetic here that
        # is only meaningful for one of them.
        try:
            content = run_store.read_artifact(run.run_id, name)
        except (FileNotFoundError, ValueError):
            return error_page(
                request, 404, "Artifact not found",
                f"No artifact named {name!r} on run {run_id!r}.",
            )
        suffix = Path(name).suffix
        media = (
            "application/json" if suffix == ".json"
            else "text/markdown; charset=utf-8" if suffix == ".md"
            else "text/plain; charset=utf-8"
        )
        filename = Path(name).name
        return Response(
            _artifact_bytes(content, name),
            media_type=media,
            headers={"content-disposition": f'attachment; filename="{filename}"'},
        )

    return app
