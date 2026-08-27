"""Vercel serverless entrypoint.

**Why this file exists at all.** Vercel's Python runtime discovers functions
by scanning the ``api/`` directory; it does not read an entrypoint out of
``pyproject.toml``. A ``[tool.vercel]`` table there would be inert — Vercel
never looks at it — so without a module here to invoke, the first deploy
would return ``FUNCTION_INVOCATION_FAILED``. ``vercel.json`` rewrites every
path to this one function, so this module is the whole surface (spec §11).

**What this deployment can and cannot do.** Read the spec's §11 before
assuming this is a general-purpose deployment of the tool. Only a ``probe``
MINE, a (resumable) INSIGHT and a REPORT fit inside a serverless function's
timeout — ``standard``/``deep`` sweeps do not, and ``vsm/platform.py``'s
``assert_band_allowed`` refuses them in code rather than leaving it to
whoever fills in the form. That guard, and ``assert_serveable`` (spec D15,
which refuses every route on a production Vercel deployment), both run
inside ``vsm/ui/app.py`` and ``vsm/modes/mine.py`` respectively — nothing
needs repeating here.
"""

from __future__ import annotations

import logging
import os

# Set before importing vsm.app below, which builds the app (and its stores)
# at import time via `vsm.config.get_settings()`. `/tmp` is the only writable
# path on Vercel. `vercel.json` already sets this in its own `env` block; the
# `setdefault` here is a second, deliberately redundant guarantee — a value
# configured in the Vercel dashboard always wins, and the app is never left
# pointed at a directory (e.g. the default `var/`, inside the read-only
# function bundle) it cannot write to, on any code path that reaches this
# file.
os.environ.setdefault("VSM_VAR_DIR", "/tmp/vsm-var")

# Vercel captures stdout/stderr, but nothing configures a logging handler by
# default. Without one, `vsm.storage.open_stores`'s own INFO log — which
# backend it picked, and the consequence of that choice — is silently
# discarded, which is exactly the failure spec §11 records: "the one signal
# saying your writes are being lost was discarded because no handler was
# configured." Configuring it here, once, before anything else logs, is what
# keeps that signal from repeating on this platform.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

from vsm.app import app as _vsm_app  # noqa: E402 — after the env/logging setup above
from vsm.platform import RequireAccessKey, StripFunctionPrefix  # noqa: E402

#: `vercel.json`'s rewrite carries the capture group (`destination:
#: "/api/index/$1"`); without it every path collapses to the one literal
#: destination and the app serves its own styled 404 for every URL — running,
#: and serving nothing. `StripFunctionPrefix` (in `vsm/platform.py`, where it
#: is unit-tested directly) puts the path back the way the app's own router
#: expects to see it, as an ASGI wrapper rather than `root_path` — `root_path`
#: would also shift URL *generation*, putting `/api/index` into every link
#: and form action this app emits.
# The gate goes *outside* the prefix stripper, so an unauthenticated
# request is refused before any routing decision is made about it.
# Inert unless VSM_ACCESS_KEY is set.
app = RequireAccessKey(StripFunctionPrefix(_vsm_app))

__all__ = ["app"]
