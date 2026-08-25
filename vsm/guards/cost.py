"""G3 — the estimate, and the cap that binds before anything is bought.

Prices are the parent engine's verified figures. A SERP request is $0.0015 and
a successful Web Unlocker page fetch is $0.03 — twenty times more. That ratio is
the entire cost argument for querying a curated venue list before the open web,
and it is why ``page_fetches_per_cluster`` is the knob that decides the bill.

The Bright Data account is shared with other Vi projects, so the cap is tight on
purpose. Raise it per run, knowingly; never by editing the default upward.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from vsm.errors import BudgetExceeded
from vsm.topics.model import SpendBand

__all__ = [
    "SERP_USD",
    "DISCOVER_USD",
    "UNLOCKER_USD",
    "MODEL_USD_PER_CLUSTER",
    "CostEstimate",
    "CostCap",
    "estimate_run_usd",
]

SERP_USD = 0.0015
DISCOVER_USD = 0.0015
UNLOCKER_USD = 0.03
#: Rough, and labelled as rough. A parent campaign ran ~$1 of model across far
#: more generation than a MINE lexicon call; this is deliberately generous so
#: the estimate shown to an operator is never an underestimate.
MODEL_USD_PER_CLUSTER = 0.05


@dataclass(frozen=True)
class CostEstimate:
    serp_usd: float
    discover_usd: float
    unlocker_usd: float
    model_usd: float
    breakdown: list[dict[str, Any]]

    @property
    def total_usd(self) -> float:
        return round(
            self.serp_usd + self.discover_usd + self.unlocker_usd + self.model_usd, 4
        )


def estimate_run_usd(band: SpendBand, *, cluster_count: int) -> CostEstimate:
    serp = band.queries_per_cluster * cluster_count * SERP_USD
    discover = band.discover_results_per_cluster * cluster_count * DISCOVER_USD
    unlocker = band.page_fetches_per_cluster * cluster_count * UNLOCKER_USD
    model = cluster_count * MODEL_USD_PER_CLUSTER
    return CostEstimate(
        serp_usd=round(serp, 4),
        discover_usd=round(discover, 4),
        unlocker_usd=round(unlocker, 4),
        model_usd=round(model, 4),
        breakdown=[
            {"item": "serp", "usd": round(serp, 4),
             "note": f"{band.queries_per_cluster} queries x {cluster_count} clusters"},
            {"item": "discover", "usd": round(discover, 4),
             "note": f"{band.discover_results_per_cluster} results x {cluster_count} clusters"},
            {"item": "unlocker", "usd": round(unlocker, 4),
             "note": f"{band.page_fetches_per_cluster} fetches x {cluster_count} clusters"},
            {"item": "model", "usd": round(model, 4), "note": "lexicon + naming, approximate"},
        ],
    )


@dataclass
class CostCap:
    """Refuses the spend that would breach, and stays truthful about the rest.

    A refused spend is **not** recorded. The ledger should say what was bought,
    and we did not buy the thing we declined to pay for.
    """

    cap_usd: float
    _spent: float = field(default=0.0, init=False)

    def spent(self) -> float:
        return round(self._spent, 6)

    def remaining(self) -> float:
        return round(max(0.0, self.cap_usd - self._spent), 6)

    def would_breach(self, amount: float) -> bool:
        return (self._spent + amount) > self.cap_usd + 1e-9

    def spend(self, amount: float) -> None:
        if self.would_breach(amount):
            raise BudgetExceeded(
                f"spending {amount:.4f} would pass the cap of {self.cap_usd:.2f} "
                f"(spent {self.spent():.4f})",
                rule="G3",
            )
        self._spent += amount
