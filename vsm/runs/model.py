"""A run, and the five states it can end in.

``stopped_on_budget`` is a distinct terminal state, not a flavour of failure. A
cap breach produces partial rows and a recorded deferral by design; conflating
it with ``failed`` would lose the difference between "we stopped paying" and
"it broke", which is the first question anyone asks of a short run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["Run", "RunMode", "RunStatus", "RUN_MODES"]

RunMode = Literal["mine", "insight", "report"]
RunStatus = Literal["pending", "running", "complete", "failed", "stopped_on_budget"]

RUN_MODES: tuple[str, ...] = ("mine", "insight", "report")


@dataclass(frozen=True)
class Run:
    run_id: str
    topic_id: str
    mode: RunMode
    status: RunStatus
    started_at: str
    finished_at: str | None = None
    cost_usd: float = 0.0
    #: the run this one consumed — an INSIGHT's snapshot, a REPORT's insight
    parent_run_id: str | None = None
    note: str = ""
