"""Drawing that has to happen in Python: the forest plot and the sparkline.

Both are inline SVG built from plain dicts and floats already computed by
``vsm.analysis`` — nothing here derives a new number, it only places numbers
that already exist. Every piece of dynamic text is escaped before it goes
into the markup, because a theme name can come from an LLM's naming pass (or,
offline, straight from a page title) and this string is trusted by the
browser as markup the moment the template marks it ``|safe``.

The forest plot is a concept kept from the previous direction because it is
the right encoding for the dual-lens gap, but it is drawn in the pinned Vi
system's palette (``vsm/ui/static/ds/colors_and_type.css``): box area is
volume, the whisker spans the signed gap between the patient and clinician
net-stance readings, and a null line at zero divergence is shared by every
row. A theme only one side discussed prints ``NE`` on that null line, dashed
in ink rather than in a warning colour — the Vi palette has no red reserved
for "not estimable"; black structure and a dashed stroke say it instead.
"""

from __future__ import annotations

import math
import re
from datetime import date as _date
from html import escape
from typing import Any, Mapping, Sequence

from vsm.ui.content import TIERS

__all__ = [
    "forest_plot_svg",
    "sparkline_svg",
    "usd",
    "pct",
    "net_stance_text",
    "fmt_dt",
    "fmt_date_long",
    "fmt_date_short",
    "iso_attr",
    "markdown_to_html",
    "markdown_inline_html",
    "markdown_sections",
    "markdown_paragraphs",
    "markdown_excerpt_html",
    # The figure geometry the macros in _macros.html draw from. See
    # docs/design/COMPONENTS.md for the contract each of these publishes.
    "bar_rows",
    "series_points",
    "gap_chart",
    "sentiment_mix",
    "coverage_grid",
    "meter",
    "POLYLINE_MIN",
    "PROPORTION_MIN_N",
    "PERCENT_MIN_N",
    "SENTIMENT_ORDER",
    "COVERAGE_STATES",
]

# Vi's palette (see ds/colors_and_type.css): black rules and structure, Vi
# Violet for the one measured signal — here, the whisker and box that ARE
# the finding — and cool gray for supporting structure (the null line, the
# baseline, axis labels). No red: "not estimable" is drawn dashed in ink,
# not in a warning colour this system doesn't have.
INK = "#000000"
STRUCTURE = "rgba(0, 0, 0, 0.18)"
VIOLET = "#4F31F5"
NE_INK = "#140923"

from vsm.modes.vocabulary import SOURCE_LABEL as _TIER_LABEL
# content.TIERS is the one place tier copy is authored; keys there use a
# space ("single source") where run data uses an underscore. Normalising
# once here lets the plot attach the same sentence as a native SVG <title>
# tooltip instead of inventing a second explanation of what a tier means.
_TIER_NOTE = {key.replace(" ", "_"): note for key, note in TIERS}


def usd(value: float | None, decimals: int = 4) -> str:
    """Money, at the precision this tool actually operates in.

    Four decimals because a probe sweep costs about $0.03 and the cents matter;
    rounding to `$0.03` would hide the difference between a run and ten of them.

    An exact zero drops to `$0.00`. `$0.0000` is truthful and reads as broken,
    and a figure a reader distrusts is worse than a coarser one they believe.
    `None` stays an em dash — that is "not measured", which is a different fact
    from "measured, and it was nothing".
    """
    if value is None:
        return "—"
    if value == 0:
        return "$0.00"
    return f"${value:,.{decimals}f}"


def pct(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:g}%"


#: Why a net stance is absent, per lens. Mirrors `_NET_CELL_REASON` in
#: `vsm/modes/report.py` so the page and the artifact say the same thing in the
#: same cell — they diverged once, and the page was the one that lost the reason.
_NET_ABSENT_REASON = {
    "hcp": "not read — no clinician-class signal in this theme",
    "patient": "not read — no patient-class signal in this theme",
}


def net_stance_text(value: float | None, which: str | None = None) -> str:
    """A net stance, or **why there isn't one**.

    An em dash alone was the defect here. The client artifact prints "not read
    — no patient-class signal in this theme" in this very cell, so the page was
    strictly less honest than the file it previews, and a reader comparing the
    two would find the page silent where the document explained itself.

    `which` is optional so the filter stays usable where the lens is not known;
    without it the reason degrades to a bare dash, which is the old behaviour
    and should be treated as a caller that has not been updated yet.
    """
    if value is None:
        return _NET_ABSENT_REASON.get(which or "", "—")
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}"


def net_stance_short(value: float | None, which: str | None = None) -> str:
    """The same fact as :func:`net_stance_text`, in two words instead of nine.

    A dashboard cell cannot carry "not read — no clinician-class signal in this
    theme", and a bare em dash is the defect that function exists to prevent. So
    the compact form still says *that it was not read* rather than implying a
    zero, and the full reason is one click away on the insight page the row
    links to. `which` is accepted and unused so the two filters are
    interchangeable at a call site.
    """
    if value is None:
        return "not read"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}"


#: Sweep size in plain words. "probe / standard / deep" are internal names for
#: how wide and how expensive a collection run is; "band" is banned from the
#: interface because it also means something unrelated (venue band 1/2/3).
from vsm.modes.vocabulary import SWEEP_SIZE as _SWEEP_SIZE


def sweep_size(value: str | None) -> str:
    """The band's plain-language name, or the raw value if it is unrecognised —
    showing an unknown band verbatim is better than hiding it behind a guess."""
    if not value:
        return "—"
    return _SWEEP_SIZE.get(value, value)


def fmt_dt(value: str | None) -> str:
    """A capture time's label, carrying its zone: `2026-08-25 14:03 UTC`.

    The zone is not decoration. This app's whole commercial claim is that a
    figure traces to a dated row, and a bare `14:03` cannot be resolved to an
    actual instant by anyone reading it — which was the state of every one of
    the five tool screens where "when was this collected" is the load-bearing
    question. The stamp is appended only when the source string actually
    carries one, because inventing a zone would be worse than omitting it.

    Slice rather than parse-and-reformat: a malformed string still shows
    *something* instead of 500ing a whole page over one bad timestamp.
    Templates pair this with :func:`iso_attr` in a `<time datetime="...">` so
    the machine-readable original stays on the page.
    """
    if not value:
        return "undated"
    head = str(value)[:16].replace("T", " ")
    tail = str(value)[16:]
    if tail.endswith("Z") or "+00:00" in tail or "-00:00" in tail:
        return f"{head} UTC"
    # A non-UTC offset is reported verbatim rather than named: naming a zone
    # from an offset alone is a guess (−05:00 is two different zones).
    if len(tail) >= 6 and tail[-6] in "+-":
        return f"{head} UTC{tail[-6:]}"
    return head


def iso_attr(value: str | None) -> str:
    """The machine-readable original, for a `<time datetime="...">` attribute.

    Returns `""` when there is nothing to stamp, so a template can write
    `<time datetime="{{ x|iso }}">` unconditionally: an empty `datetime` is
    ignored by parsers, whereas a `<time>` carrying a human label and no
    attribute silently claims to be machine-readable and is not.
    """
    return "" if not value else str(value)


def fmt_date_short(value: str | None) -> str:
    """`19 Aug` — a sweep's name on screen, where the year is noise.

    Never used anywhere that can reach paper: ux-guidelines row 85 forbids an
    ambiguous date, and "19 Aug" on a printed page a client opens in February
    is exactly that. Use :func:`fmt_date_long` there.
    """
    return _short_date(value)


_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def fmt_date_long(value: str | None) -> str:
    """A date a client reads: `25 August 2026`.

    The machine stamp stays available to a template as the raw value for a
    `<time datetime="...">` attribute — this is the label, not a replacement
    for the traceable original. A string that does not parse as ISO comes
    back sliced rather than guessed at, for the same reason `fmt_dt` does:
    showing something wrong is better than 500ing a whole report over a
    malformed timestamp.
    """
    if not value:
        return "undated"
    head = str(value)[:10]
    parts = head.split("-")
    if len(parts) != 3 or not all(x.isdigit() for x in parts):
        return head or "undated"
    year, month, day = (int(x) for x in parts)
    if not 1 <= month <= 12:
        return head
    return f"{day} {_MONTHS[month - 1]} {year}"


