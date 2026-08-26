"""Hermetic unit tests for ``vsm/backends/vercel_blob.py`` — no network, no
``BLOB_READ_WRITE_TOKEN`` required, always part of the default suite.

The shared contract suite (``tests/test_storage_contract.py``) exercises
this backend end-to-end against the real Blob API, but only when a live
token is present — see that file's own module docstring for why. This file
covers logic worth pinning even without one, by faking the two points where
``_BlobNamespace`` ever touches the network (``_resolve`` and
``_http.get_content``) rather than mocking HTTP itself: neither method does
any I/O at construction time (confirmed in ``vsm/backends/vercel_blob.py``'s
own docstrings), so building a real ``BlobRunStore`` with a bogus token and
monkeypatching just those two calls is enough to exercise the surrounding
logic honestly.
"""

from __future__ import annotations

import pytest

from vsm.backends.vercel_blob import BlobRunStore


def _fake_store(monkeypatch: pytest.MonkeyPatch, content_by_pathname: dict[str, bytes]) -> BlobRunStore:
    """A ``BlobRunStore`` whose namespace never makes a real HTTP call:
    ``_resolve(pathname)`` returns the pathname itself as a stand-in "url"
    when it is a key in ``content_by_pathname``, ``None`` otherwise; the
    faked ``get_content`` then looks that same string up as its own "url"
    argument. Good enough to exercise ``read_artifact`` honestly without
    needing a real Blob host in the loop."""
    store = BlobRunStore("fake-token-for-unit-test", root="vsm-unit-test")

    def fake_resolve(pathname: str) -> str | None:
        return pathname if pathname in content_by_pathname else None

    def fake_get_content(url: str) -> tuple[bytes, str | None] | None:
        if url not in content_by_pathname:
            return None
        return content_by_pathname[url], "etag-not-exercised-here"

    monkeypatch.setattr(store._ns, "_resolve", fake_resolve)
    monkeypatch.setattr(store._ns._http, "get_content", fake_get_content)
    return store


def test_read_artifact_returns_non_json_text_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """**The regression this pins.** An earlier version of
    ``read_artifact`` called ``_BlobNamespace.read_json`` unconditionally —
    a method built for topic/run records, which *are* always JSON — before
    ever checking the artifact name's suffix. ``pulse_report.md`` is plain
    markdown, not JSON, so that call raised ``json.JSONDecodeError`` on
    every attempt to read this app's own actual deliverable, discovered
    only by testing a non-JSON artifact directly against the live store
    (the shared contract suite's own artifact case only ever writes
    ``signals.json``, so it never exercised this path). Would fail on any
    reintroduction of that bug."""
    run_id = "min-abc123"
    name = "pulse_report.md"
    text = "# Hello\n\nThis is **not** JSON.\n"
    store = _fake_store(
        monkeypatch, {f"vsm-unit-test/artifacts/{run_id}/{name}": text.encode("utf-8")}
    )
    assert store.read_artifact(run_id, name) == text


def test_read_artifact_still_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other half of the same decision: a ``.json`` name is still
    parsed, not merely returned as raw text — the fix above must not have
    swung the other way."""
    run_id = "min-abc123"
    name = "signals.json"
    store = _fake_store(
        monkeypatch,
        {f"vsm-unit-test/artifacts/{run_id}/{name}": b'{"signal_id": "sig-1"}'},
    )
    assert store.read_artifact(run_id, name) == {"signal_id": "sig-1"}


def test_read_artifact_raises_file_not_found_for_a_missing_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _fake_store(monkeypatch, {})
    with pytest.raises(FileNotFoundError):
        store.read_artifact("min-abc123", "signals.json")
