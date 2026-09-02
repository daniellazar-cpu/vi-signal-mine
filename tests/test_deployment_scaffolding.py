"""The deployment files have to stay true, and only a test can keep them true.

Deliberately no actual Vercel build here — these are text assertions about
``vercel.json`` and ``.vercelignore``, so they run in the same fraction of a
second as everything else. What they catch is a class of failure a build
does not: the deploy config quietly drifting from what the app actually
needs, each one recorded here because it already happened once, to the
parent this tool forked from (spec §11):

- a rewrite destination without ``$1``, which collapses every path to one
  literal destination and serves the app's own styled 404 for every URL —
  clearly running, and serving nothing;
- ``.vercelignore`` excluding a directory the app imports at request time
  (the parent excluded ``scripts/``, on the assumption a name like that
  meant dev-only tooling, and every route including its own 404 handler
  started raising ``ModuleNotFoundError``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VERCEL_JSON = PROJECT_ROOT / "vercel.json"
VERCELIGNORE = PROJECT_ROOT / ".vercelignore"
API_INDEX = PROJECT_ROOT / "api" / "index.py"


def _vercel_config() -> dict:
    return json.loads(VERCEL_JSON.read_text(encoding="utf-8"))


def test_vercel_json_is_present_and_valid_json() -> None:
    assert VERCEL_JSON.exists()
    _vercel_config()  # raises if malformed


def test_the_rewrite_destination_carries_the_capture_group() -> None:
    """Without `$1` on the destination, every path — `/`, `/topics/new`,
    `/runs/abc/report` — collapses to the same literal destination and
    matches no route in the app. The symptom is a deployment that is clearly
    running (it serves *a* page) while serving nothing anyone asked for."""
    config = _vercel_config()
    rewrites = config.get("rewrites", [])
    assert rewrites, "vercel.json declares no rewrites"
    destinations = [r.get("destination", "") for r in rewrites]
    assert any("$1" in d for d in destinations), (
        f"no rewrite destination carries $1: {destinations}"
    )


def test_the_function_vercel_will_actually_find_is_declared() -> None:
    """Vercel discovers functions by scanning `api/`, not by reading this
    key — but a `functions` entry for a path with no file backing it is a
    config that describes a deployment that does not exist."""
    config = _vercel_config()
    functions = config.get("functions", {})
    assert "api/index.py" in functions
    assert API_INDEX.exists(), "vercel.json configures api/index.py, but the file is missing"


def test_var_dir_points_somewhere_actually_writable() -> None:
    """The one thing Task 24 leaves to this file: an ephemeral path that is
    at least writable, since only /tmp is on Vercel's read-only filesystem."""
    config = _vercel_config()
    var_dir = config.get("env", {}).get("VSM_VAR_DIR", "")
    assert var_dir.startswith("/tmp/"), f"VSM_VAR_DIR={var_dir!r} is not under /tmp"


def test_vercelignore_never_excludes_a_directory_the_app_imports_at_runtime() -> None:
    """The exact mistake spec §11 records the parent making, checked by
    import rather than by name — a directory that merely *sounds* like
    dev-only tooling is exactly how it happened the first time."""
    if not VERCELIGNORE.exists():
        import pytest

        pytest.skip(".vercelignore is not present")

    excluded = {
        line.strip().rstrip("/")
        for line in VERCELIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#") and "*" not in line
    }

    imported: set[str] = set()
    pattern = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_][\w]*)", re.M)
    for source_dir in (PROJECT_ROOT / "vsm", PROJECT_ROOT / "api"):
        for path in source_dir.rglob("*.py"):
            for name in pattern.findall(path.read_text(encoding="utf-8")):
                candidate = PROJECT_ROOT / name
                # Only names that are real top-level directories of this
                # repo — this is not trying to catch third-party imports,
                # only "a local directory this app reaches into".
                if candidate.is_dir() and not name.startswith((".", "_")):
                    imported.add(name)

    collision = sorted(imported & excluded)
    assert not collision, (
        f".vercelignore excludes {collision}, which vsm/ or api/ imports at "
        "runtime. The deployment will raise ModuleNotFoundError on the first "
        "request that reaches it."
    )


def test_vercelignore_keeps_the_templates_and_static_directories() -> None:
    """Named explicitly because they are not `.py` files, so the import-scan
    test above cannot see them: `vsm/ui/templates` is read by Jinja2's
    `FileSystemLoader` and `vsm/ui/static` is served by `StaticFiles`, both
    at request time, neither via a Python `import`."""
    if not VERCELIGNORE.exists():
        import pytest

        pytest.skip(".vercelignore is not present")
    text = VERCELIGNORE.read_text(encoding="utf-8")
    excluded_lines = [
        ln.strip() for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    for pattern in excluded_lines:
        assert not pattern.rstrip("/") in ("vsm", "vsm/ui", "vsm/ui/templates", "vsm/ui/static"), (
            f".vercelignore excludes {pattern!r}, which the app reads at request time"
        )
    assert (PROJECT_ROOT / "vsm" / "ui" / "templates").is_dir()
    assert (PROJECT_ROOT / "vsm" / "ui" / "static").is_dir()


def test_vercel_json_never_pins_the_master_offline_switch() -> None:
    """`VSM_OFFLINE` must not live in `vercel.json`'s `env` block.

    It was hardcoded there, and commit 74b97f1 removed it so the dashboard could
    control it. The failure it caused is the most confusing kind available: every
    key set correctly, the gate up, the site serving, `vercel env add VSM_OFFLINE 0`
    reporting success — and `vercel.json`'s `env` silently overriding it, so
    `Settings.offline` stays True, every sweep collapses to the fake miner, and
    nothing errors. Zero real signals, zero spend, no message.

    Nothing prevented it being pasted back, which is why this exists. Absence is
    safe on its own: `vsm/config.py` already defaults `VSM_OFFLINE` to "1", so a
    deployment with nothing configured is still inert and cannot spend.
    """
    env = _vercel_config().get("env", {})
    assert "VSM_OFFLINE" not in env, (
        "VSM_OFFLINE is pinned in vercel.json — it will override the dashboard "
        "variable and a live launch will silently do nothing"
    )
