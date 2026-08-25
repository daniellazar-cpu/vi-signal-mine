"""G5 — no forecast, and no accuracy figure.

Spec D13. Competitors publish prediction accuracy because they re-check their
predictions monthly against what actually happened; that is what earns the
number. This tool measures the delta between two dated snapshots and stops
there, and this guard is what stops the prose quietly upgrading a measurement
into a projection.

Patterns are anchored to word boundaries. A guard that fires on "Willis"
because it contains "will" gets switched off within a week, and then it guards
nothing.
"""

from __future__ import annotations

import re

from vsm.errors import GuardViolation

__all__ = ["FORECAST_PATTERNS", "assert_no_unmeasured_claims"]

FORECAST_PATTERNS: tuple[str, ...] = (
    r"will\s+(?:grow|rise|increase|decline|fall|double|halve|continue|reach|become)",
    r"expected\s+to",
    r"projected",
    r"projection",
    r"forecast(?:ed|s)?\s+to",
    r"we\s+forecast",
    r"predicts?\b",
    r"prediction",
    r"\d+(?:\.\d+)?\s*%\s*accur",
    r"accuracy\s+of\s+\d+",
    r"likely\s+to\s+(?:grow|rise|increase|decline|fall|double)",
    r"over\s+the\s+(?:next|coming)\s+\w+\s+(?:months?|weeks?|quarters?)",
)

_PATTERN = re.compile("|".join(f"(?:{p})" for p in FORECAST_PATTERNS), re.IGNORECASE)


def assert_no_unmeasured_claims(text: str, *, where: str = "") -> None:
    found = sorted({m.group(0).lower() for m in _PATTERN.finditer(text or "")})
    if found:
        place = f" in {where}" if where else ""
        raise GuardViolation(
            f"G5: forecast or accuracy language{place}: {', '.join(found)}. "
            "This report describes measured movement between dated snapshots; "
            "it does not predict, and it quotes no accuracy figure it has not "
            "backtested.",
            rule="G5",
        )
