"""One error family, so a caller can catch the whole tool's failures.

Every error carries a ``rule`` naming the decision it enforces. When one of
these reaches a log, the reader should not have to open the source to find
out which rule fired.
"""

from __future__ import annotations

__all__ = [
    "VsmError",
    "ConfigError",
    "BudgetExceeded",
    "GuardViolation",
    "NoSuchTopic",
    "NoSuchRun",
]


class VsmError(Exception):
    """Base for everything this tool raises deliberately."""

    def __init__(self, message: str, *, rule: str = "") -> None:
        super().__init__(message)
        self.rule = rule


class ConfigError(VsmError):
    """The environment says something we cannot act on."""


class BudgetExceeded(VsmError):
    """A cap bound. Callers stop cleanly; they do not let this escape a run."""


class GuardViolation(VsmError):
    """A guard refused output. Never caught and softened — it blocks."""


class NoSuchTopic(VsmError):
    pass


class NoSuchRun(VsmError):
    pass
