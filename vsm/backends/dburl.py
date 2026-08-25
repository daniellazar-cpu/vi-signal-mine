"""Which database URL wins, and the scheme fix every provider's dashboard needs.

Vercel Postgres, Neon and Supabase each export a connection string under their
own environment variable name, and none of them is ours to invent. This reads
the three names a provider is likely to set, in the order that matters:

1. ``POSTGRES_URL_NON_POOLING`` — preferred. The pooled URL a provider also
   sets is PgBouncer running in transaction mode, which does not support
   prepared statements. That failure surfaces as a confusing runtime error
   from deep inside the driver, not as a clean failure at connect time, so the
   unpooled URL wins whenever both are present.
2. ``POSTGRES_URL`` — the pooled fallback, if that is all a provider gives.
3. ``DATABASE_URL`` — the generic name several providers also set.

Every provider's dashboard hands out ``postgres://``; every Python driver
wants ``postgresql://``. Rewriting the scheme here removes the trap once
rather than leaving it as a footnote every caller has to remember.

Returning ``None`` when nothing is configured is deliberate and is the whole
point of this module: the parent engine's version of this function fell back
to ``sqlite:////tmp/...`` here and lost a real visitor's consent record — the
write succeeded, every layer reported success, and the container holding the
row was destroyed once the invocation ended. ``None`` makes the absence of a
database a decision the caller has to make loudly (``open_stores`` logs it),
never a decision this module quietly makes for them.
"""

from __future__ import annotations

from typing import Mapping

__all__ = ["resolve_db_url"]

#: Order matters: the unpooled URL is preferred, see the module docstring.
_ENV_VARS = ("POSTGRES_URL_NON_POOLING", "POSTGRES_URL", "DATABASE_URL")

_OLD_SCHEME = "postgres://"
_NEW_SCHEME = "postgresql://"


def resolve_db_url(env: Mapping[str, str]) -> str | None:
    """The first configured URL among the recognised names, or ``None``."""
    for name in _ENV_VARS:
        value = env.get(name)
        if not value:
            continue
        if value.startswith(_OLD_SCHEME):
            value = _NEW_SCHEME + value[len(_OLD_SCHEME):]
        return value
    return None
