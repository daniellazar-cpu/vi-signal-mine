"""Contrast as a *computed* property, not a grep.

The suite already checked that certain CSS text and HTML structure exist. That
cannot catch a colour token which is simply too light, and it did not: the
forest plot's small text — legend, axis ends, per-row signal counts, the
"Single source" tier label — was set to ``--vi-gray-500`` (``#797F88``), which
measures 4.03:1 on white against WCAG AA's 4.5:1 for text under 18px. Every one
of those labels is 10–12px.

The design system's own token file already says so, in a comment above
``--fg2``: gray-500 is for dividers and icons, ``#5F6570`` is for secondary
*text*. So this was the plot violating a rule the codebase had already written
down — which is exactly the kind of drift a test should hold, since the SVG is
reused verbatim as Figure 1 of the client report and the shortfall shipped in
the deliverable.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[1] / "vsm" / "ui" / "static"
_APP_CSS = _STATIC / "app.css"
_DS_CSS = _STATIC / "ds" / "colors_and_type.css"

#: Rules whose `fill` is small text drawn on the page background. Kept as an
#: explicit list rather than "every rule with a fill" so that adding a new
#: plot label is a deliberate decision to state its size here.
_PLOT_TEXT_RULES = {
    ".plot-legend-text": 10,
    ".plot-axis-end": 10,
    ".plot-theme-sub": 12,
    ".plot-tier-single_source": 12,
    ".plot-theme-name": 14,
    ".plot-num": 13,
    ".plot-tier": 12,
    ".plot-ne-label": 10,
}


def _tokens() -> dict[str, str]:
    """Every `--name: value` in both stylesheets, resolved through one level of
    `var(--other)` indirection, which is all the palette uses."""
    # Comments stripped FIRST. Prose naming a token — "…is --fg2, not
    # --vi-gray-500: at 10-12px…" — otherwise parses as a declaration and
    # shadows the real one. That happened: the reference-pair assertion below
    # started skipping on a non-hex "colour" that was actually comment text,
    # so the measurement silently stopped being checked at all.
    text = _DS_CSS.read_text() + "\n" + _APP_CSS.read_text()
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    raw = dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", text))
    out = {}
    for k, v in raw.items():
        v = v.strip()
        for _ in range(4):
            m = re.fullmatch(r"var\((--[\w-]+)\)", v)
            if not m:
                break
            v = raw.get(m.group(1), v).strip()
        out[k] = v
    return out


def _rgb(value: str) -> tuple[float, float, float]:
    v = value.strip()
    m = re.fullmatch(r"#([0-9a-fA-F]{6})", v)
    # Deliberately an assertion, not a skip. A skip here means "this colour was
    # never checked", which is indistinguishable from a pass in the summary
    # line — and that is precisely how the shortfall this module exists for went
    # unnoticed. Every fill in `_PLOT_TEXT_RULES` resolves to plain hex today;
    # if one legitimately becomes `currentColor`, handle it here explicitly.
    assert m, f"not a plain hex colour, so contrast was never measured: {value!r}"
    h = m.group(1)
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _luminance(value: str) -> float:
    def chan(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(c) for c in _rgb(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg: str, bg: str) -> float:
    a, b = _luminance(fg), _luminance(bg)
    lo, hi = sorted((a, b))
    return (hi + 0.05) / (lo + 0.05)


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _fill_of(selector: str, css: str) -> str:
    # Anchored so `.plot-tier` matches its own rule and not the shared
    # `.plot-legend-text, ..., .plot-tier { font-family: ... }` list, which
    # declares no fill and made this lookup silently pick the wrong block.
    m = re.search(r"(?:^|\n)\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"{selector} not found as its own rule in app.css"
    f = re.search(r"fill\s*:\s*([^;]+)", m.group(1))
    assert f, f"{selector} declares no fill"
    return f.group(1).strip()


def test_the_reference_pair_is_measured_correctly():
    """The measurement itself, pinned against two values the design system
    states in a comment. Without this, a bug in `contrast` could make every
    other test in this file pass vacuously."""
    tok = _tokens()
    assert contrast(tok["--vi-gray-500"], "#FFFFFF") == pytest.approx(4.03, abs=0.05)
    assert contrast(tok["--fg2"], "#FFFFFF") == pytest.approx(5.86, abs=0.05)


@pytest.mark.parametrize("selector,size", sorted(_PLOT_TEXT_RULES.items()))
def test_every_piece_of_plot_text_meets_aa_on_the_page_background(selector, size):
    css, tok = _strip_comments(_APP_CSS.read_text()), _tokens()
    fill = _fill_of(selector, css)
    m = re.fullmatch(r"var\((--[\w-]+)\)", fill)
    colour = tok[m.group(1)] if m else fill
    ratio = contrast(colour, tok["--bg"])
    required = 3.0 if size >= 18 else 4.5
    assert ratio >= required, (
        f"{selector} is {colour} at {size}px — {ratio:.2f}:1, needs {required}:1"
    )


def test_no_small_text_rule_reaches_for_the_divider_gray():
    """`--vi-gray-500` is legitimate for hairlines and icons. The guard is that
    it must not come back as a *text* fill in the plot, which is where it was."""
    css = _strip_comments(_APP_CSS.read_text())
    for selector in _PLOT_TEXT_RULES:
        assert "vi-gray-500" not in _fill_of(selector, css), (
            f"{selector} fills with the divider gray, which is 4.03:1 — use --fg2"
        )
