"""G1 — a claim binds to ledger rows, or it does not get written.

Every field of a citation is rebuilt here from the signal row. A citation the
model produced is discarded even when it happens to be right, because the
point is not this citation's correctness — it is that no citation in the
document depends on the model having been honest.

The parent engine earned this rule the hard way: its scaffolding path once
minted PMIDs as ``30000000 + (seed % 9999999)`` with a matching PubMed URL,
plausible enough to survive review.

An unbindable id **blocks**. Dropping it instead would convert a fabricated
citation into a silently uncited claim — the same lie with fewer symptoms.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from vsm.errors import GuardViolation
from vsm.mining.venues import kind_of

__all__ = ["Citation", "bind_citations"]


@dataclass(frozen=True)
class Citation:
    signal_id: str
    url: str
    venue: str
    venue_kind: str
    captured_at: str
    collection_method: str


def bind_citations(
    signal_ids: Sequence[str], ledger: Mapping[str, Mapping[str, Any]]
) -> list[Citation]:
    if not signal_ids:
        raise GuardViolation(
            "G1: a claim was written with no signal ids to bind to", rule="G1"
        )
    missing = [sid for sid in signal_ids if sid not in ledger]
    if missing:
        raise GuardViolation(
            f"G1: claim cites signal ids that are not in the ledger: "
            f"{', '.join(missing)}",
            rule="G1",
        )
    out: list[Citation] = []
    for sid in signal_ids:
        row = ledger[sid]
        venue = str(row.get("venue") or "")
        out.append(
            Citation(
                signal_id=sid,
                url=str(row.get("url") or ""),
                venue=venue,
                venue_kind=kind_of(venue) or "unknown",
                captured_at=str(row.get("captured_at") or ""),
                collection_method=str(row.get("collection_method") or ""),
            )
        )
    return out
