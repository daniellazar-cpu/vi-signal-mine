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




def test_the_ordinal_is_strictly_increasing():
    """The one property the whole run-ordering scheme rests on."""
    from vsm.backends.vercel_blob import _next_ordinal

    got = [_next_ordinal() for _ in range(500)]
    assert got == sorted(got)
    assert len(set(got)) == len(got), "an ordinal repeated"


def test_the_ordinal_never_ties_under_concurrency():
    """The hazard `RunStoreLike` names is the tie, not the clock. Sixteen
    threads allocating flat out must not produce one."""
    import threading

    from vsm.backends.vercel_blob import _next_ordinal

    out: list[int] = []
    lock = threading.Lock()

    def work():
        mine = [_next_ordinal() for _ in range(200)]
        with lock:
            out.extend(mine)

    threads = [threading.Thread(target=work) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(out) == 16 * 200
    assert len(set(out)) == len(out), (
        f"{len(out) - len(set(out))} ties across 16 concurrent allocators"
    )


def test_a_clock_that_stalls_or_steps_backwards_still_advances(monkeypatch):
    """`time.time_ns()` is not guaranteed monotonic — an NTP correction can move
    it backwards, and a coarse timer can return the same value twice. Either
    would produce a tie, which is the failure the contract forbids."""
    import vsm.backends.vercel_blob as mod

    frozen = [1_000_000_000]
    monkeypatch.setattr(mod.time, "time_ns", lambda: frozen[0])
    a, b, c = mod._next_ordinal(), mod._next_ordinal(), mod._next_ordinal()
    assert a < b < c, (a, b, c)

    frozen[0] = 1  # a large step backwards
    d = mod._next_ordinal()
    assert d > c, "a backwards clock produced a non-increasing ordinal"


def test_allocating_an_ordinal_makes_no_network_call(store):
    """The point of the change. The old counter needed a read *and* a
    conditional write per allocation, against a store whose read lags its
    write — so allocation could fail. This must touch nothing."""
    s, host = store
    calls = []
    for name in ("get_content", "put", "list_all"):
        import functools
        orig = getattr(s._ns._http, name)
        setattr(s._ns._http, name,
                functools.partial(lambda n, *a, **k: calls.append(n), name))

    from vsm.backends.vercel_blob import _next_ordinal

    before = host.stored
    [_next_ordinal() for _ in range(20)]
    assert calls == [], f"allocation still talks to the store: {calls}"
    assert host.stored == before


def test_ordinals_sort_after_values_written_by_the_old_counter():
    """Existing production records hold small values (1..9). They were created
    first and must keep sorting first, or the deployed history reorders."""
    from vsm.backends.vercel_blob import _next_ordinal

    assert min(_next_ordinal() for _ in range(5)) > 9




# ---------------------------------------------------------------- cold reads --
#
# The list API is only eventually consistent: "PUT a brand-new pathname, then
# list that exact pathname" can come back empty. `_resolve` used it as a
# fallback whenever the instance had no cached domain — and a cold container
# that only *reads* has written nothing, so it always took that fallback.
#
# On production this made the report step fail about half the time: mine wrote
# `signals.json` on one container, the report POST landed on a different cold
# one, the list had not caught up, and `read_artifact` raised
# `FileNotFoundError` — surfacing as "No snapshot to report on" for a snapshot
# that existed. Deriving the host from the token removes the list from every
# read path.


def test_the_content_host_is_derived_from_the_token():
    """Pinned against this deployment's real store: token store id
    `tLMD7oDfiL8G8UPE` serves from `tlmd7odfil8g8upe.public.blob...`."""
    from vsm.backends.vercel_blob import _domain_from_token

    assert (_domain_from_token("vercel_blob_rw_tLMD7oDfiL8G8UPE_abc123secret")
            == "tlmd7odfil8g8upe.public.blob.vercel-storage.com")


@pytest.mark.parametrize("token", [
    "fake-token-for-unit-test",
    "vercel_blob_rw__secret",          # empty store id
    "vercel_blob_rw_onlyfourparts",
    "",
    "vercel_blob_ro_STORE_secret",     # not a read-write token
])
def test_an_unrecognised_token_degrades_instead_of_guessing(token):
    """A wrong host would 404 every read, which is worse than the lag it
    replaces. Anything unfamiliar must fall back to lazy discovery."""
    from vsm.backends.vercel_blob import _domain_from_token

    assert _domain_from_token(token) is None


def test_a_cold_read_only_instance_never_consults_the_list_api():
    """The actual regression. A fresh instance that has written nothing must
    still resolve a pathname without listing."""
    from vsm.backends.vercel_blob import BlobRunStore

    store = BlobRunStore("vercel_blob_rw_tLMD7oDfiL8G8UPE_abc123secret", root="vsm-cold")
    listed: list[str] = []
    store._ns._http.list_all = lambda prefix: listed.append(prefix) or []  # type: ignore[assignment]

    url = store._ns._resolve("vsm-cold/artifacts/min-abc/signals.json")
    assert url == (
        "https://tlmd7odfil8g8upe.public.blob.vercel-storage.com"
        "/vsm-cold/artifacts/min-abc/signals.json"
    )
    assert listed == [], f"a cold read still went to the list API: {listed}"


def test_an_unrecognised_token_still_resolves_via_the_list_api():
    """The fallback must remain wired, or an unfamiliar token would break
    every read rather than merely being slower."""
    from vsm.backends.vercel_blob import BlobRunStore

    store = BlobRunStore("fake-token-for-unit-test", root="vsm-cold")
    assert store._ns._domain is None
    store._ns._http.list_all = lambda prefix: [  # type: ignore[assignment]
        {"pathname": "vsm-cold/x.json", "url": "https://host.example/vsm-cold/x.json"}
    ]
    assert store._ns._resolve("vsm-cold/x.json") == "https://host.example/vsm-cold/x.json"


# ------------------------------------------------- request-scoped identity map --


def _http():
    from vsm.backends.vercel_blob import _BlobHTTP
    return _BlobHTTP("vercel_blob_rw_tLMD7oDfiL8G8UPE_secret")


def _wire(http, monkeypatch, bodies: dict):
    """Count real sends, serving from `bodies` by url."""
    sent: list[str] = []

    class _Resp:
        def __init__(self, url):
            self._url = url
            self.status_code = 200 if url in bodies else 404
            self.content = bodies.get(url, b"")
            self.headers = {"etag": '"e"'}

        def raise_for_status(self):
            pass

        def json(self):
            return {"url": self._url}

    def fake_send(method, url, **kwargs):
        sent.append(url)
        return _Resp(url)

    monkeypatch.setattr(http, "_send", fake_send)
    return sent


def test_the_same_blob_is_fetched_once_per_request(monkeypatch):
    """The 504. One page render fetched the same handful of blobs hundreds of
    times — 13,144 GETs, past the 60s function ceiling."""
    http = _http()
    url = "https://h/vsm/runs/min-abc.json"
    sent = _wire(http, monkeypatch, {url: b'{"a":1}'})

    for _ in range(200):
        assert http.get_content(url) == (b'{"a":1}', '"e"')
    assert len(sent) == 1, f"{len(sent)} round trips for one blob in one request"


def test_a_404_is_remembered_too(monkeypatch):
    """A missing blob is looked up just as repeatedly as a present one — the
    fan-out does not know in advance which runs belong to which topic."""
    http = _http()
    sent = _wire(http, monkeypatch, {})
    for _ in range(50):
        assert http.get_content("https://h/vsm/runs/nope.json") is None
    assert len(sent) == 1, f"{len(sent)} round trips for one absent blob"


def test_begin_request_drops_the_map(monkeypatch):
    """The map is correct only within one request. A serverless container is
    reused, so without this a later request is served bytes it never read."""
    http = _http()
    url = "https://h/vsm/runs/min-abc.json"
    sent = _wire(http, monkeypatch, {url: b'{"a":1}'})

    http.get_content(url)
    http.begin_request()
    http.get_content(url)
    assert len(sent) == 2, "begin_request did not clear the map"


def test_a_write_invalidates_what_it_wrote(monkeypatch):
    """Read-after-write inside one request must not be served the pre-write
    bytes."""
    http = _http()
    url = "https://h/vsm/runs/min-abc.json"
    store = {url: b'{"v":1}'}
    sent = _wire(http, monkeypatch, store)

    assert http.get_content(url)[0] == b'{"v":1}'
    store[url] = b'{"v":2}'
    http.put("vsm/runs/min-abc.json", b'{"v":2}', "application/json")
    assert http.get_content(url)[0] == b'{"v":2}', "served a stale read after its own write"


def test_both_stores_expose_begin_request():
    """The middleware calls this on the store, not the HTTP layer."""
    from vsm.backends.vercel_blob import BlobRunStore, BlobTopicStore

    for cls in (BlobRunStore, BlobTopicStore):
        s = cls("vercel_blob_rw_tLMD7oDfiL8G8UPE_secret", root="r")
        s.begin_request()
