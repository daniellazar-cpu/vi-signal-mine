"""Rung 7 — what changed that nobody asked about.

**Detection is arithmetic. Only the narration is model-written.** A threshold
crossing can be recomputed by anyone with the artifacts; a model's opinion that
something looks unusual cannot. Keeping the two apart is what lets the report
say "this doubled" and mean it.

The baseline is the **median** of a theme's volume across the previous three
snapshots. Median rather than mean because one freak week should not redefine
normal — and if it did, it would also mask the next real spike.

A spike must clear both a multiple and a floor. Doubling from one mention to two
is arithmetically a spike and substantively nothing, and a section full of
those teaches its reader to skip the section.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, replace
from typing import Any, Literal, Sequence

from vsm.llm.prompts import ANOMALY_NARRATION_SYSTEM
from vsm.llm.schema import ANOMALY_NARRATION_SCHEMA

__all__ = [
    "Anomaly", "AnomalyKind", "MIN_VOLUME", "SPIKE_MULTIPLE", "BASELINE_WINDOW",
    "median", "baseline_for", "detect_anomalies", "narrate",
]

AnomalyKind = Literal["theme_appeared", "theme_vanished", "volume_spike", "volume_collapse"]

#: How many prior snapshots define "normal".
BASELINE_WINDOW = 3
#: A spike is more than this multiple of the baseline...
SPIKE_MULTIPLE = 2.0
#: ...and at least this many signals. Below it, a multiple is noise.
MIN_VOLUME = 5


@dataclass(frozen=True)
class Anomaly:
    anomaly_id: str
    kind: AnomalyKind
    theme_name: str
    observed: int
    baseline: float | None
    detail: str
    #: model-written; empty until :func:`narrate` runs
    note: str = ""


def median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def baseline_for(theme_name: str, prior_snapshots: Sequence[Sequence[Any]]) -> float | None:
    window = list(prior_snapshots)[-BASELINE_WINDOW:]
    volumes = [
        next((t.volume for t in snapshot if t.name == theme_name), 0)
        for snapshot in window
    ]
    return median(volumes)


def detect_anomalies(
    current_themes: Sequence[Any], prior_snapshots: Sequence[Sequence[Any]]
) -> list[Anomaly]:
    if not prior_snapshots:
        # On a first snapshot everything is new. Saying so would be noise
        # dressed as insight.
        return []

    now = {t.name: t.volume for t in current_themes}
    seen_before = {t.name for snapshot in prior_snapshots for t in snapshot}
    found: list[Anomaly] = []
    counter = 0

    def _add(kind: AnomalyKind, name: str, observed: int, baseline: float | None, detail: str) -> None:
        nonlocal counter
        counter += 1
        found.append(Anomaly(f"anom-{counter:03d}", kind, name, observed, baseline, detail))

    for name in sorted(set(now) | seen_before):
        observed = now.get(name, 0)
        baseline = baseline_for(name, prior_snapshots)

        if name not in seen_before and observed >= MIN_VOLUME:
            _add("theme_appeared", name, observed, baseline,
                 f"{observed} signals, and the theme is absent from every prior snapshot")
            continue
        if name not in now and baseline and baseline >= MIN_VOLUME:
            _add("theme_vanished", name, 0, baseline,
                 f"baseline was {baseline:g}; this snapshot has none")
            continue
        if baseline and observed > baseline * SPIKE_MULTIPLE and observed >= MIN_VOLUME:
            _add("volume_spike", name, observed, baseline,
                 f"{observed} against a baseline of {baseline:g}")
        elif baseline and baseline >= MIN_VOLUME and observed * SPIKE_MULTIPLE < baseline:
            _add("volume_collapse", name, observed, baseline,
                 f"{observed} against a baseline of {baseline:g}")
    return found


def narrate(anomalies: Sequence[Anomaly], *, client: Any | None = None) -> list[Anomaly]:
    """Attach one sentence of explanation. Numbers are never re-derived here."""
    anomalies = list(anomalies)
    if client is None or not anomalies:
        return anomalies
    listing = "\n".join(
        f"- {a.anomaly_id} [{a.kind}] {a.theme_name}: {a.detail}" for a in anomalies
    )
    out = client.complete_structured(
        system=ANOMALY_NARRATION_SYSTEM,
        user=f"Explain what each detected change appears to mean.\n\n{listing}",
        schema=ANOMALY_NARRATION_SCHEMA,
        max_output_tokens=2048,
    )
    if not out.ok or not out.data:
        return anomalies
    notes = {str(n.get("anomaly_id")): str(n.get("note", "")) for n in out.data.get("notes", [])}
    return [replace(a, note=notes.get(a.anomaly_id, "")) for a in anomalies]
