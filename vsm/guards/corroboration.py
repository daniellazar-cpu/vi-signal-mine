"""G6 — an uncorroborated *claim* may not reach the report's main body.

This gates claims, not themes. A theme's volume, venue mix and kind mix are
counts — arithmetic over rows that are already in the ledger — and a count
needs no corroboration; it is what it is. What needs three independent
sources is an assertion *about* a theme ("tolerability is the dominant
concern"), because that is a claim someone could be wrong about, and Rung 4
exists to keep an unsupported claim out of the body. So this guard runs in
REPORT over the :class:`~vsm.analysis.corroborate.Finding` list the report
writes, never over the theme list :mod:`vsm.analysis.cluster` produces.

``emerging`` findings are publishable in a separately labelled section, because
two independent sources is a real if provisional observation. ``single_source``
never leaves the ledger: one source is an anecdote, and an anecdote printed in a
client report is indistinguishable from a finding.

Enforced here rather than in a prompt, because a rule stated only in a prompt is
an optimisation and never a control.
"""

from __future__ import annotations

from typing import Iterable

from vsm.errors import GuardViolation

__all__ = ["assert_body_is_corroborated", "BODY_TIERS"]

BODY_TIERS = frozenset({"corroborated"})


def assert_body_is_corroborated(findings: Iterable[object]) -> None:
    bad = [f for f in findings if getattr(f, "tier", None) not in BODY_TIERS]
    if bad:
        detail = ", ".join(
            f"{getattr(f, 'finding_id', '?')}={getattr(f, 'tier', '?')}" for f in bad
        )
        raise GuardViolation(
            f"findings below 'corroborated' cannot appear in the report body: {detail}",
            rule="G6",
        )
