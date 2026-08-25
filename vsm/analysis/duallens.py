"""The gap between what clinicians say and what patients say.

Two lenses over the same corpus; the delta is the output. A theme clinicians are
neutral about and patients are angry about is a different commercial problem
from the reverse, and a blended number shows neither.

``net_stance`` maps a stance histogram onto [-1, 1]. ``mixed`` and ``unclear``
contribute nothing to the numerator but stay in the denominator, so a theme the
classifier could not read comes out *near* zero rather than *at* zero — an
abstention dilutes a signal, it does not balance it.

A theme only one side discussed has ``divergence = None`` and a stated reason.
Silence is not agreement, and it is certainly not a gap of zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

__all__ = ["LensGap", "net_stance", "dual_lens"]

_WEIGHTS = {"positive": 1.0, "negative": -1.0, "mixed": 0.0, "neutral": 0.0, "unclear": 0.0}


@dataclass(frozen=True)
class LensGap:
    theme_id: str
    theme_name: str
    hcp: dict[str, int]
    patient: dict[str, int]
    hcp_net: float | None
    patient_net: float | None
    divergence: float | None
    reason: str = ""


def net_stance(counts: Mapping[str, int]) -> float | None:
    """[-1, 1], or ``None`` when nothing was classified at all."""
    total = sum(counts.values())
    if total == 0:
        return None
    numerator = sum(_WEIGHTS.get(stance, 0.0) * n for stance, n in counts.items())
    return round(numerator / total, 4)


def dual_lens(
    themes: Sequence[Any], stances: Sequence[Any]
) -> list[LensGap]:
    by_theme = {s.theme_id: s for s in stances}
    gaps: list[LensGap] = []
    for theme in themes:
        stance = by_theme.get(theme.theme_id)
        hcp = dict(stance.by_class.get("hcp", {})) if stance else {}
        patient = dict(stance.by_class.get("patient", {})) if stance else {}
        hcp_net, patient_net = net_stance(hcp), net_stance(patient)

        if hcp_net is None or patient_net is None:
            if hcp_net is None and patient_net is None:
                missing = "hcp-class or patient-class"
            elif patient_net is None:
                missing = "patient-class"
            else:
                missing = "hcp-class"
            divergence, reason = None, (
                f"no {missing} signal for this theme, so the two lenses "
                "cannot be compared; silence is not agreement"
            )
        else:
            divergence, reason = round(abs(hcp_net - patient_net), 4), ""

        gaps.append(
            LensGap(theme.theme_id, theme.name, hcp, patient, hcp_net, patient_net,
                    divergence, reason)
        )

    # Unmeasurable themes sort last rather than being dropped — a theme only one
    # side discusses is itself worth seeing.
    return sorted(gaps, key=lambda g: (g.divergence is None, -(g.divergence or 0.0)))
