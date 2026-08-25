"""G4 — an optional per-run list of terms the output may never contain.

Empty by default and a no-op when empty: this is not a required guardrail, it
is a convenience for an operator who has a reason to keep a name out of a
document.

Whole-word matching only. A never-say list that fires on substrings makes
ordinary prose unwritable, and a guard people switch off protects nothing.
"""

from __future__ import annotations

import re
from typing import Sequence

from vsm.errors import GuardViolation

__all__ = ["assert_no_banned_terms"]


def assert_no_banned_terms(
    text: str, terms: Sequence[str], *, where: str = ""
) -> None:
    terms = [t for t in terms if t]
    if not terms:
        return
    pattern = re.compile(
        "|".join(rf"(?<!\w){re.escape(t)}(?!\w)" for t in terms), re.IGNORECASE
    )
    found = sorted({m.group(0) for m in pattern.finditer(text or "")})
    if found:
        place = f" in {where}" if where else ""
        raise GuardViolation(
            f"never-say terms present{place}: {', '.join(found)}", rule="G4"
        )
