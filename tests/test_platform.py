import asyncio

import pytest

from vsm.errors import GuardViolation
from vsm.platform import (
    StripFunctionPrefix,
    assert_band_allowed,
    assert_serveable,
    is_vercel,
    storage_is_durable,
)


def test_production_refuses_only_when_it_has_something_to_lose(monkeypatch):
    """Spec D15, as refined.

    Vercel gates preview deployments only on this plan, so a production URL is
    reachable by anyone holding it. The thing worth protecting is not the URL
    but the live keys behind it, which can spend real money — so live keys with
    no gate is the combination that refuses, and it is the only one.
    """
    monkeypatch.setenv("VERCEL_ENV", "production")
    monkeypatch.setenv("VSM_OFFLINE", "0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-live-looking-key")
    monkeypatch.delenv("VSM_ACCESS_KEY", raising=False)
    with pytest.raises(GuardViolation, match="VSM_ACCESS_KEY"):
        assert_serveable()


def test_production_serves_when_offline_leaves_nothing_to_abuse(monkeypatch):
    """A fresh deployment carrying no secrets is inert, so it may be clicked.

    The first version of this guard refused all production traffic, which made
    the URL a person naturally lands on permanently dead — indistinguishable
    from a broken deployment, and there was nothing to protect.
    """
    monkeypatch.setenv("VERCEL_ENV", "production")
    monkeypatch.setenv("VSM_OFFLINE", "1")
    monkeypatch.delenv("VSM_ACCESS_KEY", raising=False)
    assert assert_serveable() is None


def test_production_serves_when_an_access_key_gates_it(monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "production")
    monkeypatch.setenv("VSM_OFFLINE", "0")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-live-looking-key")
    monkeypatch.setenv("VSM_ACCESS_KEY", "a-shared-secret")
    assert assert_serveable() is None


