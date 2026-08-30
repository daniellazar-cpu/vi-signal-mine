"""Rung 6 — what is moving, measured against the previous snapshot.

**This is a delta, not a forecast** (spec D13). Competitors publish prediction
accuracy because they re-check their predictions every month against what
actually happened. Until Vi does the same, a projection here would be a number
with nothing behind it, and G5 rejects the language that would express one.

On a topic's first snapshot there is no baseline, and every comparison field is
``None`` with the reason stated. That is the parent engine's rule about never
inventing a number, applied to time.

A theme that appeared and a theme that vanished are both reported. Omitting the
vanished one would hide exactly the change worth seeing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

__all__ = ["ThemeMomentum", "momentum", "NO_BASELINE"]

NO_BASELINE = "no prior sweep"


@dataclass(frozen=True)
class ThemeMomentum:
    theme_name: str
    volume_now: int
    volume_prior: int | None
    delta: int | None
    #: ``None`` when the prior volume was zero — percentage growth from nothing
    #: is not a large number, it is an undefined one.
    delta_pct: float | None
    reason: str = ""


def _volumes(themes: Sequence[Any]) -> dict[str, int]:
    """Sum, don't overwrite. Two ``Theme`` objects sharing a name are two
    counted fragments of the same reported topic; keying a plain dict
    comprehension on the name would let the second silently discard the
    first one's signals. Silently dropping counted signals is worse than
    summing them."""
    totals: dict[str, int] = {}
    for t in themes:
        totals[t.name] = totals.get(t.name, 0) + t.volume
    return totals


def momentum(
    current_themes: Sequence[Any], prior_snapshots: Sequence[Sequence[Any]]
) -> list[ThemeMomentum]:
    now = _volumes(current_themes)

    if not prior_snapshots:
        return [
            ThemeMomentum(name, volume, None, None, None, NO_BASELINE)
            for name, volume in sorted(now.items())
        ]

    prior = _volumes(prior_snapshots[-1])  # oldest first, so the last is the latest
    results: list[ThemeMomentum] = []
    for name in sorted(set(now) | set(prior)):
        volume_now = now.get(name, 0)
        volume_prior = prior.get(name, 0)
        delta = volume_now - volume_prior
        if volume_prior == 0:
            results.append(
                ThemeMomentum(
                    name, volume_now, 0, delta, None,
                    "not present in the prior sweep, so growth has no base",
                )
            )
            continue
        results.append(
            ThemeMomentum(
                name, volume_now, volume_prior, delta,
                round(100.0 * delta / volume_prior, 2), "",
            )
        )
    return results
