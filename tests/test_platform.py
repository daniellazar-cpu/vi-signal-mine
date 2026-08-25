import asyncio

import pytest

from vsm.errors import GuardViolation
from vsm.platform import (
    StripFunctionPrefix,
    assert_band_allowed,
    assert_serveable,
    is_vercel,
)


def test_production_deployment_refuses_to_serve(monkeypatch):
    """Spec D15. Protection is Vercel preview gating, which covers preview
    deployments only. This guard is what makes 'preview-only' a property of the
    code instead of a dashboard setting that has to stay correct — a deploy that
    escapes to a production domain is inert rather than open, with the API keys
    behind it."""
    monkeypatch.setenv("VERCEL_ENV", "production")
    with pytest.raises(GuardViolation, match="production"):
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