def test_the_guard_fails_closed(monkeypatch):
    """Offline off and no access key is a refusal, never a default-allow.

    Worth its own test because the permissive branches are the new behaviour,
    and a guard that grew two ways to say yes is exactly where an accidental
    third one would hide.
    """
    monkeypatch.setenv("VERCEL_ENV", "production")
    monkeypatch.setenv("VSM_OFFLINE", "0")
    monkeypatch.delenv("VSM_ACCESS_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("BRIGHTDATA_API_KEY", raising=False)
    with pytest.raises(GuardViolation):
        assert_serveable()


def test_preview_deployment_serves(monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "preview")
    assert assert_serveable() is None


def test_local_serves(monkeypatch):
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    assert assert_serveable() is None
    assert is_vercel() is False


@pytest.mark.parametrize("band", ["standard", "deep"])
def test_only_probe_runs_on_vercel(monkeypatch, band):
    """Spec D14. A standard or deep sweep does not fit in a function timeout,
    and a sweep that dies halfway leaves a half-written snapshot that later
    momentum silently treats as real."""
    monkeypatch.setenv("VERCEL", "1")
    with pytest.raises(GuardViolation, match="probe"):
        assert_band_allowed(band)


def test_probe_runs_on_vercel(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    assert assert_band_allowed("probe") is None


def test_every_band_runs_locally(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    for band in ("probe", "standard", "deep"):
        assert assert_band_allowed(band) is None


def test_the_refusal_names_where_to_run_it_instead(monkeypatch):
    """A guard that only says no teaches nothing."""
    monkeypatch.setenv("VERCEL", "1")
    with pytest.raises(GuardViolation) as exc:
        assert_band_allowed("deep")
    assert "local" in str(exc.value).lower()


# --- storage_is_durable: the read-only-mode guard ------------------------


def test_storage_is_not_durable_with_no_database_on_vercel():
    """The one combination that actually cannot honour a write: SQLite plus
    a filesystem under a single serverless invocation's own /tmp, which does
    not survive the container being recycled — see vsm/storage.py."""
    assert storage_is_durable({"VERCEL": "1"}) is False


def test_storage_is_durable_with_no_database_locally():
    """A local run must be entirely unaffected: no VERCEL means one
    long-lived process reading and writing the same directory on every
    request — nothing like Vercel's per-invocation /tmp — so SQLite plus
    the filesystem is genuinely durable here, database or not."""
    assert storage_is_durable({}) is True


def test_storage_is_durable_with_a_database_on_vercel():
    """A database url resolving wins outright, Vercel or not — Postgres+blob
    storage survives any request landing on any instance."""
    assert storage_is_durable({"VERCEL": "1", "DATABASE_URL": "postgresql://x/y"}) is True


def test_storage_is_durable_with_a_database_locally():
    assert storage_is_durable({"DATABASE_URL": "postgresql://x/y"}) is True


@pytest.mark.parametrize("var", ["POSTGRES_URL_NON_POOLING", "POSTGRES_URL", "DATABASE_URL"])
def test_storage_is_durable_recognises_every_db_url_env_var(var):
    """Delegates to resolve_db_url rather than re-checking one hardcoded
    name — proven by exercising all three names that module recognises."""
    assert storage_is_durable({"VERCEL": "1", var: "postgresql://x/y"}) is True


def test_storage_is_durable_reads_the_real_environment_by_default(monkeypatch):
    """No ``env`` argument means ``os.environ``, read fresh — the same
    convention ``resolve_db_url``, ``open_stores`` and ``seed_demo_topic``
    already use, so a database configured after the process started is
    reflected on the very next call with no restart."""
    monkeypatch.setenv("VERCEL", "1")
    for var in ("POSTGRES_URL_NON_POOLING", "POSTGRES_URL", "DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
    assert storage_is_durable() is False
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    assert storage_is_durable() is True


# --- StripFunctionPrefix: the ASGI wrapper vercel.json's rewrite requires ---


@pytest.fixture
def captured():
    """A minimal ASGI inner app that records the scope it was called with."""
    calls: list[dict] = []

    async def inner(scope, receive, send):
        calls.append(scope)

    return inner, calls


def test_strips_the_function_prefix_from_the_path(captured):
    """`vercel.json`'s rewrite carries `$1`, so a request for `/topics/new`
    arrives here as `/api/index/topics/new`. Without this the app's router
    never sees a path it recognises."""
    inner, calls = captured
    app = StripFunctionPrefix(inner)
    asyncio.run(app({"type": "http", "path": "/api/index/topics/new"}, None, None))
    assert calls[0]["path"] == "/topics/new"


def test_the_bare_prefix_strips_to_the_root(captured):
    inner, calls = captured
    app = StripFunctionPrefix(inner)
    asyncio.run(app({"type": "http", "path": "/api/index"}, None, None))
    assert calls[0]["path"] == "/"


def test_an_unprefixed_path_passes_through_unchanged(captured):
    """If Vercel ever routes to the function directly with no rewrite in
    force, this must not mangle a path that was never prefixed."""
    inner, calls = captured
    app = StripFunctionPrefix(inner)
    asyncio.run(app({"type": "http", "path": "/topics/new"}, None, None))
    assert calls[0]["path"] == "/topics/new"


def test_a_lifespan_scope_passes_through_untouched(captured):
    """Only http/websocket scopes carry a path worth rewriting; a lifespan
    scope has none, and indexing `scope['path']` on one would raise."""
    inner, calls = captured
    app = StripFunctionPrefix(inner)
    asyncio.run(app({"type": "lifespan"}, None, None))
    assert calls[0] == {"type": "lifespan"}


def test_does_not_mutate_the_caller_supplied_scope(captured):
    """The platform may reuse the scope dict across the pipeline; mutating a
    caller's dict to fix this app's own routing is a side effect no caller
    of this class would expect."""
    inner, calls = captured
    app = StripFunctionPrefix(inner)
    original = {"type": "http", "path": "/api/index/x"}
    asyncio.run(app(original, None, None))
    assert original["path"] == "/api/index/x"
    assert calls[0]["path"] == "/x"