def _row_h(n: int) -> int:
    # The plot is the hero of the insight screen (DIRECTION.md's FIRST
    # VIEWPORT), not an inset thumbnail — rows are sized to read at a
    # glance, not to conserve vertical space.
    return 64


def sparkline_svg(values: Sequence[int], *, width: int = 108, height: int = 30) -> str:
    """A polyline across >=2 points. Callers must not call this for one point
    — one point is not a trend, and drawing it as a flat line would be the
    first lie the tool tells (see PRODUCT.md)."""
    if len(values) < 2:
        return ""
    pad = 4
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    n = len(values)
    step = (width - 2 * pad) / (n - 1)

    def _xy(i: int, v: int) -> tuple[float, float]:
        x = pad + step * i
        y = height - pad - ((v - lo) / span) * (height - 2 * pad)
        return round(x, 1), round(y, 1)

    pts = [_xy(i, v) for i, v in enumerate(values)]
    points_attr = " ".join(f"{x},{y}" for x, y in pts)
    last_x, last_y = pts[-1]
    baseline_y = height - pad
    return (
        f'<svg class="sparkline" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="none" role="img" aria-label="volume across '
        f'{n} snapshots, {lo} to {hi}">'
        f'<line x1="{pad}" y1="{baseline_y}" x2="{width - pad}" y2="{baseline_y}" '
        f'stroke="{STRUCTURE}" stroke-width="1" />'
        f'<polyline points="{points_attr}" fill="none" stroke="{VIOLET}" '
        f'stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round" />'
        f'<circle cx="{last_x}" cy="{last_y}" r="2.2" fill="{VIOLET}" />'
        f"</svg>"
    )


def forest_plot_svg(rows: Sequence[Mapping[str, Any]]) -> str:
    """One row per theme, ordered by weight (the caller sorts by volume).

    Each row dict: ``name``, ``volume``, ``hcp_net``, ``patient_net``,
    ``divergence``, ``reason``, ``independent_sources``, ``tier``.
    """
    rows = list(rows)
    n = len(rows)
    # Enlarged from the original 220/320/170: the direction calls this the
    # hero of the insight screen, full content width, generous row height —
    # not an inset thumbnail. Proportions keep the same three-zone layout
    # (theme name / plotted field / sources+tier), just at instrument scale.
    left_w, plot_w, right_w = 260, 460, 200
    header_h, footer_h = 40, 60
    row_h = _row_h(n)
    total_w = left_w + plot_w + right_w
    total_h = header_h + row_h * max(n, 1) + footer_h

    if n == 0:
        return (
            f'<svg viewBox="0 0 {total_w} 160" role="img" aria-label="no themes">'
            f'<text x="{total_w / 2}" y="80" text-anchor="middle" '
            f'font-size="15" fill="{INK}">No themes in this snapshot.</text>'
            f"</svg>"
        )

    measured = [r for r in rows if r.get("divergence") is not None]
    max_abs = max((abs(float(r["divergence"])) for r in measured), default=0.0)
    half_domain = max(0.2, max_abs * 1.35)
    plot_inner = plot_w / 2 - 20
    axis_x = left_w + plot_w / 2

    def x_of(gap: float) -> float:
        return axis_x + (gap / half_domain) * plot_inner

    max_volume = max((int(r["volume"]) for r in rows), default=1) or 1
    min_side, max_side = 16.0, 40.0

    def side_of(volume: int) -> float:
        frac = math.sqrt(max(0.0, volume) / max_volume)
        return min_side + (max_side - min_side) * frac

    parts: list[str] = [
        f'<svg viewBox="0 0 {total_w} {total_h}" width="100%" '
        f'role="img" aria-label="forest plot of {n} themes by patient-versus-'
        f'clinician divergence">'
    ]

    # ---- header legends (condensed, structure ink) ------------------------
    parts.append(
        f'<text x="16" y="24" class="plot-legend-text">THEME</text>'
        f'<text x="{axis_x}" y="24" text-anchor="middle" class="plot-legend-text">'
        f"GAP — PATIENT MINUS CLINICIAN</text>"
        f'<text x="{left_w + plot_w + 16}" y="24" class="plot-legend-text">SOURCES</text>'
        f'<text x="{total_w - 16}" y="24" text-anchor="end" class="plot-legend-text">TIER</text>'
    )

    top_y = header_h
    bottom_y = header_h + row_h * n

    # ---- the null line, shared by every row --------------------------------
    parts.append(
        f'<line x1="{x_of(0):.1f}" y1="{top_y}" x2="{x_of(0):.1f}" y2="{bottom_y}" '
        f'stroke="{STRUCTURE}" stroke-width="1.25" />'
    )

    for i, row in enumerate(rows):
        y = header_h + row_h * i + row_h / 2
        name = escape(str(row.get("name", "")))
        volume = int(row.get("volume", 0))
        divergence = row.get("divergence")
        reason = escape(str(row.get("reason") or ""))
        sources = row.get("independent_sources")
        tier = str(row.get("tier") or "")
        tier_label = escape(_TIER_LABEL.get(tier, tier or "—"))

        parts.append(
            f'<text x="16" y="{y - 8:.1f}" class="plot-theme-name">{name}</text>'
            f'<text x="16" y="{y + 15:.1f}" class="plot-theme-sub">'
            f"{volume} signal{'s' if volume != 1 else ''}</text>"
        )

        if divergence is None:
            side = side_of(volume)
            cx = x_of(0.0)
            half_span = side / 2 + 18
            parts.append(
                f'<g aria-label="not estimable: {reason}">'
                f'<line x1="{cx - half_span:.1f}" y1="{y:.1f}" x2="{cx + half_span:.1f}" y2="{y:.1f}" '
                f'stroke="{NE_INK}" stroke-width="2.25" stroke-dasharray="4,4" />'
                f'<rect x="{cx - side / 2:.1f}" y="{y - side / 2:.1f}" '
                f'width="{side:.1f}" height="{side:.1f}" fill="none" '
                f'stroke="{NE_INK}" stroke-width="2.25" />'
                f'<text x="{cx:.1f}" y="{y - side / 2 - 10:.1f}" text-anchor="middle" '
                f'class="plot-ne-label">NE</text>'
                f"</g>"
            )
        else:
            gap = float(divergence)
            x0, x1 = x_of(0.0), x_of(gap)
            side = side_of(volume)
            parts.append(
                f'<g aria-label="{name}: divergence {gap:.2f}">'
                f'<line x1="{x0:.1f}" y1="{y:.1f}" x2="{x1:.1f}" y2="{y:.1f}" '
                f'stroke="{VIOLET}" stroke-width="2.75" />'
                f'<rect x="{x1 - side / 2:.1f}" y="{y - side / 2:.1f}" '
                f'width="{side:.1f}" height="{side:.1f}" fill="{VIOLET}" '
                f'fill-opacity="0.82" stroke="{INK}" stroke-width="1" />'
                f"</g>"
            )

        src_text = "—" if sources is None else str(int(sources))
        tier_note = escape(_TIER_NOTE.get(tier, ""))
        tier_title = f"<title>{tier_note}</title>" if tier_note else ""
        parts.append(
            f'<text x="{left_w + plot_w + 16}" y="{y + 5:.1f}" '
            f'class="plot-num">{src_text}</text>'
            f'<text x="{total_w - 16}" y="{y + 5:.1f}" text-anchor="end" '
            f'class="plot-tier plot-tier-{escape(tier)}">{tier_label}{tier_title}</text>'
        )

    # ---- baseline + axis end labels ----------------------------------------
    parts.append(
        f'<line x1="{left_w}" y1="{bottom_y}" x2="{left_w + plot_w}" y2="{bottom_y}" '
        f'stroke="{STRUCTURE}" stroke-width="1.25" />'
        f'<text x="{left_w}" y="{bottom_y + 22}" class="plot-axis-end">'
        f"PATIENTS MORE NEGATIVE</text>"
        f'<text x="{left_w + plot_w}" y="{bottom_y + 22}" text-anchor="end" '
        f'class="plot-axis-end">CLINICIANS MORE NEGATIVE</text>'
        f'<text x="{x_of(0):.1f}" y="{bottom_y + 42}" text-anchor="middle" '
        f'class="plot-axis-end">NO GAP</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


# ==========================================================================
# Markdown -> HTML. One converter, one place.
# ==========================================================================
#
# Every markdown surface in this app goes through `markdown_to_html`. That is
# the whole point of it living here rather than in a template filter or a
# per-route helper: the failure that produced this module was raw `**bold**`
# reaching a client-facing page, and the only structural fix for "raw syntax
# can reach a page" is that no surface is allowed its own converter.
#
# It is not a general CommonMark implementation and does not pretend to be —
# no third-party markdown dependency is on this project's allowed list. It is
# a complete-enough converter for prose: ATX and setext headings, fenced and
# indented code, blockquotes (nested), bullet and ordered lists (nested),
# pipe tables with escaped pipes and alignment, thematic breaks, and inline
# code, links, autolinks, bare URLs, images, strong, emphasis, strikethrough,
# hard breaks and backslash escapes. Anything it cannot parse is emitted as
# escaped text, never as the source syntax it came from.
#
# Two deliberate refusals:
#
# * `href` schemes are allow-listed (http, https, mailto, and anything with
#   no scheme at all). A `javascript:` URL in a model-authored link is not
#   rendered as a link — the label survives, the href does not.
# * Headings are emitted at `base_level` and below, clamped at `h6`, so a
#   document rendered inside a page cannot mint a second `<h1>` and flatten
#   the page's own outline.

_MD_ATX_RE = re.compile(r"^(#{1,6})(?:[ \t]+(.*?))?[ \t]*#*[ \t]*$")
_MD_FENCE_RE = re.compile(r"^(`{3,}|~{3,})[ \t]*([A-Za-z0-9_+#.-]*)[ \t]*$")
_MD_HR_RE = re.compile(
    r"^ {0,3}(?:\*[ \t]*){3,}$|^ {0,3}(?:-[ \t]*){3,}$|^ {0,3}(?:_[ \t]*){3,}$"
)
_MD_SETEXT1_RE = re.compile(r"^ {0,3}=+[ \t]*$")
_MD_SETEXT2_RE = re.compile(r"^ {0,3}-+[ \t]*$")
_MD_QUOTE_RE = re.compile(r"^ {0,3}>[ \t]?(.*)$")
_MD_ITEM_RE = re.compile(r"^( *)(?:([-*+])|(\d{1,9})[.)])( +|\t)(.*)$")
_MD_PIPE_ROW_RE = re.compile(r"^\s*\|")
_MD_DELIM_ROW_RE = re.compile(r"^[\s|:-]*-[\s|:-]*$")
_MD_INDENTED_CODE_RE = re.compile(r"^ {4,}\S")

#: The character run a paragraph's hard line break is folded to before the
#: inline pass sees it. A literal NUL is stripped from the input, so this can
#: never collide with document content.
_MD_BREAK = "\x00"

_MD_ESCAPABLE = set("\\`*_{}[]()#+-.!|>~<&\"'/:")

_MD_CODE_SPAN_RE = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.S)
_MD_LINK_RE = re.compile(
    r"\[(?P<label>(?:[^\[\]\\]|\\.)*)\]\("
    r"(?P<href><[^>]*>|(?:[^()\s]|\([^()\s]*\))*)"
    r"(?:[ \t]+\"(?P<title>[^\"]*)\")?\)"
)
_MD_IMAGE_RE = re.compile(r"!(?=\[)")
_MD_AUTOLINK_RE = re.compile(r"<((?:https?://|mailto:)[^>\s]+)>")
_MD_BARE_URL_RE = re.compile(r"https?://[^\s<>\"'`\]]+")
_MD_STRONG_EM_RE = re.compile(r"\*\*\*(?=\S)(.+?)(?<=\S)\*\*\*", re.S)
_MD_STRONG_STAR_RE = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.S)
_MD_STRONG_UNDER_RE = re.compile(r"__(?=\S)(.+?)(?<=\S)__(?!\w)", re.S)
_MD_EM_STAR_RE = re.compile(r"\*(?=\S)([^*]+?)(?<=\S)\*", re.S)
# Deliberately narrow, and the narrowness is load-bearing: without the word
# boundaries this matches straight through identifiers like
# `hcp_discussion, patient_community` — the first `_` pairs with the next
# unrelated `_` and swallows the space and comma between them. `kind_mix`
# and `venue_mix` keys are exactly that shape, so this is not hypothetical.
_MD_EM_UNDER_RE = re.compile(r"(?<!\w)_(?=\S)([^_]+?)(?<=\S)_(?!\w)", re.S)
_MD_STRIKE_RE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.S)
_MD_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_MD_SAFE_SCHEMES = ("http:", "https:", "mailto:")
_MD_NUMERIC_CELL_RE = re.compile(r"^[+-]?[\d,]+(?:\.\d+)?%?$")


