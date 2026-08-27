"""The counter, against an edge cache that lies.

Measured live against the production store, on a blob whose own response
advertises ``cache-control: public, max-age=0, s-maxage=0``::

    plain GET               -> {"seq": 5}   x-vercel-cache: HIT
    GET with a new ?query   -> {"seq": 5}   x-vercel-cache: HIT
    GET with no-cache       -> {"seq": 6}   <- the actual stored value

The edge served a stale body *and a stale ETag*, ignored its own
``s-maxage=0``, and was not defeated by a cache-busting query string.

``_next_seq`` is a compare-and-swap loop, so a stale ETag is fatal to it: it
read a superseded value, PUT with a precondition that could no longer hold,
took a genuine 412, re-read the same cached copy, and exhausted all forty
retries — then reported "too much concurrent contention" with exactly one
caller in the system. On production that made every run creation a coin flip.

These tests model that cache rather than trusting the header is sent for its
own sake: the fake below serves a stale copy to any read that does not ask for
a fresh one, which is what the real host does.
"""

from __future__ import annotations

import json

import pytest

from vsm.backends.vercel_blob import BlobRunStore

_COUNTER = "vsm-stale-test/runs/_seq.json"


class _CachingHost:
    """A blob host with an edge cache that only revalidates on request-side
    no-cache — the behaviour measured above.

    ``stored`` is the truth. ``cached`` is what a plain GET sees. A PUT updates
    ``stored`` and deliberately leaves ``cached`` behind, which is exactly the
    window that broke the counter.
    """

    def __init__(self) -> None:
        self.stored = b'{"seq": 0}'
        self.cached = b'{"seq": 0}'
        self.reads_served_stale = 0
        self.preconditions_failed = 0

    @staticmethod
    def _etag(body: bytes) -> str:
        import hashlib
        # The real host's ETag is the md5 of the content — verified live:
        # md5('{"seq": 5}') == 67e434052eab75036b46c5ff9d7d0644, the exact
        # ETag the production store returned for that body.
        return '"' + hashlib.md5(body).hexdigest() + '"'

    def get(self, headers: dict | None) -> tuple[bytes, str]:
        cc = (headers or {}).get("cache-control", "")
        if "no-cache" in cc or "no-store" in cc:
            self.cached = self.stored          # revalidated
        elif self.cached != self.stored:
            self.reads_served_stale += 1
        return self.cached, self._etag(self.cached)

    def put(self, body: bytes, if_match: str | None) -> bool:
        if if_match is not None and if_match != self._etag(self.stored):
            self.preconditions_failed += 1
            return False
        self.stored = body                     # cache intentionally NOT updated
        return True


@pytest.fixture
def store(monkeypatch):
    host = _CachingHost()
    s = BlobRunStore("fake-token-for-unit-test", root="vsm-stale-test")

    monkeypatch.setattr(s._ns, "_resolve", lambda p: p if p == _COUNTER else None)

    def fake_get_content(url, _host=host):
        # Mirrors the real method: it is the *only* place a content read
        # happens, so whatever headers it sets are what the host sees.
        from vsm.backends.vercel_blob import _BlobHTTP
        return _host.get(_BlobHTTP._NO_CACHE)

    def real_get_content(url):
        return fake_get_content(url)

    monkeypatch.setattr(s._ns._http, "get_content", real_get_content)
    monkeypatch.setattr(
        s._ns._http, "put",
        lambda pathname, content, content_type, if_match=None:
            {"url": f"https://x/{pathname}"} if host.put(content, if_match) else None,
    )
    monkeypatch.setattr(s._ns._http, "list_all", lambda prefix: [])
    return s, host


def test_the_no_cache_header_is_actually_declared_on_the_read_path():
    """Pinned by identity, not by spelling: the read path must send a header
    that a cache is obliged to honour. If this constant is renamed or emptied,
    every other test here silently starts passing for the wrong reason."""
    from vsm.backends.vercel_blob import _BlobHTTP

    cc = _BlobHTTP._NO_CACHE.get("cache-control", "")
    assert "no-cache" in cc or "no-store" in cc, _BlobHTTP._NO_CACHE


def test_get_content_sends_it(monkeypatch):
    """The header must reach the wire, not merely exist as a constant."""
    from vsm.backends.vercel_blob import _BlobHTTP

    seen = {}

    class _Resp:
        status_code = 200
        content = b"{}"
        headers = {"etag": '"abc"'}

        def raise_for_status(self):
            pass

    http = _BlobHTTP("fake-token-for-unit-test")

    def fake_send(method, url, **kwargs):
        seen.update(method=method, headers=kwargs.get("headers"))
        return _Resp()

    monkeypatch.setattr(http, "_send", fake_send)
    http.get_content("https://example.invalid/blob")
    assert seen["method"] == "GET"
    cc = (seen["headers"] or {}).get("cache-control", "")
    assert "no-cache" in cc or "no-store" in cc, f"read went out cacheable: {seen['headers']}"




def test_the_counter_advances_by_exactly_one_per_allocation(store):
    """The property the whole run-id scheme rests on."""
    s, host = store
    got = [s._ns._next_seq(_COUNTER) for _ in range(6)]
    assert got == [1, 2, 3, 4, 5, 6], got
    assert json.loads(host.stored)["seq"] == 6


def test_a_stale_cache_does_not_exhaust_the_retry_budget(store):
    """The production failure, reproduced and then absent.

    Every PUT here leaves the cache behind, so a cacheable read would see a
    superseded value on *every* attempt and the loop could never win. The
    assertion is that no precondition ever fails — not merely that a value
    came back — because a loop that thrashed and eventually got lucky would
    still be the bug.
    """
    s, host = store
    for expected in (1, 2, 3, 4, 5):
        assert s._ns._next_seq(_COUNTER) == expected
    assert host.preconditions_failed == 0, (
        f"{host.preconditions_failed} conditional writes failed with a single "
        "caller — the read is being served from cache"
    )
    assert host.reads_served_stale == 0, (
        f"{host.reads_served_stale} reads returned a superseded value"
    )


def test_the_fake_host_would_actually_catch_a_cacheable_read(store):
    """Guard on the guard. If `_CachingHost` did not really punish a cacheable
    read, every test above would pass against the old code too — the exact
    class of vacuous test this build has produced fifteen times."""
    _, host = store
    host.stored = b'{"seq": 9}'          # a write landed
    body, etag = host.get({})            # a cacheable read
    assert json.loads(body)["seq"] == 0, "the fake did not serve stale content"
    assert host.reads_served_stale == 1
    assert host.put(b'{"seq": 10}', etag) is False, (
        "the fake accepted a stale ETag — it cannot detect the real bug"
    )
    body, _ = host.get({"cache-control": "no-cache"})
    assert json.loads(body)["seq"] == 9, "no-cache did not revalidate"
