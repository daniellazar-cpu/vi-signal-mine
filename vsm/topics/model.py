"""What a topic is, and how much a sweep of it is allowed to buy.

A topic persists across runs. That is not a convenience — momentum and anomaly
are deltas, and a delta needs a baseline, so the unit that carries history has
to outlive a single run.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Topic", "SpendBand", "BANDS", "band_for"]


@dataclass(frozen=True)
class SpendBand:
    """One preset of the four knobs that decide what a sweep costs.

    A preset rather than a dollar target: the knobs interact, and "spend $2"
    gives an operator no guidance on which of the four to move. Each band shows
    its estimated cost on the form instead.
    """

    name: str
    queries_per_cluster: int
    serp_results_per_query: int
    discover_results_per_cluster: int
    #: Web Unlocker page fetches. A fetch is $0.03 against a SERP call's
    #: $0.0015 — twenty times more — so this is the knob that decides the bill.
    page_fetches_per_cluster: int


BANDS: dict[str, SpendBand] = {
    # Is there any conversation here at all? Search metadata only, no page reads.
    "probe": SpendBand("probe", 2, 10, 5, 0),
    "standard": SpendBand("standard", 4, 10, 10, 3),
    "deep": SpendBand("deep", 8, 20, 20, 6),
}


def band_for(name: str) -> SpendBand:
    return BANDS[name]


@dataclass(frozen=True)
class Topic:
    """A thing we watch. Its MINE runs are dated snapshots of it."""

    topic_id: str
    name: str
    therapeutic_area: str
    spend_band: str
    created_at: str
    brand: str | None = None
    molecule: str | None = None
    competitors: tuple[str, ...] = ()
    questions: tuple[str, ...] = ()
    #: G4. Terms the report may never contain. Empty is a no-op.
    never_say: tuple[str, ...] = ()

    def band(self) -> SpendBand:
        return band_for(self.spend_band)
