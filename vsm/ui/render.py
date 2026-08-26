"""Drawing that has to happen in Python: the forest plot and the sparkline.

Both are inline SVG built from plain dicts and floats already computed by
``vsm.analysis`` — nothing here derives a new number, it only places numbers
that already exist. Every piece of dynamic text is escaped before it goes
into the markup, because a theme name can come from an LLM's naming pass (or,
offline, straight from a page title) and this string is trusted by the
browser as markup the moment the template marks it ``|safe``.

The forest plot is the direction contract's centrepiece (see
``.superpowers/sdd/2026-08-25-vi-signal-mine/DIRECTION.md``): box area is
volume, the whisker spans the signed gap between the patient and clinician
net-stance readings, and a null line at zero divergence is shared by every
row. A theme only one side discussed prints ``NE`` on that null line, in the
one colour this app reserves for exactly two things.
"""

from __future__ import annotations

import math
from html import escape
from typing import Any, Mapping, Sequence

from vsm.ui.content import TIERS

__all__ = ["forest_plot_svg", "sparkline_svg", "usd", "pct", "net_stance_text", "fmt_dt"]

# The closed, five-ink set named in DIRECTION.md. No sixth colour anywhere
# in generated SVG.
INK = "#14181B"
CYAN = "#8FC4D8"
BLUE = "#1B4E7E"
RED = "#B2372A"
GROUND = "#F2F4F3"

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
        f'stroke="{CYAN}" stroke-width="1" />'
        f'<polyline points="{points_attr}" fill="none" stroke="{BLUE}" '
        f'stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round" />'
        f'<circle cx="{last_x}" cy="{last_y}" r="2.2" fill="{BLUE}" />'
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
        f'stroke="{CYAN}" stroke-width="1.25" />'
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
                f'stroke="{RED}" stroke-width="2.25" stroke-dasharray="4,4" />'
                f'<rect x="{cx - side / 2:.1f}" y="{y - side / 2:.1f}" '
                f'width="{side:.1f}" height="{side:.1f}" fill="none" '
                f'stroke="{RED}" stroke-width="2.25" />'
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
                f'stroke="{BLUE}" stroke-width="2.75" />'
                f'<rect x="{x1 - side / 2:.1f}" y="{y - side / 2:.1f}" '
                f'width="{side:.1f}" height="{side:.1f}" fill="{BLUE}" '
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
        f'stroke="{CYAN}" stroke-width="1.25" />'
        f'<text x="{left_w}" y="{bottom_y + 22}" class="plot-axis-end">'
        f"PATIENTS MORE NEGATIVE</text>"
        f'<text x="{left_w + plot_w}" y="{bottom_y + 22}" text-anchor="end" '
        f'class="plot-axis-end">CLINICIANS MORE NEGATIVE</text>'
        f'<text x="{x_of(0):.1f}" y="{bottom_y + 42}" text-anchor="middle" '
        f'class="plot-axis-end">NO GAP</text>'
    )
    parts.append("</svg>")
    return "".join(parts)