def _md_href(raw: str) -> str:
    """An escaped href, or `""` when the scheme is not one we will link to.

    A refused href drops the link and keeps the label — the reader still
    reads the words, and the page never carries a scheme this app did not
    intend to hand a browser.
    """
    url = raw.strip()
    if url.startswith("<") and url.endswith(">"):
        url = url[1:-1].strip()
    if not url:
        return ""
    m = _MD_SCHEME_RE.match(url)
    if m and not url.lower().startswith(_MD_SAFE_SCHEMES):
        return ""
    return escape(url, quote=True)


def _md_inline(text: str) -> str:
    """Inline markdown, as HTML. Every literal character is escaped on the
    way out; only tags this function itself emits are markup."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]

        if ch == "\\" and i + 1 < n and text[i + 1] in _MD_ESCAPABLE:
            out.append(escape(text[i + 1]))
            i += 2
            continue
        if ch == _MD_BREAK:
            out.append("<br>")
            i += 1
            continue
        if ch == "\n":
            out.append(" ")
            i += 1
            continue
        if ch == "`":
            m = _MD_CODE_SPAN_RE.match(text, i)
            if m:
                out.append(f"<code>{escape(m.group(2).strip())}</code>")
                i = m.end()
                continue
        if ch == "!" and _MD_IMAGE_RE.match(text, i):
            m = _MD_LINK_RE.match(text, i + 1)
            if m:
                # No image is ever rendered: this app loads nothing over the
                # network, and an <img> pointing at a remote host would be
                # the one exception. The alt text is the content; the source
                # becomes a link beside it so nothing is silently dropped.
                alt = _md_inline(m.group("label")) or "image"
                href = _md_href(m.group("href"))
                out.append(
                    f'<a href="{href}">{alt}</a>' if href else f"<span>{alt}</span>"
                )
                i = m.end()
                continue
        if ch == "[":
            m = _MD_LINK_RE.match(text, i)
            if m:
                label = _md_inline(m.group("label"))
                href = _md_href(m.group("href"))
                title = m.group("title")
                if href:
                    t = f' title="{escape(title, quote=True)}"' if title else ""
                    out.append(f'<a href="{href}"{t}>{label}</a>')
                else:
                    out.append(label)
                i = m.end()
                continue
        if ch == "<":
            m = _MD_AUTOLINK_RE.match(text, i)
            if m:
                href = _md_href(m.group(1))
                shown = escape(m.group(1))
                out.append(f'<a href="{href}">{shown}</a>' if href else shown)
                i = m.end()
                continue
        if ch in "hH":
            m = _MD_BARE_URL_RE.match(text, i)
            if m:
                url = m.group(0).rstrip(".,;:!?)")
                href = _md_href(url)
                out.append(f'<a href="{href}">{escape(url)}</a>' if href else escape(url))
                i += len(url)
                continue
        if ch == "*" or ch == "_":
            for pattern, tag in (
                (_MD_STRONG_EM_RE, "strong-em"),
                (_MD_STRONG_STAR_RE, "strong"),
                (_MD_STRONG_UNDER_RE, "strong"),
                (_MD_EM_STAR_RE, "em"),
                (_MD_EM_UNDER_RE, "em"),
            ):
                m = pattern.match(text, i)
                if m:
                    inner = _md_inline(m.group(1))
                    if tag == "strong-em":
                        out.append(f"<strong><em>{inner}</em></strong>")
                    else:
                        out.append(f"<{tag}>{inner}</{tag}>")
                    i = m.end()
                    break
            else:
                out.append(escape(ch))
                i += 1
            continue
        if ch == "~":
            m = _MD_STRIKE_RE.match(text, i)
            if m:
                out.append(f"<del>{_md_inline(m.group(1))}</del>")
                i = m.end()
                continue
        out.append(escape(ch))
        i += 1
    return "".join(out)


def _md_split_cells(row: str) -> list[str]:
    """A pipe-table row's cells, honouring `\\|` inside a cell.

    A bare `.split("|")` splits an escaped pipe and hands the table one cell
    too many, which is how a three-column header ends up over a four-cell
    row. The escape survives into the cell text and the inline pass turns it
    back into a literal `|`.
    """
    body = row.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", body)]


def _md_alignments(cells: list[str]) -> list[str]:
    out = []
    for c in cells:
        c = c.strip()
        if c.startswith(":") and c.endswith(":"):
            out.append("center")
        elif c.endswith(":"):
            out.append("right")
        elif c.startswith(":"):
            out.append("left")
        else:
            out.append("")
    return out


def _md_table(block: list[str], caption: str) -> str:
    rows = [_md_split_cells(ln) for ln in block]
    header = rows[0]
    body = rows[1:]
    aligns = [""] * len(header)
    if body and _MD_DELIM_ROW_RE.match(block[1].strip()):
        aligns = _md_alignments(body[0])
        body = body[1:]
    aligns += [""] * (len(header) - len(aligns))

    width = len(header)
    body = [r + [""] * (width - len(r)) if len(r) < width else r for r in body]

    # A column whose every filled cell is a number is right-aligned and set
    # in tabular numerals, so counts line up down the column. Explicit
    # alignment in the delimiter row wins over the guess.
    numeric = []
    for col in range(width):
        cells = [r[col] for r in body if col < len(r) and r[col].strip()]
        numeric.append(bool(cells) and all(_MD_NUMERIC_CELL_RE.match(c) for c in cells))

    def cls(col: int) -> str:
        align = aligns[col] if col < len(aligns) else ""
        if align == "right" or (not align and numeric[col]):
            return ' class="num"'
        if align == "center":
            return ' class="mid"'
        return ""

    thead = "".join(
        f'<th scope="col"{cls(c)}>{_md_inline(h)}</th>' for c, h in enumerate(header)
    )
    trs = []
    for r in body:
        tds = "".join(f"<td{cls(c)}>{_md_inline(v)}</td>" for c, v in enumerate(r))
        trs.append(f"<tr>{tds}</tr>")
    cap = escape(caption) if caption else "Table"
    return (
        f'<div class="table-scroll" tabindex="0" role="region" '
        f'aria-label="{escape(cap)}">'
        f'<table class="doc-table">'
        f'<caption class="visually-hidden">{cap}</caption>'
        f"<thead><tr>{thead}</tr></thead><tbody>{''.join(trs)}</tbody></table></div>"
    )


def _md_dedent(lines: list[str], width: int) -> list[str]:
    out = []
    for ln in lines:
        stripped = ln[:width]
        if stripped.strip():  # less indented than expected — keep as-is
            out.append(ln.lstrip())
        else:
            out.append(ln[width:])
    return out


def _md_list(lines: list[str], start: int, level: int, ctx: dict) -> tuple[str, int]:
    m = _MD_ITEM_RE.match(lines[start])
    assert m is not None
    indent = len(m.group(1))
    ordered = m.group(3) is not None
    first_num = m.group(3)

    items: list[list[str]] = []
    loose = False
    i, n = start, len(lines)
    while i < n:
        m = _MD_ITEM_RE.match(lines[i])
        if m is None or len(m.group(1)) < indent:
            break
        if len(m.group(1)) > indent:
            # A deeper marker with no parent item is not ours to consume.
            break
        if (m.group(3) is not None) != ordered:
            break
        content_indent = len(m.group(1)) + len(m.group(2) or m.group(3) or "") + len(m.group(4))
        item = [m.group(5)]
        i += 1
        blanks = 0
        while i < n:
            ln = lines[i]
            if not ln.strip():
                # A blank line only continues the item if indented content
                # follows it; otherwise the list ends here.
                j = i + 1
                while j < n and not lines[j].strip():
                    j += 1
                if j < n and (
                    len(lines[j]) - len(lines[j].lstrip(" ")) >= content_indent
                ):
                    item.append("")
                    blanks += 1
                    i += 1
                    continue
                break
            lead = len(ln) - len(ln.lstrip(" "))
            if lead >= content_indent:
                item.append(ln[content_indent:])
                i += 1
                continue
            if _MD_ITEM_RE.match(ln) or _MD_ATX_RE.match(ln.strip()) or _MD_PIPE_ROW_RE.match(ln):
                break
            # Lazy continuation: an unindented wrap of the same paragraph.
            item.append(ln.strip())
            i += 1
        if blanks:
            loose = True
        items.append(item)

    rendered = []
    for item in items:
        inner = _md_blocks(item, level, ctx)
        # A tight list item's leading paragraph is unwrapped, so a one-line
        # item is one line of text rather than a block with a paragraph's
        # margins. A nested list under it still nests — only the wrapper of
        # the *first* block goes.
        open_p = '<p class="doc-p">'
        if not loose and inner.startswith(open_p):
            end = inner.find("</p>")
            if end != -1:
                inner = inner[len(open_p):end] + inner[end + 4:]
        rendered.append(f"<li>{inner}</li>")
    tag = "ol" if ordered else "ul"
    attr = ""
    if ordered and first_num and first_num != "1":
        attr = f' start="{int(first_num)}"'
    return f'<{tag} class="doc-list"{attr}>{"".join(rendered)}</{tag}>', i


def _md_heading(level: int, base: int, text: str, ctx: dict) -> str:
    tag = min(base + level - 1, 6)
    ctx["heading"] = re.sub(r"\s+", " ", re.sub(r"[*_`]", "", text)).strip()
    return f'<h{tag} class="doc-h{level}">{_md_inline(text)}</h{tag}>'


def _md_blocks(lines: list[str], base: int, ctx: dict) -> str:
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        raw = lines[i]
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        m = _MD_FENCE_RE.match(stripped)
        if m:
            fence = m.group(1)[0] * 3
            lang = m.group(2)
            body: list[str] = []
            i += 1
            while i < n and not lines[i].strip().startswith(fence):
                body.append(lines[i])
                i += 1
            if i < n:
                i += 1
            attr = f' class="language-{escape(lang, quote=True)}"' if lang else ""
            out.append(
                f'<pre class="doc-code"><code{attr}>{escape(chr(10).join(body))}</code></pre>'
            )
            continue

        if _MD_HR_RE.match(line):
            out.append('<hr class="doc-rule">')
            i += 1
            continue

        m = _MD_ATX_RE.match(stripped)
        if m:
            out.append(_md_heading(len(m.group(1)), base, m.group(2) or "", ctx))
            i += 1
            continue

        if _MD_QUOTE_RE.match(line):
            block: list[str] = []
            while i < n and (
                _MD_QUOTE_RE.match(lines[i]) or (lines[i].strip() and block)
            ):
                qm = _MD_QUOTE_RE.match(lines[i])
                block.append(qm.group(1) if qm else lines[i].strip())
                i += 1
            out.append(f'<blockquote class="doc-quote">{_md_blocks(block, base, ctx)}</blockquote>')
            continue

        if _MD_PIPE_ROW_RE.match(line):
            block = []
            while i < n and _MD_PIPE_ROW_RE.match(lines[i].strip() or ""):
                block.append(lines[i].strip())
                i += 1
            out.append(_md_table(block, ctx.get("heading", "")))
            continue

        if _MD_ITEM_RE.match(line):
            html, i = _md_list(lines, i, base, ctx)
            out.append(html)
            continue

        if _MD_INDENTED_CODE_RE.match(raw):
            body = []
            while i < n and (_MD_INDENTED_CODE_RE.match(lines[i]) or not lines[i].strip()):
                body.append(lines[i][4:] if lines[i].startswith("    ") else lines[i].strip())
                i += 1
            while body and not body[-1].strip():
                body.pop()
            out.append(f'<pre class="doc-code"><code>{escape(chr(10).join(body))}</code></pre>')
            continue

        # Setext heading: this line's text, underlined on the next.
        if i + 1 < n and stripped:
            nxt = lines[i + 1].rstrip()
            if _MD_SETEXT1_RE.match(nxt) and nxt.strip():
                out.append(_md_heading(1, base, stripped, ctx))
                i += 2
                continue
            if _MD_SETEXT2_RE.match(nxt) and len(nxt.strip()) >= 2:
                out.append(_md_heading(2, base, stripped, ctx))
                i += 2
                continue

        block = []
        while i < n:
            ln = lines[i]
            s = ln.strip()
            if not s:
                break
            if (
                _MD_ATX_RE.match(s)
                or _MD_ITEM_RE.match(ln)
                or _MD_PIPE_ROW_RE.match(ln)
                or _MD_FENCE_RE.match(s)
                or _MD_QUOTE_RE.match(ln)
                or _MD_HR_RE.match(ln.rstrip())
            ):
                break
            if i > 0 and block:
                nxt = lines[i]
                if _MD_SETEXT1_RE.match(nxt.rstrip()) or (
                    _MD_SETEXT2_RE.match(nxt.rstrip()) and len(nxt.strip()) >= 2
                ):
                    break
            block.append(ln.rstrip() if not ln.rstrip().endswith("  ") else ln.rstrip() + _MD_BREAK)
            i += 1
        if block:
            text = "\n".join(block).replace("  " + _MD_BREAK, _MD_BREAK)
            out.append(f'<p class="doc-p">{_md_inline(text)}</p>')
    return "".join(out)


def markdown_to_html(
    text: str | None, *, base_level: int = 1, drop_title: bool = False
) -> str:
    """Markdown as HTML, with headings emitted at `base_level` and below.

    `base_level=3` renders a document's `#` as `<h3>`, which is how a whole
    artifact is placed inside a page that already has an `<h1>` and `<h2>`
    of its own without minting a second `<h1>` or skipping a level.

    `drop_title` removes the document's own leading `#` title. A page that
    has already named the artifact in its section heading would otherwise
    print that name twice, one line apart.
    """
    if not text:
        return ""
    body = text.replace("\r\n", "\n").replace("\r", "\n").replace(_MD_BREAK, "")
    body = body.expandtabs(4).strip("\n")
    if not body.strip():
        return ""
    lines = body.split("\n")
    if drop_title:
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            m = _MD_ATX_RE.match(line.strip())
            if m and len(m.group(1)) == 1:
                lines = lines[i + 1:]
            break
    # The document's *shallowest* heading becomes `base_level`, and the rest
    # shift with it. Without this, a body whose own top heading is `##`
    # (which is what every artifact looks like once its `#` title is dropped)
    # renders one level deeper than the page asked for — and a section `<h2>`
    # followed by an `<h4>` is a skipped level, which flattens the outline
    # for anyone navigating by headings.
    levels = [
        len(m.group(1))
        for m in (_MD_ATX_RE.match(ln.strip()) for ln in lines)
        if m
    ]
    shift = (min(levels) - 1) if levels else 0
    return _md_blocks(lines, max(1, base_level - shift), {"heading": ""})


def markdown_inline_html(text: str | None) -> str:
    """One line of markdown as inline HTML — no wrapping paragraph.

    A finding's claim is a single sentence that has to end with its
    superscript reference marks *inside* the sentence, not in a block after
    it. Rendered as a block, the references detached onto their own line and
    read as a footer rather than as part of the claim.
    """
    if not text:
        return ""
    return _md_inline(" ".join(text.replace("\r\n", "\n").split("\n")).strip())


def markdown_sections(text: str | None) -> list[dict[str, Any]]:
    """A markdown document split at its `##` headings, in order.

    Presentation-only reshaping of a document this same process wrote: it
    lets a view render some of an artifact's sections as designed components
    and the rest as prose, without either one being written twice.

    Returns `[{"heading": str, "level": int, "body": str}, ...]`. Anything
    before the first heading arrives as a section with an empty heading.
    """
    if not text:
        return []
    sections: list[dict[str, Any]] = [{"heading": "", "level": 0, "body": []}]
    for line in text.replace("\r\n", "\n").split("\n"):
        m = _MD_ATX_RE.match(line.strip())
        if m and len(m.group(1)) <= 2:
            sections.append(
                {"heading": (m.group(2) or "").strip(), "level": len(m.group(1)), "body": []}
            )
        else:
            sections[-1]["body"].append(line)
    return [
        {"heading": s["heading"], "level": s["level"], "body": "\n".join(s["body"]).strip("\n")}
        for s in sections
        if s["heading"] or "\n".join(s["body"]).strip()
    ]


def markdown_paragraphs(text: str | None) -> list[str]:
    """A markdown fragment's blank-line-separated paragraphs, as markdown.

    Used where a section is known to hold one paragraph per finding — each
    one becomes a designed statement rather than a run of body copy.
    """
    if not text:
        return []
    blocks: list[list[str]] = [[]]
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.strip():
            blocks[-1].append(line.strip())
        elif blocks[-1]:
            blocks.append([])
    return [" ".join(b) for b in blocks if b]


#: A block containing any of these is the fabrication banner, not a sample.
#: Every synthetic artifact *opens* with it — correctly, since a downloaded file
#: must carry its own warning — so an excerpt taken from the top showed it
#: instead of the output. With ten cards on a page that was the same forty words
#: ten times over, under a page banner that had already said it once, which is
#: how a warning stops being read.
_NOTICE_MARKERS = (
    "fabricated by the offline",
    "Synthetic demonstration run",
)


def markdown_excerpt_html(text: str | None, *, limit: int = 260, min_len: int = 48) -> str:
    """A short, rendered excerpt of a markdown artifact.

    Skips the document's own title, its tables and its rules, and takes the
    first substantive prose block — a paragraph or a bullet list — which it
    renders as markup. `min_len` is what keeps an excerpt off a document's
    standing preamble ("Suggestions, not decisions.", "One row per cited
    signal."): a block that short is a label, not a sample, so the next one
    is preferred and the short one is only used if it is all there is.

    The point is that a deliverable's sample is the *shape of the output*,
    never its source syntax: an excerpt reading `**cost**` is the exact
    defect this module exists to make impossible.
    """
    if not text:
        return ""
    blocks: list[tuple[str, list[str]]] = []
    # Note the excerpt skips the fabrication banner; the artifact keeps it.
    for line in text.replace("\r\n", "\n").split("\n"):
        s_line = line.strip()
        if not s_line:
            if blocks and blocks[-1][1]:
                blocks.append(("", []))
            continue
        if _MD_ATX_RE.match(s_line) or _MD_PIPE_ROW_RE.match(s_line) or _MD_HR_RE.match(s_line):
            if blocks and blocks[-1][1]:
                blocks.append(("", []))
            continue
        kind = "list" if _MD_ITEM_RE.match(line) else "para"
        if not blocks or not blocks[-1][1] or blocks[-1][0] != kind:
            blocks.append((kind, [s_line]))
        else:
            blocks[-1][1].append(s_line)
    candidates = [
        (k, ls) for k, ls in blocks
        if ls and not any(m in " ".join(ls) for m in _NOTICE_MARKERS)
    ]
    if not candidates:
        return ""
    chosen = next(
        (c for c in candidates if sum(len(x) for x in c[1]) >= min_len), candidates[0]
    )
    kind, picked = chosen
    if kind == "list":
        return markdown_to_html("\n".join(picked[:3]))
    joined = " ".join(picked)
    if len(joined) > limit:
        head = joined[:limit].rsplit(" ", 1)[0]
        joined = (head or joined[:limit]) + "…"
    return markdown_to_html(joined)


# ==========================================================================
# Figure geometry: numbers in, positions out.
# ==========================================================================
#
# Everything below is pure arithmetic over values `vsm.analysis` already
# computed. None of it emits markup — the macros in `_macros.html` do that —
# and none of it derives a new fact. The split exists for two reasons.
#
# 1. **StrictUndefined.** A template that reaches for `row.pct` on a row that
#    happens to lack it is a 500, not a blank. Every function here returns the
#    *same keys on every path*, so a macro can address any field of any row
#    without a guard, and a screen author cannot be caught out by a shape that
#    only appears when the data is unusual. Uniform shapes, guarded once here,
#    rather than a guard at each of ~40 call sites.
# 2. **Testability.** Placing a dot on an axis is arithmetic and belongs where
#    arithmetic can be asserted, not inside a Jinja expression.
#
# The encodings themselves are the conventional ones (see
# `docs/design/COMPONENTS.md`); the thresholds below are the ones the
# accessibility rulebook fixed, and each is named at its constant.

#: Below this many sweeps a polyline is a chart of nothing: two points always
#: make a straight line and three make a shape the eye over-reads. charts.csv
#: row 1 ("Trend Over Time") lists "fewer than 4 data points" under *When NOT
#: to Use* and sends that case to a stat card instead. So 1 point is a dot, 2
#: are two dots against a rule, 3 are three dots, and only 4+ get a line.
POLYLINE_MIN = 4

#: Below this many mentions a proportional bar is noise dressed as a
#: measurement — a "67% negative" derived from three rows is a false
#: statement. Under it the raw counts are printed instead.
PROPORTION_MIN_N = 5

#: And percentages are only printed at all from here up (UX-PLAN §5). Between
#: PROPORTION_MIN_N and this the bar is drawn — the *shape* of a mix is real
#: at n=8 — but it is labelled in counts, because "38%" of eight is not.
PERCENT_MIN_N = 20

#: The five sentiment values, in the one order every row uses. A fixed order is
#: what makes two rows comparable at a glance. "Couldn't tell" is last and is
#: drawn unfilled, so it can never be misread as an opinion.
SENTIMENT_ORDER: tuple[tuple[str, str], ...] = (
    ("positive", "Positive"),
    ("mixed", "Mixed"),
    ("neutral", "Neutral"),
    ("negative", "Negative"),
    ("unclear", "Couldn’t tell"),
)

#: The four things that can be true of a site in a sweep, in reading order.
#: Four *nominal* states, not an ordered ramp: "blocked us" is not more of
#: anything than "returned nothing", so charts.csv row 5's sequential colour
#: guidance is deliberately not applied (see COMPONENTS.md).
COVERAGE_STATES: tuple[tuple[str, str], ...] = (
    ("collected", "Returned rows"),
    ("empty", "Returned nothing"),
    ("blocked", "Blocked us"),
    ("not_tried", "Not tried"),
)


def _num(value: Any) -> float | None:
    """A number, or ``None`` — never a crash and never a silent zero.

    A zero and an absent value are different facts everywhere in this product,
    so a value that cannot be read as a number comes back as ``None`` and the
    caller renders the word, not the numeral.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(out) or math.isinf(out) else out


def _count_label(value: float | None) -> str:
    """A count with thousands separators, or the *word* for its absence.

    ux-guidelines row 86 asks for grouped thousands; this codebase's own rule
    asks that a null be a word and a zero a numeral. Both are settled here so
    no template has to remember either.
    """
    if value is None:
        return "not counted"
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}"


