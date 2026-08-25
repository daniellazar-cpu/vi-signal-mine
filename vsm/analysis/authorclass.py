"""Who is speaking — the only place any pass is allowed to ask.

**v1 answers from the venue.** The gold-list registry already classifies every
domain by ``kind``, so "this came from an HCP-discussion venue" is computable
without resolving anybody's identity. That is a weaker claim than "a clinician
wrote this", and the difference is recorded rather than smoothed over.

**v2 will answer from identity.** The social-handle → NPI join against
Provider360 and the Pipl bridge is permitted (spec O2, answered 2026-08-25) and
is scoped as its own piece of work. When it lands it implements ``Resolver`` and
nothing downstream changes — asserted by a test that runs the consuming passes
against a stub identity resolver.

Two rules make the seam worth having:

* Consumers take an :class:`AuthorClass`, never a venue. ``stance`` and
  ``duallens`` must not be able to tell which resolver ran.
* ``basis`` travels into the report, always. "HCP" from a venue and "HCP" from
  an NPI are different claims, and printing them identically would overstate
  the weaker one — the same category of error as asserting a trust state you
  have not earned.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Protocol

from vsm.mining.venues import kind_of

__all__ = [
    "AuthorClass",
    "AuthorClassValue",
    "Resolver",
    "VenueResolver",
    "KIND_TO_CLASS",
]

AuthorClassValue = Literal["hcp", "patient", "institutional", "unknown"]

#: The registry has exactly six kinds. There is no ``press`` class because there
#: is no press kind — inventing one would mean inventing the venues to fill it.
KIND_TO_CLASS: dict[str, AuthorClassValue] = {
    "hcp_discussion": "hcp",
    "patient_community": "patient",
    "evidence": "institutional",
    "guideline_body": "institutional",
    "regulatory": "institutional",
    "drug_reference": "institutional",
}


@dataclass(frozen=True)
class AuthorClass:
    value: AuthorClassValue
    basis: Literal["venue", "identity"]
    confidence: float | None
    rationale: str
    #: Only ever set on an identity basis. A venue can never supply one.
    npi: str | None = None


class Resolver(Protocol):
    def resolve(self, signal: Mapping[str, Any]) -> AuthorClass: ...


class VenueResolver:
    """v1. Reads the registry's ``kind`` and says so."""

    basis = "venue"

    def resolve(self, signal: Mapping[str, Any]) -> AuthorClass:
        venue = str(signal.get("venue") or "")
        kind = kind_of(venue)
        value = KIND_TO_CLASS.get(kind)
        if value is None:
            return AuthorClass(
                value="unknown",
                basis="venue",
                confidence=None,
                rationale=(
                    f"{venue!r} is not in the registry, so its author class is "
                    "unknown; nothing is inferred from the URL or a username"
                ),
            )
        return AuthorClass(
            value=value,
            basis="venue",
            confidence=None,
            rationale=(
                f"venue {venue!r} is registered as {kind!r}; the class is derived "
                "from the venue, not from the identity of any author"
            ),
        )
