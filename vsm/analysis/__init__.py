"""Analysis passes over mined signals — and the seam they answer identity through.

:mod:`vsm.analysis.authorclass` is the only place any pass is allowed to ask
who is speaking. See its module docstring for why that is a seam rather than
a comment.
"""

from __future__ import annotations

from vsm.analysis.authorclass import (
    KIND_TO_CLASS,
    AuthorClass,
    AuthorClassValue,
    Resolver,
    VenueResolver,
)

__all__ = [
    "AuthorClass",
    "AuthorClassValue",
    "Resolver",
    "VenueResolver",
    "KIND_TO_CLASS",
]