def _pct_of(part: float, whole: float) -> float:
    return 0.0 if whole <= 0 else round(100.0 * part / whole, 2)


def _plural(n: int, word: str, plural: str | None = None) -> str:
    return word if n == 1 else (plural or word + "s")


def _iso_day(value: Any) -> int | None:
    """An ISO date's day number, for spacing a series by real elapsed time.

    Returns ``None`` rather than raising on anything unparsable: a malformed
    stamp should cost the *spacing*, not the whole figure, and the caller
    falls back to even spacing and says so.
    """
    head = str(value or "")[:10]
    parts = head.split("-")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    try:
        return _date(int(parts[0]), int(parts[1]), int(parts[2])).toordinal()
    except ValueError:
        return None


def _short_date(value: Any) -> str:
    """`19 Aug` — the name of a sweep on screen.

    Deliberately without the year, because on screen the sweep axis carries
    only weeks and the year is noise. Anything that can reach paper uses
    :func:`fmt_date_long` instead, per ux-guidelines row 85: "19 Aug" on a
    page a client reads six months later is ambiguous.
    """
    head = str(value or "")[:10]
    parts = head.split("-")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return head or "undated"
    month = int(parts[1])
    if not 1 <= month <= 12:
        return head
    return f"{int(parts[2])} {_MONTHS[month - 1][:3]}"


