"""Where the app is running, and what that forbids (spec §11, D14, D15).

Both guards key off Vercel's own environment variables rather than a setting
this app invents, because whether a process is actually running on Vercel is
a question only the platform itself can answer honestly:

- ``VERCEL`` is set to ``"1"`` on every Vercel deployment — preview and
  production alike.
- ``VERCEL_ENV`` distinguishes which: ``"production"``, ``"preview"``, or
  ``"development"``.

Both guards are meant to run where nothing can route around them.
``assert_serveable`` is wired as ASGI middleware in ``vsm/ui/app.py`` rather
than a per-route dependency, because a per-route guard is a guard with an
exempt route by construction the moment someone adds a new one and forgets
it. ``assert_band_allowed`` runs inside ``run_mine`` itself, before the
estimate — not in the UI layer that calls it — because ``run_mine`` is the
one chokepoint every caller (the web form today, a script tomorrow) already
goes through.
"""

from __future__ import annotations

import os
from typing import Any

from vsm.errors import GuardViolation

__all__ = [
    "is_vercel",
    "production_is_safe",
    "vercel_env",
    "assert_serveable",
    "assert_band_allowed",
    "StripFunctionPrefix",
]


def is_vercel() -> bool:
    return os.environ.get("VERCEL", "").strip() == "1"


def vercel_env() -> str | None:
    return os.environ.get("VERCEL_ENV") or None


def production_is_safe() -> tuple[bool, str]:
    """May a production deployment serve, and on what grounds?

    Returns ``(allowed, reason)``. The reason travels either way, because "why
    is this page dead" and "why is this page open" are both questions someone
    asks in a hurry.

    **What this guard actually protects.** Vercel's own gating covers preview
    deployments only on this plan, so a production URL is reachable by anyone
    holding it. What makes that dangerous is not the URL — it is the live API
    keys behind it, which can spend real money. So the question is not "is this
    production?" but "is there anything here worth protecting?", and there are
    two honest ways for the answer to be no:

    * **Nothing to spend.** With ``VSM_OFFLINE=1`` no outbound call is possible
      from any code path, so there is no key to abuse and no budget to drain.
      A visitor gets a working but inert instance. This is the state a fresh
      deployment is in before anyone adds secrets, which is why it can be
      clicked through immediately.
    * **Something in front of it.** ``VSM_ACCESS_KEY`` set means the app gates
      itself, so live keys sit behind a shared secret rather than behind
      nothing.

    Live keys with no gate is the single combination that refuses — the actual
    danger, stated precisely instead of approximated by "is this production".
    Fails closed: offline off and no access key is a refusal, never a
    default-allow.
    """
    from vsm.config import get_settings

    if os.environ.get("VSM_ACCESS_KEY", "").strip():
        return True, "an access key is set, so the app gates itself"
    if get_settings(refresh=True).offline:
        return (
            True,
            "VSM_OFFLINE=1, so no outbound call is possible and there is no "
            "key to abuse or budget to drain",
        )
    return False, "live API keys are configured and nothing gates this deployment"


def assert_serveable() -> None:
    """Spec D15. Refuses a production deployment that has something to lose.

    Not every production deployment — see :func:`production_is_safe`. The
    first version of this guard refused *all* production traffic. That was a
    fair reading of the decision and wrong in practice: it made the URL a
    person naturally lands on permanently dead, which reads as a broken
    deployment rather than a protected one, and it pushed every visit onto a
    preview URL that changes with every deploy.
    """
    if vercel_env() != "production":
        return
    allowed, reason = production_is_safe()
    if allowed:
        return
    raise GuardViolation(
        f"this production deployment refuses to serve, because {reason}. On "
        "this plan Vercel gates preview deployments only, so a production URL "
        "is reachable by anyone who has it. Either set VSM_ACCESS_KEY to put a "
        "shared secret in front of the app, or set VSM_OFFLINE=1 to make it "
        "inert and unable to spend anything.",
        rule="D15",
    )


def assert_band_allowed(band: str) -> None:
    """Spec D14. Only the ``probe`` band may run on Vercel.

    ``standard`` and ``deep`` add page fetches and a wider sweep that does
    not reliably fit inside a serverless function's timeout. A sweep that
    dies partway through is not merely a failed run: it leaves a
    half-written snapshot on disk that a later momentum pass has no way to
    tell apart from a genuine, complete baseline — worse than refusing to
    start. Run a ``standard`` or ``deep`` sweep locally instead, where there
    is no timeout to race.
    """
    if is_vercel() and band != "probe":
        raise GuardViolation(
            f"the {band!r} spend band does not fit inside a Vercel "
            "function's timeout — only 'probe' runs here. Run this topic's "
            f"{band!r} sweep locally instead, where there is no timeout to race.",
            rule="D14",
        )


#: The path prefix Vercel's rewrite prepends. `vercel.json` rewrites `/(.*)`
#: to `/api/index/$1`, so a request for `/topics/new` arrives at `api/index.py`
#: as `/api/index/topics/new`.
FUNCTION_PREFIX = "/api/index"


class StripFunctionPrefix:
    """Serve the app at ``/``, however the platform addressed the function.

    **The bug this exists to prevent, because it is not obvious from a stack
    trace.** A rewrite destination of ``/api/index`` with the capture group
    left off collapses every path to that one literal destination: ``/``,
    ``/topics/new`` and ``/runs/abc/report`` would all arrive here as
    ``/api/index``, match no route, and get the app's own styled 404 —
    clearly running, and serving nothing. ``vercel.json``'s destination
    carries ``$1`` to avoid exactly that; this class strips the prefix back
    off so the app's own router sees the path it would see locally.

    Written as a plain ASGI wrapper rather than passed as ``root_path``,
    because ``root_path`` also shifts URL *generation*: every link, form
    action and redirect this app emits would gain an ``/api/index`` prefix,
    and the deployment would work while every URL it produced was wrong.

    Tolerant of an unprefixed path on purpose: if Vercel's framework
    detection ever routes to the function directly with no rewrite in
    force, the request passes through unchanged rather than breaking
    either way. Lives here rather than inline in ``api/index.py`` so it can
    be unit-tested directly — importing ``api/index.py`` itself runs its
    module-level environment and logging setup, which a test has no reason
    to trigger just to check this one piece of routing logic.
    """

    def __init__(self, inner: Any, prefix: str = FUNCTION_PREFIX) -> None:
        self._inner = inner
        self._prefix = prefix

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") in {"http", "websocket"}:
            path = scope.get("path") or "/"
            if path == self._prefix or path.startswith(self._prefix + "/"):
                stripped = path[len(self._prefix):] or "/"
                # A copy: the platform may reuse the scope dict, and mutating
                # a caller's scope to fix our own routing is a side effect
                # nobody reading this call site would expect.
                scope = {**scope, "path": stripped, "raw_path": stripped.encode()}
        await self._inner(scope, receive, send)
