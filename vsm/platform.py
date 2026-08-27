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

import base64
import hmac
import os
from typing import Any, Mapping

from vsm.backends.dburl import resolve_db_url
from vsm.errors import GuardViolation

__all__ = [
    "is_vercel",
    "production_is_safe",
    "vercel_env",
    "assert_serveable",
    "assert_band_allowed",
    "storage_is_durable",
    "StripFunctionPrefix",
    "RequireAccessKey",
]


def is_vercel(env: Mapping[str, str] | None = None) -> bool:
    """Are we running as a Vercel serverless function?

    Checks ``VERCEL_ENV`` as well as ``VERCEL``, and that is not belt-and-
    braces — it is the bug this signature exists to fix. **``VERCEL`` is set
    during the build but is not reliably present in the function's own
    runtime environment**, while ``VERCEL_ENV`` is. Keyed on ``VERCEL``
    alone, every guard downstream of this silently believed it was running
    locally: the read-only guard let a production deployment accept writes it
    could not keep, and the spend-band guard would have let a ``deep`` sweep
    start against a 60-second timeout.

    Proven on the deployment rather than assumed: ``assert_serveable`` fired
    its refusal there (so ``VERCEL_ENV`` was set), while
    ``storage_is_durable`` reported durable (so ``VERCEL`` was not).
    """
    env = env if env is not None else os.environ
    return bool(env.get("VERCEL_ENV", "").strip()) or env.get("VERCEL", "").strip() == "1"


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
    * **Something in front of it.** ``VSM_ACCESS_KEY`` set means every request
      must present that key over HTTP Basic — see :class:`RequireAccessKey`, and
      note that this branch was a lie until that class existed: the key was read
      here and nowhere else, so "the app gates itself" described a gate no code
      implemented. Live keys behind a shared secret that checked nothing is the
      exact combination this function exists to prevent.

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


def storage_is_durable(env: Mapping[str, str] | None = None) -> bool:
    """Would a write made on this request still be there for the next one?

    **True** whenever a database URL resolves (spec'd by
    :func:`vsm.backends.dburl.resolve_db_url`, the same function
    ``vsm.storage.open_stores`` itself defers to) — Postgres storage
    survives any request landing on any instance, container recycle or not.

    **Also true** whenever ``BLOB_READ_WRITE_TOKEN`` is set, the same name
    ``vsm.storage.open_stores`` checks to pick the Vercel Blob backend
    (``vsm/backends/vercel_blob.py``). A write there is an HTTP call to
    Vercel's own storage service, not a local file — it genuinely survives
    any instance the same way a database row does, so this is not a second,
    weaker notion of "durable"; it is the same one a database URL already
    satisfies, checked against a different name.

    **Also true** whenever this process is not running as a Vercel
    serverless function. SQLite+filesystem storage is genuinely durable
    there too: a local run is one long-lived process reading and writing the
    same directory on every request, nothing like the single invocation's
    own ``/tmp`` a Vercel function is handed — which belongs to that one
    invocation and is gone the moment the container is recycled (see
    ``vsm/storage.py``'s own docstring). A local install must be unaffected
    by this guard, and this is the check that makes that true without
    needing a database or a Blob token at all.

    **False** in exactly the one combination that cannot honour a write: no
    database configured, no Blob token configured, on the one platform where
    the filesystem underneath it does not survive between requests.

    ``env`` is injectable for tests, the same convention ``resolve_db_url``,
    ``open_stores`` and ``seed_demo_topic`` already use; every real caller
    leaves it at ``None`` and gets ``os.environ`` read fresh at call time, so
    a database or Blob token configured (or ``VERCEL`` set) after the
    process started is reflected on the very next call, never requiring a
    restart to notice.
    """
    env = env if env is not None else os.environ
    if resolve_db_url(env) is not None:
        return True
    if (env.get("BLOB_READ_WRITE_TOKEN") or "").strip():
        return True
    # Through `is_vercel` rather than reading `VERCEL` here: one definition of
    # "are we on Vercel", in one place. Two copies of that check is how this
    # guard came to trust a build-only variable and report a serverless
    # deployment as durable.
    return not is_vercel(env)


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

class RequireAccessKey:
    """HTTP Basic in front of the whole app when ``VSM_ACCESS_KEY`` is set.

    **This is the gate ``production_is_safe`` already claimed existed.** That
    function returned "an access key is set, so the app gates itself" and
    nothing anywhere checked a request against the key — it was read in exactly
    one place, to decide whether serving was *permitted*. So the combination the
    guard was built to make safe — live API keys behind a shared secret — put no
    secret in front of anything: any visitor with the URL could start sweeps
    that spend real money. The test named
    ``test_production_serves_when_an_access_key_gates_it`` asserted only that
    serving was allowed, which locked the hole in rather than catching it.

    Basic rather than a login form and a session: the app has no JavaScript, no
    session store, and no user model, and a shared secret has no account to
    belong to. The browser's own prompt needs none of that and survives a
    stateless serverless invocation, where a cookie signed with a per-container
    key would not.

    Any username is accepted; only the password is checked. The secret is
    shared, so inventing a username to go with it would be theatre — and a
    wrong username silently failing is worse to diagnose than one field.

    Compared with :func:`hmac.compare_digest`, so a wrong key cannot be
    recovered a character at a time from response timing.

    Applied at the ASGI layer, outside the router, so it covers every route,
    every static asset, and every 404 — a gate that only wraps the pages you
    remembered to decorate is not a gate.
    """

    def __init__(self, inner: Any, realm: str = "Vi Signal Mine") -> None:
        self._inner = inner
        self._realm = realm

    @staticmethod
    def _expected() -> str:
        # Read per request, not captured at construction: on a serverless host
        # the module may be imported before the environment is fully populated,
        # and a gate that cached an empty key would be permanently open.
        return os.environ.get("VSM_ACCESS_KEY", "").strip()

    @staticmethod
    def _offered(scope: Any) -> str | None:
        for name, value in scope.get("headers") or ():
            if name.lower() != b"authorization":
                continue
            try:
                kind, _, payload = value.decode("latin-1").partition(" ")
                if kind.lower() != "basic":
                    return None
                decoded = base64.b64decode(payload, validate=True).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                return None
            _user, sep, password = decoded.partition(":")
            return password if sep else None
        return None

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        expected = self._expected()
        if not expected or scope.get("type") != "http":
            await self._inner(scope, receive, send)
            return
        offered = self._offered(scope)
        if offered is not None and hmac.compare_digest(offered, expected):
            await self._inner(scope, receive, send)
            return
        body = (
            b"This instance is protected. Sign in with the access key as the "
            b"password; any username will do."
        )
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"www-authenticate",
                 f'Basic realm="{self._realm}", charset="UTF-8"'.encode("latin-1")),
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
                # Nothing behind this may be cached by a shared cache.
                (b"cache-control", b"no-store"),
            ],
        })
        await send({"type": "http.response.body", "body": body})