# -------------------------------------------------------------- bar list --

def bar_rows(
    rows: Any,
    *,
    sort: bool = True,
    limit: int | None = None,
    unit: str = "mentions",
) -> list[dict[str, Any]]:
    """A ranked horizontal bar list: the shape for 3-15 named categories.

    charts.csv row 2 (*Compare Categories*) is unambiguous here — "always sort
    descending by value", never a pie — and quick-reference §10's
    `axis-readability` forbids rotated or truncated labels, which is what
    rules out the vertical bar its own threshold line would otherwise pick:
    theme names are long free text.

    Accepts either mappings (``label``, ``value``, and optionally ``href``,
    ``note``, ``emphasis``) or ``(label, value)`` pairs, and always returns the
    full key set:

    ``label`` ``value`` ``value_label`` ``pct`` ``share_pct`` ``href`` ``note``
    ``emphasis`` ``rank``

    ``pct`` is the bar's length — a share of the *largest* row, which is what
    makes a ranked list readable. ``share_pct`` is the share of the total, for
    a caller that wants to say "38% of everything collected"; the two are
    different questions and conflating them is a common defect.
    """
    items: list[dict[str, Any]] = []
    for raw in rows or ():
        if isinstance(raw, Mapping):
            label = str(raw.get("label", ""))
            value = _num(raw.get("value")) or 0.0
            href = str(raw.get("href") or "")
            note = str(raw.get("note") or "")
            emphasis = bool(raw.get("emphasis"))
        else:
            pair = list(raw)
            label = str(pair[0]) if pair else ""
            value = (_num(pair[1]) if len(pair) > 1 else 0.0) or 0.0
            href, note, emphasis = "", "", False
        items.append({
            "label": label, "value": value, "href": href,
            "note": note, "emphasis": emphasis,
        })
    if sort:
        items.sort(key=lambda r: (-r["value"], r["label"].lower()))
    if limit is not None:
        items = items[:limit]
    top = max((r["value"] for r in items), default=0.0)
    total = sum(r["value"] for r in items)
    for i, r in enumerate(items, start=1):
        r["rank"] = i
        r["pct"] = _pct_of(r["value"], top)
        r["share_pct"] = _pct_of(r["value"], total)
        r["value_label"] = _count_label(r["value"])
        r["unit"] = unit
    return items


