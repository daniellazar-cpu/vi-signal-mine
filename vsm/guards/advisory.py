"""G2 — the report suggests. It does not decide.

The reader is a professional making a commercial judgement with context we do
not have. Telling them what to do is both presumptuous and, in a regulated
setting, a claim we are not positioned to make.

``BANNED_DIRECTIVES`` must equal ``vsm.llm.prompts.BANNED_DIRECTIVES``. A test
pins the equality, because a drifted pair means the model is being told a
different rule than the one that rejects its output — and then the rejection
looks like a bug rather than a boundary.
"""

from __future__ import annotations

import re

from vsm.errors import GuardViolation

__all__ = ["BANNED_DIRECTIVES", "assert_advisory"]

BANNED_DIRECTIVES: tuple[str, ...] = (
    "you should",
    "you must",
    "we recommend that you",
    "the right move is",
    "you need to",
    "the best option is",
)

_PATTERN = re.compile(
    "|".join(rf"(?<!\w){re.escape(p)}(?!\w)" for p in BANNED_DIRECTIVES),
    re.IGNORECASE,
)


def assert_advisory(text: str, *, where: str = "") -> None:
    found = sorted({m.group(0).lower() for m in _PATTERN.finditer(text or "")})
    if found:
        place = f" in {where}" if where else ""
        raise GuardViolation(
            f"G2: directive language{place}: {', '.join(found)}. "
            "This report suggests; it does not decide.",
            rule="G2",
        )
