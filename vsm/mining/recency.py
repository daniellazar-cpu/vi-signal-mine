"""How recent is recent — and, more importantly, **what recency must never touch**.

The owner's ask: *"recency of the data, and it should be up to 90+ days."*

Applied as a blanket filter that instruction deletes the evidence base. The current
AGA opioid-induced-constipation guideline is from 2019 and is *the current edition*;
Cochrane reviews and pivotal trials are older still. A 90-day cutoff would throw all
of them away and keep last week's forum chatter. So the window is split by venue
kind, not applied to the sweep:

* **Date-restricted** — ``hcp_discussion`` and ``patient_community`` (which includes
  the trade press). Here staleness is real: a 2019 Reddit thread about a drug is not
  current practice signal.
* **Never date-restricted** — ``evidence``, ``guideline_body``, ``regulatory``,
  ``drug_reference``. For these the test is **current edition, not recent date**,
  which is already the repo's rule. Where a superseded edition is cheaply
  detectable, :func:`supersession_flag` flags it; nothing is dropped for age.

The window is expressed as a Google custom date range on the SERP URL
(``tbs=cdr:1,cd_min:MM/DD/YYYY,cd_max:MM/DD/YYYY``) rather than ``qdr:m``, so the
boundary is exact, auditable, and identical on a re-run — ``qdr:m`` is
"approximately a month ago" and cannot be reconciled against anything.

90 days is the **floor**, not the ceiling: ``window_days`` widens freely.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping

from vsm.mining.venues import EVERGREEN_KINDS, RECENCY_FILTERED_KINDS

__all__ = [
    "DEFAULT_RECENCY_DAYS",
    "RecencyWindow",
    "window_for",
    "google_tbs",
    "parse_posted_at",
    "supersession_flag",
]

#: The floor the owner named. A campaign may widen it; nothing narrows it silently.
DEFAULT_RECENCY_DAYS = 90


@dataclass(frozen=True)
class RecencyWindow:
    """The applied window, in the form a reader can check."""

    days: int
    since: date
    until: date
    applies_to_kinds: tuple[str, ...] = tuple(sorted(RECENCY_FILTERED_KINDS))
    exempt_kinds: tuple[str, ...] = tuple(sorted(EVERGREEN_KINDS))

    @property
    def tbs(self) -> str:
        return google_tbs(self.since, self.until)

    def applies_to(self, kind: str) -> bool:
        return kind in self.applies_to_kinds

    def as_dict(self) -> dict[str, Any]:
        return {
            "window_days": self.days,
            "since": self.since.isoformat(),
            "until": self.until.isoformat(),
            "google_tbs": self.tbs,
            "date_restricted_kinds": list(self.applies_to_kinds),
            "never_date_restricted_kinds": list(self.exempt_kinds),
            "rule": (
                "discussion and community venues are restricted to the window; evidence, "
                "guideline, regulatory and drug-reference venues are not date-filtered at all — "
                "for those the test is current edition, not recent date"
            ),
        }


def window_for(now: datetime, days: int = DEFAULT_RECENCY_DAYS) -> RecencyWindow:
    """The window ending today. ``days`` below the 90-day floor is raised to it."""
    span = max(int(days), DEFAULT_RECENCY_DAYS)
    until = now.astimezone(timezone.utc).date()
    return RecencyWindow(days=span, since=until - timedelta(days=span), until=until)


def google_tbs(since: date, until: date) -> str:
    """``cdr:1,cd_min:MM/DD/YYYY,cd_max:MM/DD/YYYY`` — an exact, auditable range."""
    fmt = "%m/%d/%Y"
    return f"cdr:1,cd_min:{since.strftime(fmt)},cd_max:{until.strftime(fmt)}"


_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_TEXT_DATE = re.compile(
    r"\b(\d{1,2})?\s*([a-z]{3,9})\.?\s+(\d{1,2})?,?\s*(\d{4})\b", re.IGNORECASE
)


def parse_posted_at(raw: Any) -> str | None:
    """An absolute date the venue actually exposed → ISO date. Otherwise ``None``.

    Deliberately narrow. ``"3 days ago"`` is Google's rendering at the moment it
    answered, not a date the venue published, so it is refused — PRD §5.3 says do
    not guess, and a computed relative date presented as a fact is a guess with a
    timestamp on it.
    """
    text = str(raw or "").strip()
    if not text:
        return None
    iso = _ISO.match(text)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3))).isoformat()
        except ValueError:
            return None
    match = _TEXT_DATE.search(text)
    if not match:
        return None
    lead, month_word, trail, year = match.groups()
    month = _MONTHS.get(month_word[:3].lower())
    if month is None:
        return None
    day_raw = lead or trail
    try:
        return date(int(year), month, int(day_raw) if day_raw else 1).isoformat()
    except ValueError:
        return None


_SUPERSEDED = (
    "this guideline has been superseded",
    "superseded by",
    "withdrawn guideline",
    "this guidance has been updated",
    "replaced by the",
    "no longer current",
    "archived guideline",
    "retired guideline",
)


def supersession_flag(text: str | None, *, title: str = "") -> str:
    """A cheap, honest supersession check for evergreen venues. ``""`` when clean.

    This is a *flag*, never a filter: an old edition still tells us the question was
    contested, and a false positive must not delete a guideline. Nothing here infers
    supersession from a date.
    """
    haystack = f"{title} {(text or '')[:4000]}".lower()
    for phrase in _SUPERSEDED:
        if phrase in haystack:
            return f"page says {phrase!r} — check the issuing body for the current edition"
    return ""


def kind_is_date_filtered(kind: str, mapping: Mapping[str, Any] | None = None) -> bool:
    """``True`` when the recency window applies to this venue kind."""
    return kind in RECENCY_FILTERED_KINDS
