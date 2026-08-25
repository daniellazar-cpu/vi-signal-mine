"""Cost + quota accounting for the mining layer (PRD §13.1).

Verified pricing, July 2026 (PRD §13.1, matching Bright Data's published ladder):

* SERP API — **$1.50 per 1,000** requests → ``$0.0015`` per request.
* Web Unlocker — **~$3 per 1,000 successful** responses → ``$0.003`` each.
  *Failures are not billed* in standard mode, so a failed call records
  ``billable=False`` and costs nothing.
* Discover — no separate published unit price; a Discover result carries a parsed
  page, so it is charged at the same ``$0.003`` per returned result the PRD uses
  for "intent discovery with parsed content". Flagged ``estimated=True`` on the
  call record so nobody mistakes it for a verified figure.
* Free tier — **5,000 results/month**. That is the number the runner's
  ``QuotaCaps.fetches_per_campaign`` already carries; it is re-stated here so the
  clients can stop cleanly even when no ledger was injected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

__all__ = [
    "SERP_COST_PER_REQUEST_USD",
    "UNLOCKER_COST_PER_SUCCESS_USD",
    "DISCOVER_COST_PER_RESULT_USD",
    "FREE_TIER_RESULTS_PER_MONTH",
    "FetchCall",
    "Budget",
    "BudgetStop",
]

SERP_COST_PER_REQUEST_USD = 0.0015
UNLOCKER_COST_PER_SUCCESS_USD = 0.003
DISCOVER_COST_PER_RESULT_USD = 0.003
FREE_TIER_RESULTS_PER_MONTH = 5000

CallKind = Literal["serp", "discover", "unlocker", "robots"]


#: Statuses that mean *we may be missing data we intended to collect*. ``blocked``
#: is deliberately not one of them: the site defeated the unlocker, which is an
#: expected outcome of asking, recorded and moved past. ``error`` is ours.
DATA_LOSS_STATUSES: frozenset[str] = frozenset({"error"})


@dataclass(frozen=True)
class FetchCall:
    """One billable (or refused) call — the row that lands in fetch provenance.

    ``product`` and ``url`` exist because the first live sweep produced a
    provenance block whose cost and status reconciled perfectly and whose record of
    *what was called* was null on every row. Cost without a target is an invoice,
    not provenance, so both are required here rather than optional:

    * ``product`` — ``serp`` / ``discover`` / ``unlocker`` / ``robots``. Defaults
      from ``kind``, which is the same vocabulary the clients publish.
    * ``url`` — the endpoint actually requested. For SERP that is the Google search
      URL including its parameters (which is where the recency window is visible);
      for Discover the API endpoint; for a page fetch the page. Truncated, never
      empty: a blank ``url`` raises rather than reaching an artifact.

    ``status="error"`` additionally requires a ``reason``. An error row with no
    reason is indistinguishable from lost data, which is the one thing fetch
    provenance may never be.
    """

    kind: CallKind
    target: str
    at: datetime
    status: str = "ok"
    results: int = 0
    cost_usd: float = 0.0
    billable: bool = True
    estimated: bool = False
    detail: str = ""
    #: the endpoint or page actually requested — required, see the class docstring
    url: str = ""
    #: ``serp`` / ``discover`` / ``unlocker`` / ``robots``; defaults from ``kind``
    product: str = ""
    #: why an ``error``/``blocked`` call did not produce data
    reason: str = ""
    #: HTTP status when there was one
    http_status: int | None = None

    #: how much of a URL is worth keeping in an artifact
    MAX_URL_CHARS = 300

    def __post_init__(self) -> None:
        if not self.product:
            object.__setattr__(self, "product", str(self.kind))
        url = (self.url or "").strip() or (self.target if "://" in (self.target or "") else "")
        if not url:
            raise ValueError(
                f"FetchCall(product={self.product!r}) has no url — a provenance row that does not "
                "say what was called is not provenance. Pass url=… (the endpoint requested)."
            )
        if len(url) > self.MAX_URL_CHARS:
            url = url[: self.MAX_URL_CHARS - 1] + "…"
        object.__setattr__(self, "url", url)
        if self.status in DATA_LOSS_STATUSES and not (self.reason or self.detail):
            raise ValueError(
                f"FetchCall(product={self.product!r}, status='error') carries no reason. An error "
                "with no reason cannot be told apart from silently lost data."
            )
        if not self.reason and self.detail and self.status != "ok":
            object.__setattr__(self, "reason", self.detail)

    @property
    def data_loss(self) -> bool:
        """``True`` when this call may have cost us signal we meant to collect."""
        return self.status in DATA_LOSS_STATUSES

    def as_dict(self) -> dict[str, Any]:
        return {
            "product": self.product,
            "url": self.url,
            "kind": self.kind,
            "target": self.target,
            "at": self.at.astimezone(timezone.utc).isoformat(),
            "status": self.status,
            "results": self.results,
            "cost_usd": round(self.cost_usd, 6),
            "billable": self.billable,
            "cost_estimated": self.estimated,
            "detail": self.detail,
            "error": self.reason if self.status != "ok" else "",
            "http_status": self.http_status,
            # blocked → expected, no data was ever available. error → ours, may be
            # missing signal. The two must never read the same in an audit.
            "data_loss": self.data_loss,
        }


class BudgetStop(Exception):
    """Internal signal: stop mining cleanly, do not overspend. Never escapes the package."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class Budget:
    """Counts results against the free-tier cap and, when present, the quota ledger.

    ``ledger`` is duck-typed on purpose — :class:`engine.orchestrator.runner.QuotaLedger`
    satisfies it, and importing the runner here would be a cycle. Anything with
    ``fetches``/``authorize_fetch``/``record_fetch`` works.
    """

    campaign_id: str
    result_cap: int = FREE_TIER_RESULTS_PER_MONTH
    ledger: Any = None
    account: str = "brightdata"
    calls: list[FetchCall] = field(default_factory=list)
    results_used: int = 0
    cost_usd: float = 0.0
    stopped_reason: str = ""

    def __post_init__(self) -> None:
        if self.ledger is not None:
            try:
                self.results_used = int(self.ledger.fetches(self.campaign_id))
            except Exception:  # pragma: no cover - a ledger without the accessor
                self.results_used = 0

    # ------------------------------------------------------------------ checks
    @property
    def remaining(self) -> int:
        return max(self.result_cap - self.results_used, 0)

    def check(self, units: int, *, what: str) -> None:
        """Raise :class:`BudgetStop` if ``units`` more results would breach a cap.

        Checks the local cap first, then asks the ledger (``dry_run``) so the
        ledger's own :class:`~engine.errors.QuotaExceeded` message is preserved.
        """
        if units <= 0:
            return
        if self.results_used + units > self.result_cap:
            raise BudgetStop(
                f"Bright Data free-tier cap: {self.results_used}+{units} results would exceed "
                f"{self.result_cap}/month — stopped before {what} (PRD §13.1)"
            )
        if self.ledger is not None:
            try:
                self.ledger.authorize_fetch(
                    campaign_id=self.campaign_id, units=units, account=self.account, dry_run=True
                )
            except Exception as exc:  # QuotaExceeded, or a ledger that refuses another way
                raise BudgetStop(f"quota ledger refused {units} results before {what}: {exc}") from exc

    # ----------------------------------------------------------------- records
    def record(self, call: FetchCall) -> FetchCall:
        """Book one completed call: cost, results consumed, ledger entry."""
        self.calls.append(call)
        if call.billable:
            self.cost_usd += call.cost_usd
        if call.results:
            self.results_used += call.results
            if self.ledger is not None:
                self.ledger.record_fetch(
                    campaign_id=self.campaign_id,
                    units=call.results,
                    at=call.at,
                    account=self.account,
                )
        return call

    def stop(self, reason: str) -> None:
        if not self.stopped_reason:
            self.stopped_reason = reason

    def as_provenance(self) -> dict[str, Any]:
        """The per-call provenance block for ``fetch_provenance.json``."""
        return {
            "account": self.account,
            "result_cap": self.result_cap,
            "results_used": self.results_used,
            "results_remaining": self.remaining,
            "cost_usd": round(self.cost_usd, 6),
            "stopped_reason": self.stopped_reason,
            "calls": [c.as_dict() for c in self.calls],
            # errors are pulled out rather than left for a reader to find among the
            # calls: an error means we may be missing signal, and "blocked" does not
            "errors": [
                {"product": c.product, "url": c.url, "reason": c.reason, "http_status": c.http_status}
                for c in self.calls
                if c.data_loss
            ],
            "blocked": [
                {"product": c.product, "url": c.url, "reason": c.reason}
                for c in self.calls
                if c.status == "blocked"
            ],
        }