# ------------------------------------------------------------- series ----

def series_points(
    points: Any,
    *,
    width: int = 150,
    height: int = 38,
    pad: int = 6,
    polyline_min: int = POLYLINE_MIN,
    unit: str = "mentions",
) -> dict[str, Any]:
    """A sweep series, spaced by the dates it actually happened on.

    Even spacing would misstate cadence: a topic swept on the 1st, the 8th and
    then not again until the 29th has a three-week hole in it, and that hole is
    information. So x is the real elapsed day count and a missed week reads as
    a gap.

    ``shape`` names what the caller must draw, and is the whole point of this
    function:

    ``empty``  nothing collected — the caller renders a named empty state
    ``dot``    one sweep: one dot carrying its own value. Not a trend
    ``pair``   two sweeps: two dots against a rule, never a connecting slope
    ``dots``   three sweeps: three dots, still no line
    ``line``   four or more: a polyline with every dot visible

    Input items are mappings with ``date`` and ``value``, optionally ``href``
    and ``label``. Anything whose date will not parse drops the whole series to
    index spacing and says so in ``spacing``.
    """
    parsed: list[dict[str, Any]] = []
    for raw in points or ():
        if isinstance(raw, Mapping):
            date = raw.get("date")
            value = _num(raw.get("value"))
            href = str(raw.get("href") or "")
        else:
            pair = list(raw)
            date = pair[0] if pair else None
            value = _num(pair[1]) if len(pair) > 1 else None
            href = ""
        parsed.append({
            "date": str(date or ""), "value": value or 0.0,
            "href": href, "day": _iso_day(date),
        })

    n = len(parsed)
    lo = min((p["value"] for p in parsed), default=0.0)
    hi = max((p["value"] for p in parsed), default=0.0)
    shape = (
        "empty" if n == 0 else
        "dot" if n == 1 else
        "pair" if n == 2 else
        "line" if n >= polyline_min else
        "dots"
    )
    baseline_y = float(height - pad)
    inner_w = float(width - 2 * pad)
    inner_h = float(height - 2 * pad)

    days = [p["day"] for p in parsed]
    # Three different reasons a series can end up evenly spaced, and only one
    # of them is a fallback worth confessing to the reader: a date that would
    # not parse. Two sweeps on the same day, or a single sweep, raise no
    # spacing question at all — reporting those as "a date could not be read"
    # was a false alarm on the commonest state this app has.
    date_failed = any(d is None for d in days)
    even = date_failed or (n > 1 and days[0] == days[-1])
    span_days = 0 if even or n < 2 else (days[-1] - days[0])
    if span_days <= 0:
        even = True

    span_value = (hi - lo) or 1.0
    out_points: list[dict[str, Any]] = []
    for i, p in enumerate(parsed):
        if n == 1:
            x = pad + inner_w / 2
        elif even:
            x = pad + inner_w * i / (n - 1)
        else:
            x = pad + inner_w * (p["day"] - days[0]) / span_days
        y = baseline_y - ((p["value"] - lo) / span_value) * inner_h
        out_points.append({
            "x": round(x, 2), "y": round(y, 2),
            "value": p["value"], "value_label": _count_label(p["value"]),
            "date": p["date"], "date_label": _short_date(p["date"]),
            "date_long": fmt_date_long(p["date"]),
            "href": p["href"], "is_last": i == n - 1, "index": i,
        })

    if shape == "empty":
        summary = f"No sweep has collected any {unit} yet."
    elif shape == "dot":
        one = out_points[0]
        summary = f"{one['value_label']} {unit} on {one['date_label']} — one sweep, so no trend yet."
    else:
        summary = (
            f"{n} sweeps, {_count_label(lo)} to {_count_label(hi)} {unit}; "
            f"{out_points[-1]['value_label']} on {out_points[-1]['date_label']}."
        )

    return {
        "shape": shape,
        "count": n,
        "width": width, "height": height, "pad": pad,
        "baseline_y": baseline_y,
        "points": out_points,
        "polyline": " ".join(f"{p['x']},{p['y']}" for p in out_points) if shape == "line" else "",
        "lo": lo, "hi": hi,
        "lo_label": _count_label(lo), "hi_label": _count_label(hi),
        "first_label": out_points[0]["date_label"] if out_points else "",
        "last_label": out_points[-1]["date_label"] if out_points else "",
        "latest": out_points[-1] if out_points else None,
        "spacing": (
            "index" if date_failed
            else "date" if not even
            else "even"
        ),
        "unit": unit,
        "summary": summary,
    }


