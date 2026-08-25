"""Rung 5 — what is being discussed, grouped and named.

The model proposes the grouping and writes the names, because that is a reading
task. Every *number* on a theme is counted here from the signal rows: volume,
venue mix, kind mix. A model-supplied count is discarded even when it is right,
because a number nobody can reproduce cannot go in a client report.

Offline the pass groups on the ``theme`` field the miner already derived from
each page title, which keeps it demonstrable under ``VSM_MINER=fake``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from vsm.llm.prompts import CLUSTER_SYSTEM
from vsm.llm.schema import THEMES_SCHEMA
from vsm.mining.venues import kind_of

__all__ = ["Theme", "cluster_themes", "venue_mix_for", "kind_mix_for"]


@dataclass(frozen=True)
class Theme:
    theme_id: str
    name: str
    signal_ids: tuple[str, ...]
    volume: int
    venue_mix: dict[str, int]
    kind_mix: dict[str, int]


def venue_mix_for(signals: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(s.get("venue") or "") for s in signals))


def kind_mix_for(signals: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Venue kinds, straight from the registry. An unregistered venue counts as
    ``unknown`` rather than being assigned a plausible kind."""
    return dict(Counter(kind_of(str(s.get("venue") or "")) or "unknown" for s in signals))


def _theme(theme_id: str, name: str, rows: Sequence[Mapping[str, Any]]) -> Theme:
    return Theme(
        theme_id=theme_id,
        name=name,
        signal_ids=tuple(str(r["signal_id"]) for r in rows),
        volume=len(rows),
        venue_mix=venue_mix_for(rows),
        kind_mix=kind_mix_for(rows),
    )


def _offline(signals: Sequence[Mapping[str, Any]]) -> list[Theme]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for signal in signals:
        grouped.setdefault(str(signal.get("theme") or "unlabelled"), []).append(signal)
    return [
        _theme(f"th-{i:03d}", name, rows)
        for i, (name, rows) in enumerate(sorted(grouped.items()), start=1)
    ]


def cluster_themes(
    signals: Sequence[Mapping[str, Any]], *, client: Any | None = None
) -> list[Theme]:
    if client is None or not signals:
        return _offline(signals)

    by_id = {str(s["signal_id"]): s for s in signals}
    listing = "\n".join(
        f"- {sid}: {str(s.get('theme') or s.get('title') or '')[:160]}"
        for sid, s in by_id.items()
    )
    out = client.complete_structured(
        system=CLUSTER_SYSTEM,
        user=f"Group these signals into themes and name each theme.\n\n{listing}",
        schema=THEMES_SCHEMA,
        max_output_tokens=4096,
    )
    if not out.ok or not out.data:
        return _offline(signals)

    themes: list[Theme] = []
    for index, proposed in enumerate(out.data.get("themes", []), start=1):
        # An id the model invented cannot conjure a signal into the ledger.
        rows = [by_id[sid] for sid in proposed.get("signal_ids", []) if sid in by_id]
        if not rows:
            continue
        themes.append(
            _theme(
                str(proposed.get("theme_id") or f"th-{index:03d}"),
                str(proposed.get("name") or "unnamed"),
                rows,
            )
        )
    return themes or _offline(signals)
