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
    "markdown_to_html",
    "markdown_inline_html",
    "markdown_sections",
    "markdown_paragraphs",
    "markdown_excerpt_html",
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

_TIER_LABEL = {
    "corroborated": "Corroborated",
    "emerging": "Emerging",
    "single_source": "Single source",
}
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


def net_stance_text(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}"


def fmt_dt(value: str | None) -> str:
    """A dated frame's label. Never guesses a format that doesn't parse."""
    if not value:
        return "undated"
    # Signals and runs both stamp ISO-8601. Slice rather than parse-and-
    # reformat: a malformed string still shows *something* instead of 500ing.
    return value[:16].replace("T", " ")


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
        f"DIVERGENCE — PATIENT MINUS CLINICIAN NET STANCE</text>"
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
    candidates = [(k, ls) for k, ls in blocks if ls]
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