# ----------------------------------------------------------- the gap -----

#: What to say when only one audience raised a theme. Never a status token and
#: never a zero: UX-PLAN §7.2 calls this the system's highest-risk null,
#: because a gap of zero and "nobody on that side said anything" look
#: identical and mean opposite things.
_ONLY_ONE_SIDE = {
    "clinicians": "Only clinicians discussed this",
    "patients": "Only patients discussed this",
    "neither": "Neither audience discussed this",
}


def gap_chart(rows: Any, *, domain: float = 1.0) -> dict[str, Any]:
    """Clinician tone against patient tone, on one shared −1…+1 axis.

    A dumbbell, because the connector's *length is the gap* — the most direct
    encoding of divergence there is, and it degrades honestly: when one
    audience did not speak there is one dot and no connector, so the row
    cannot be misread as agreement. charts.csv row 14 excludes a radar chart
    from exactly this case twice over ("values need precise comparison",
    "audience unfamiliar with radar"), and the recipient here is a commercial
    lead reading a printed page.

    Themes only one side raised are returned in ``single``, separately, so they
    can never be visually averaged into the comparison (UX-PLAN §7.2).

    Every row carries the same keys whichever list it lands in.
    """
    comparable: list[dict[str, Any]] = []
    single: list[dict[str, Any]] = []

    for raw in rows or ():
        if not isinstance(raw, Mapping):
            continue
        hcp = _num(raw.get("hcp_net"))
        patient = _num(raw.get("patient_net"))
        gap = _num(raw.get("divergence"))
        if gap is None and hcp is not None and patient is not None:
            gap = patient - hcp
        if hcp is not None and patient is not None:
            present = "both"
        elif hcp is not None:
            present = "clinicians"
        elif patient is not None:
            present = "patients"
        else:
            present = "neither"

        def _pct(v: float | None) -> float | None:
            if v is None:
                return None
            clamped = max(-domain, min(domain, v))
            return round((clamped + domain) / (2 * domain) * 100.0, 2)

        hcp_pct, patient_pct = _pct(hcp), _pct(patient)
        lo_pct = min(x for x in (hcp_pct, patient_pct) if x is not None) if present != "neither" else 50.0
        hi_pct = max(x for x in (hcp_pct, patient_pct) if x is not None) if present != "neither" else 50.0
        volume = int(_num(raw.get("volume")) or 0)
        sources = _num(raw.get("independent_sources"))
        comparable_row = present == "both" and gap is not None

        row = {
            "name": str(raw.get("name") or raw.get("theme_name") or ""),
            "volume": volume,
            "volume_label": _count_label(volume),
            "sources": None if sources is None else int(sources),
            "hcp": hcp, "patient": patient,
            "hcp_label": net_stance_short(hcp, "hcp"),
            "patient_label": net_stance_short(patient, "patient"),
            "hcp_pct": hcp_pct, "patient_pct": patient_pct,
            "gap": gap,
            "gap_label": "no comparison" if not comparable_row else f"{gap:+.2f}",
            "comparable": comparable_row,
            "present": present,
            "missing_label": "" if comparable_row else _ONLY_ONE_SIDE[present if present != "both" else "neither"],
            "reason": str(raw.get("reason") or ""),
            "left_pct": lo_pct,
            "width_pct": round(hi_pct - lo_pct, 2),
            "dot_pct": hcp_pct if hcp_pct is not None else (patient_pct if patient_pct is not None else 50.0),
            "tier": str(raw.get("tier") or ""),
        }
        row["summary"] = (
            f"{row['name']}: clinicians {row['hcp_label']}, patients "
            f"{row['patient_label']}, gap {row['gap_label']}."
            if comparable_row else
            f"{row['name']}: {row['missing_label'].lower()}, so there is no gap to measure."
        )
        (comparable if comparable_row else single).append(row)

    comparable.sort(key=lambda r: (-abs(r["gap"] or 0.0), r["name"].lower()))
    single.sort(key=lambda r: (-r["volume"], r["name"].lower()))
    widest = comparable[0] if comparable else None

    if widest is not None:
        summary = (
            f"Clinicians and patients read {widest['name']} most differently — "
            f"a gap of {widest['gap_label']} across {len(comparable)} comparable "
            f"{_plural(len(comparable), 'theme')}."
        )
    elif single:
        summary = (
            f"No theme can be compared: all {len(single)} were raised by one "
            "audience only, which is not agreement."
        )
    else:
        summary = "No theme has a tone reading for either audience yet."

    return {
        "rows": comparable,
        "single": single,
        "widest": widest,
        "count_comparable": len(comparable),
        "count_single": len(single),
        "total": len(comparable) + len(single),
        "domain": domain,
        "axis_low": "Patients more negative",
        "axis_mid": "No gap",
        "axis_high": "Clinicians more negative",
        "summary": summary,
    }


# --------------------------------------------------------- sentiment -----

def sentiment_mix(
    counts: Any,
    *,
    min_n: int = PROPORTION_MIN_N,
    percent_min_n: int = PERCENT_MIN_N,
) -> dict[str, Any]:
    """The five-way sentiment mix as a 100% stacked bar — or, below n=5, not.

    charts.csv row 3 rules out a pie or donut here on two counts at once
    ("accessibility-first context", "user needs precise values"); row 19 rules
    out a waffle in a per-theme row and names the escape itself — "for > 5
    categories switch to stacked 100% bar". At exactly five the stacked bar is
    the only shape that survives both.

    Two thresholds, and they are different questions. Under ``min_n`` the bar
    is not drawn at all, because a proportion of three rows is noise dressed as
    a measurement. Under ``percent_min_n`` the bar *is* drawn — the shape of a
    mix is real at n=8 — but it is labelled in counts, because "38%" of eight
    claims a precision the sample does not have.

    ``counts`` is a mapping of the internal stance keys to integers; anything
    missing is a zero, which is the one place in this codebase where that is
    the honest reading (nobody said it).
    """
    src = counts if isinstance(counts, Mapping) else {}
    segments: list[dict[str, Any]] = []
    total = 0
    for key, label in SENTIMENT_ORDER:
        value = int(_num(src.get(key)) or 0)
        total += value
        segments.append({"key": key, "label": label, "count": value})

    show_pct = total >= percent_min_n
    for seg in segments:
        seg["pct"] = _pct_of(seg["count"], total)
        seg["unfilled"] = seg["key"] == "unclear"
        seg["count_label"] = _count_label(seg["count"])
        # Whole percent, never a decimal: a tenth of a percentage point on a
        # sample of twenty-something is precision the sample cannot support,
        # and it is the difference between a figure a reader believes and one
        # they do not.
        seg["pct_label"] = f"{round(seg['pct'])}%"
        seg["value_label"] = seg["pct_label"] if show_pct else _count_label(seg["count"])

    read = [s for s in segments if s["key"] != "unclear"]
    top = max(read, key=lambda s: s["count"], default=None)
    if total == 0:
        summary = "No mention in this group could be read for sentiment."
    elif top is None or top["count"] == 0:
        summary = f"None of the {total} {_plural(total, 'mention')} could be read either way."
    elif show_pct:
        summary = (
            f"{top['label']} leads at {round(top['pct'])}% of {total} "
            f"{_plural(total, 'mention')}."
        )
    else:
        summary = (
            f"{top['label']} leads — {top['count']} of {total} "
            f"{_plural(total, 'mention')}."
        )

    return {
        "segments": segments,
        "n": total,
        "n_label": _count_label(total),
        "proportional": total >= min_n,
        "show_pct": show_pct,
        "min_n": min_n,
        "too_few_note": (
            f"{total} {_plural(total, 'mention')} — too few to draw as a "
            f"proportion, so the counts are printed instead."
        ),
        "summary": summary,
    }


# ---------------------------------------------------------- coverage -----

def coverage_grid(coverage: Any, *, known: Any = None) -> dict[str, Any]:
    """One cell per site: what each of ~40 sites actually did in this sweep.

    Four *nominal* states, so this is a categorical unit grid and not the
    sequential heat map charts.csv row 5 would otherwise suggest — "returned
    nothing" is not less of anything than "blocked us", and a blue-to-red ramp
    would imply an order that does not exist. Row 5's required fallback, a grid
    data table plus an intensity summary, still binds and the macro renders it.

    Three of the four states are also *named* below the strip, per UX-PLAN
    §7.5: a site that returned nothing, a site that refused us and a site
    nobody asked are three different facts and a shared silence hides two of
    them.
    """
    src = coverage if isinstance(coverage, Mapping) else {}

    def _list(key: str) -> list[str]:
        raw = src.get(key)
        return [str(v) for v in raw] if isinstance(raw, (list, tuple)) else []

    collected = _list("venues_collected")
    empty = _list("venues_empty")
    blocked = _list("venues_restricted")
    attempted = _list("venues_attempted")
    registry = [str(v) for v in known] if isinstance(known, (list, tuple)) else []

    seen = {*collected, *empty, *blocked, *attempted}
    not_tried = sorted(set(registry) - seen)

    by_state = {
        "collected": sorted(set(collected)),
        "empty": sorted(set(empty) - set(collected)),
        "blocked": sorted(set(blocked) - set(collected) - set(empty)),
        "not_tried": not_tried,
    }

    labels = dict(COVERAGE_STATES)
    cells: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    for key, label in COVERAGE_STATES:
        sites = by_state[key]
        states.append({
            "key": key, "label": label, "count": len(sites), "sites": sites,
            # The sites themselves, and the state as one countable phrase —
            # the second is what a screen-reader description joins on, so it
            # is built here rather than assembled inside a Jinja loop that
            # cannot tell which items it actually emitted.
            "named": ", ".join(sites),
            "named_count": f"{len(sites)} {label.lower()}",
        })
        for site in sites:
            cells.append({"site": site, "state": key, "state_label": label})

    total = len(cells)
    got = len(by_state["collected"])
    if total == 0:
        summary = "No site has been swept yet."
    else:
        summary = (
            f"{got} of {total} {_plural(total, 'site')} returned rows"
            + (f"; {len(by_state['empty'])} returned nothing" if by_state["empty"] else "")
            + (f"; {len(by_state['blocked'])} blocked us" if by_state["blocked"] else "")
            + "."
        )

    return {
        "cells": cells,
        "states": states,
        "counts": {s["key"]: s["count"] for s in states},
        "labels": labels,
        "total": total,
        "has_data": total > 0,
        "summary": summary,
    }


# ------------------------------------------------------------- meter -----

def meter(
    spent: Any,
    estimate: Any = None,
    cap: Any = None,
    *,
    stopped: bool = False,
    decimals: int = 2,
) -> dict[str, Any]:
    """Spend against a cap, as one bullet: fill spent, tick estimate, rule cap.

    charts.csv row 8 (*Performance vs Target*) allows exactly one metric per
    meter and requires "the number and target text beside the gauge" — this
    palette is monochrome, so the numbers are not a nicety, they are the only
    precise channel. "Stopped at the cap" becomes a *shape* (the fill
    terminating in a stop bar) rather than a status word, which is the cloud
    console convention and is what stops a successful partial from reading as
    a failure.
    """
    spent_v = _num(spent)
    est_v = _num(estimate)
    cap_v = _num(cap)
    scale = max([v for v in (spent_v, est_v, cap_v) if v is not None] or [0.0]) or 1.0

    over = bool(spent_v is not None and cap_v is not None and spent_v > cap_v + 1e-9)
    if stopped:
        state = "stopped"
    elif over:
        state = "over"
    else:
        state = "within"

    # A null is a word and a zero is a numeral — this codebase's one
    # non-negotiable rule. `usd(None)` gives an em dash, which reads as "not
    # applicable" when the fact is "we do not know what this cost".
    spent_label = "not recorded" if spent_v is None else usd(spent_v, decimals)
    parts = [f"Spent {spent_label}"]
    if est_v is not None:
        parts.append(f"estimated {usd(est_v, decimals)}")
    if cap_v is not None:
        parts.append(f"cap {usd(cap_v, decimals)}")
    summary = " · ".join(parts) + (
        " — stopped at the cap and kept what it collected." if stopped
        else " — over the cap." if over else "."
    )

    return {
        "spent": spent_v, "estimate": est_v, "cap": cap_v,
        "spent_label": spent_label,
        "estimate_label": "not estimated" if est_v is None else usd(est_v, decimals),
        "cap_label": "no cap set" if cap_v is None else usd(cap_v, decimals),
        "spent_pct": _pct_of(spent_v or 0.0, scale),
        "estimate_pct": None if est_v is None else _pct_of(est_v, scale),
        "cap_pct": None if cap_v is None else _pct_of(cap_v, scale),
        "has_estimate": est_v is not None,
        "has_cap": cap_v is not None,
        "stopped": bool(stopped),
        "over": over,
        "state": state,
        "summary": summary,
    }
