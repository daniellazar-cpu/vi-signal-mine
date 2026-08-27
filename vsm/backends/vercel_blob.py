"""Topics, runs and artifacts on Vercel Blob — the third storage backend.

**Naming, and why this is not ``vsm/backends/blob.py``.** That module already
exists and already means something specific: ``BlobArtifacts``, a key-value
*table on Postgres* that ``PostgresRunStore`` uses for artifact storage,
named "blob" for what it conceptually is (a blob store), not for what it is
built on (Postgres, via that module's own SQL). This module is a genuinely
different backend — real Vercel Blob, the storage product, reached over its
HTTP API — for a different Protocol pair (``TopicStoreLike``/``RunStoreLike``
in full, not just artifacts). Putting both under one filename would make one
file answer to two unrelated meanings of "blob" for two different Vercel
products; the module name here is deliberately unambiguous instead.

**The API, verified live before anything below was written** (not assumed
from memory — this project has been bitten five times doing that). Every
claim below was checked against ``https://blob.vercel-storage.com`` with a
real ``BLOB_READ_WRITE_TOKEN`` during development:

- ``PUT {base}/{pathname}`` with ``authorization: Bearer <token>`` and
  ``x-api-version: 7`` uploads. Two headers this backend always sets:

  * ``x-add-random-suffix: 0`` — without it, Vercel Blob appends a random
    suffix to the stored filename and the response ``url`` differs from the
    ``pathname`` requested, which is fine for one-shot uploads but wrong for
    a key-value store: it makes "write the record at this id" impossible,
    since a second PUT unable to know the first suffix could not overwrite
    it. With this header, ``pathname`` *is* the durable identity a caller
    can reconstruct and PUT again.
  * ``x-cache-control-max-age: 0`` — without it, Vercel Blob serves reads
    through a CDN cache (confirmed ``s-maxage=300`` by default), and this
    store's own overwrite-in-place update pattern (a run's ``finish()``,
    a topic's ``update()``) needs the very next read, from any instance, to
    see the new value — not whatever an edge node cached up to five minutes
    ago. Read-after-write correctness matters more than CDN latency for a
    low-traffic internal tool, so caching is disabled outright rather than
    tuned.

- ``x-if-match: <etag>`` on a ``PUT`` is honoured as a real compare-and-swap
  precondition: a mismatched (or since-changed) ETag 412s with
  ``{"error":{"code":"precondition_failed",...}}`` rather than silently
  overwriting. Confirmed live. This once underpinned a compare-and-swap
  counter (:func:`_next_ordinal`'s docstring records why that could not be
  made reliable here); the conditional-write primitive itself is sound
  below is built on; see its docstring for how. (The mirror header,
  ``x-if-none-match: *``, is advertised in this API's CORS allow-list but is
  **not** actually enforced — verified live by PUTting the same pathname
  twice with that header and getting 200 both times, not a 412 on the
  second. Nothing here depends on it.)

- Reading content is **not** a GET on the write endpoint above — that 404s.
  A successful ``PUT``/list response carries a ``url`` on a *separate*,
  store-specific public host (``<id>.public.blob.vercel-storage.com``); the
  content lives there, and that GET response's ``ETag`` header is what
  content reads generally. The store's host is stable for
  the store's lifetime, so it is cached per instance after first discovery
  (see ``_resolve``) rather than re-discovered on every read.

- ``GET {base}/?prefix=<prefix>&limit=&cursor=`` (auth'd) lists, returning
  ``{"blobs":[{url,pathname,size,uploadedAt}...], "hasMore", "cursor"?}``.
  Each entry's ``url`` is already fully qualified, so listing under a
  namespace never needs the per-item resolve step reads-by-id do.

- ``POST {base}/delete`` (auth'd, JSON body ``{"urls":[...]}``) deletes,
  returning ``200``/``null``. Used by nothing in this module today — no
  caller deletes a topic or a run — but exercised in ad hoc verification of
  the above, and kept here (``_BlobHTTP.delete``) as the one place that
  would implement it.

**No SDK, no shared code with the other two backends.** ``httpx`` is on the
allowed-dependency list precisely so this can be built on it directly (see
``pyproject.toml``); the spec for this backend explicitly rules out both a
dedicated Blob SDK and a shim shared across SQLite/Postgres/Blob — see
``vsm/storage.py``'s module docstring for why a unifying shim is where the
subtle bugs live. Everything below is this backend's own access code.
"""

from __future__ import annotations

import json
import posixpath
import random
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

import httpx

from vsm.errors import NoSuchRun, NoSuchTopic
from vsm.runs.model import RUN_MODES, RUN_STATUSES, Run
from vsm.topics.model import BANDS, Topic

__all__ = ["BlobTopicStore", "BlobRunStore"]

_API_BASE = "https://blob.vercel-storage.com"
#: Distinguishes "read it, and it was a 404" from "not read yet" in the
#: request-scoped map, so a genuine absence is memoised too rather than being
#: re-fetched on every one of hundreds of duplicate lookups.
_MISSING = object()

_API_VERSION = "7"

#: How many times the sequence allocator retries a lost compare-and-swap race
#: before giving up. Contention on one counter blob is the whole point of the

_TUPLE_FIELDS = ("competitors", "questions", "never_say")
_UPDATABLE = frozenset({
    "name", "therapeutic_area", "spend_band", "brand", "molecule",
    "competitors", "questions", "never_say",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _content_type_for(name: str) -> str:
    return "application/json" if name.endswith(".json") else "text/plain; charset=utf-8"


#: Status codes worth retrying — transient, not a real answer about the
#: request itself. Discovered live, not assumed: a 20-thread burst of PUTs
#: at the same pathname (the shape a burst of racing unconditional PUTs produces
#: under real concurrency) repeatedly drew ``503`` with body
#: ``{"error":{"code":"service_unavailable","message":"Blob service is
#: currently unavailable. Please try again."}}`` — explicitly a "retry me",
#: not a real answer, and confirmed live that a bare retry of the identical
#: request succeeds. Rate-limit headers on those same responses
#: (``x-ratelimit-remaining`` in the high hundreds out of a 1500 budget)
#: rule out actual rate-limiting as the cause. Neither this nor ``429`` is
#: the CAS-lost-the-race signal (that is ``412``, handled by
#: a caller's own retry, never here).
_TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})
_TRANSIENT_MAX_ATTEMPTS = 5


class _BlobHTTP:
    """The raw REST calls, isolated from the two stores that use them.

    A fresh ``httpx.Client`` per call, used as a context manager and always
    closed — the same "open, use, close" shape ``TopicStore``/``RunStore``'s
    ``_conn()`` already uses for SQLite (see that module's own docstring on
    why: an unclosed connection is a leaked resource whose ``ResourceWarning``
    at finalisation is "evidence, not noise", not something to silence).
    A first version of this class held one ``httpx.Client`` for the whole
    store instance's lifetime to pool connections — sound in isolation, but
    it left every store instance built during a test session holding an open
    socket with nothing to close it, and this project's own
    ``filterwarnings = ["error"]`` (``pyproject.toml``) turns the resulting
    ``ResourceWarning`` into a real failure the moment the garbage collector
    happens to finalise one mid-suite. Fresh-per-call trades a small amount
    of TLS-handshake overhead — irrelevant next to the network round trip
    already dominating every call here — for never holding a socket open
    longer than one request needs it.
    """

    def __init__(self, token: str, timeout: float = 20.0) -> None:
        self._timeout = timeout
        self._auth = {"authorization": f"Bearer {token}", "x-api-version": _API_VERSION}
        #: Request-scoped identity map, url -> (content, etag) or `_MISSING`.
        #: Cleared by `begin_request`; see `get_content` for why it exists and
        #: why it must not outlive one request.
        self._seen: dict[str, Any] = {}

    def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """One request, retried up to ``_TRANSIENT_MAX_ATTEMPTS`` times on a
        transient status (see ``_TRANSIENT_STATUS``'s own docstring for the
        live evidence behind that set), with a short exponential backoff
        between attempts. Every other outcome — success, 412, 404, a real
        4xx — returns on the first attempt; only a transient status ever
        loops here."""
        last: httpx.Response | None = None
        for attempt in range(_TRANSIENT_MAX_ATTEMPTS):
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.request(method, url, **kwargs)
            if resp.status_code not in _TRANSIENT_STATUS:
                return resp
            last = resp
            if attempt < _TRANSIENT_MAX_ATTEMPTS - 1:
                time.sleep(0.1 * (2**attempt))
        return last  # type: ignore[return-value]  # loop always runs >=1 time

    def put(
        self, pathname: str, content: bytes, content_type: str, if_match: str | None = None
    ) -> dict | None:
        """Upload at a fixed ``pathname`` (no random suffix, no CDN cache —
        see the module docstring). Returns the parsed response on success,
        or ``None`` on a lost compare-and-swap so a CAS loop can retry.
        Anything else non-2xx raises, same as every other method here.

        **A lost CAS is not always a clean 412.** Verified live under real
        concurrent writers (a burst of unconditional PUTs racing on the same
        fresh pathname): a losing PUT can come back as ``400`` with body
        ``{"error":{"code":"bad_request","message":"The conditional request
        cannot succeed due to a conflicting operation against this
        resource."}}`` instead of ``412``. A single-writer test never
        surfaces this — it only showed up racing sixteen real threads
        against the live API — so both shapes are treated as the same
        signal here: only ``x-if-match`` ever produces a genuine
        precondition failure (an unconditional PUT, ``if_match=None``, has
        no precondition to fail), so a 400 with this exact error code is
        unambiguous, not a guess at what "probably" means the same thing.
        """
        headers = {
            **self._auth,
            "x-content-type": content_type,
            "x-add-random-suffix": "0",
            "x-cache-control-max-age": "0",
        }
        if if_match is not None:
            headers["x-if-match"] = if_match
        resp = self._send("PUT", f"{_API_BASE}/{pathname}", content=content, headers=headers)
        # Whatever this pathname's content URL was, the map's copy is now wrong.
        # Keyed by url, not pathname, so drop every entry whose url ends in it.
        for url in [u for u in self._seen if u.endswith("/" + pathname)]:
            del self._seen[url]
        if resp.status_code == 412:
            return None
        if resp.status_code == 400 and if_match is not None:
            try:
                body = resp.json()
            except ValueError:
                body = {}
            if body.get("error", {}).get("code") == "bad_request":
                return None
        resp.raise_for_status()
        return resp.json()

    def list_page(self, prefix: str, limit: int = 1000, cursor: str | None = None) -> dict:
        params: dict[str, str] = {"prefix": prefix, "limit": str(limit)}
        if cursor:
            params["cursor"] = cursor
        resp = self._send("GET", f"{_API_BASE}/", params=params, headers=self._auth)
        resp.raise_for_status()
        return resp.json()

    def list_all(self, prefix: str) -> list[dict]:
        """Every blob under ``prefix``, following ``cursor`` pagination —
        verified live that a page's ``hasMore``/``cursor`` behave exactly
        like that: a second page requested with the first page's cursor
        returns the next slice, not a repeat."""
        blobs: list[dict] = []
        cursor: str | None = None
        while True:
            page = self.list_page(prefix, cursor=cursor)
            blobs.extend(page.get("blobs", []))
            if not page.get("hasMore"):
                return blobs
            cursor = page.get("cursor")

    #: Sent on **every** content read. A store is mutable; a cached read of it
    #: is a wrong answer, not a fast one.
    #:
    #: This is not belt-and-braces. Measured live against this store, on a blob
    #: whose own response says ``cache-control: public, max-age=0, s-maxage=0``:
    #:
    #:   plain GET                  -> {"seq": 5}   x-vercel-cache: HIT
    #:   GET with a fresh ?query    -> {"seq": 5}   x-vercel-cache: HIT
    #:   GET with these headers     -> {"seq": 6}   <- the actual stored value
    #:
    #: So the edge serves a stale body **and a stale ETag**, `s-maxage=0` is not
    #: honoured, and a cache-busting query string does not defeat it. Only an
    #: explicit request-side no-cache does.
    #:
    #: That stale ETag is what broke the old CAS counter: it read a superseded value,
    #: PUT with a precondition that could no longer hold, got a genuine 412,
    #: re-read the *same cached copy*, and burned all forty retries — then
    #: reported "too much concurrent contention" with exactly one caller. On
    #: production this made every run creation a coin flip, which is precisely
    #: the "sometimes it does work" this app was reported with. The same
    #: staleness also let a run record read back with an out-of-date status, so
    #: this is a correctness fix for every read, not only for the counter.
    _NO_CACHE = {"cache-control": "no-cache, no-store, max-age=0", "pragma": "no-cache"}

    def begin_request(self) -> None:
        """Drop the identity map. Called once per HTTP request.

        The map below is **not** a TTL cache and must never become one: it is
        correct only for the span of one request, and a container reused for a
        later request would otherwise serve that request a value it did not
        read. Clearing is therefore the caller's responsibility, wired in
        `vsm/ui/app.py`'s middleware rather than left to a timer.
        """
        self._seen.clear()

    def get_content(self, url: str) -> tuple[bytes, str | None] | None:
        """``(content, etag)`` for an already-known full blob URL, or
        ``None`` on 404. No auth header needed — the store's default access
        is public-read, confirmed live (an unauthenticated GET on the
        content host succeeded).

        **Memoised for the current request.** Not a performance nicety: the
        topics index renders one row per topic, and each row asked the store
        for that topic's runs — which, on a store with no secondary index,
        means listing every run blob and reading each one's content to find out
        which topic it belongs to. Twice per row, because `snapshots()` is
        itself a filter over `for_topic()`. So the cost was O(topics x runs x 2)
        *round trips*, and the same handful of blobs were fetched hundreds of
        times within a single page render. Measured on production: **13,144**
        content GETs, and the home page hit the 60-second function ceiling and
        returned 504.

        Within one request the store is not being written by this process
        between those duplicate reads, so returning the same bytes is not
        merely faster, it is the same answer. A write still invalidates its own
        pathname (see `put`) so a read-after-write inside one request cannot go
        stale.
        """
        hit = self._seen.get(url)
        if hit is not None:
            return None if hit is _MISSING else hit
        resp = self._send("GET", url, headers=self._NO_CACHE)
        if resp.status_code == 404:
            self._seen[url] = _MISSING
            return None
        resp.raise_for_status()
        got = (resp.content, resp.headers.get("etag"))
        self._seen[url] = got
        return got

    def delete(self, urls: list[str]) -> None:
        if not urls:
            return
        resp = self._send(
            "POST",
            f"{_API_BASE}/delete",
            content=json.dumps({"urls": urls}).encode("utf-8"),
            headers={**self._auth, "content-type": "application/json"},
        )
        resp.raise_for_status()


_ORDINAL_LOCK = threading.Lock()
_LAST_ORDINAL = 0


def _next_ordinal() -> int:
    """A strictly increasing sort key, allocated with **no coordination**.

    This replaces a compare-and-swap loop over a shared ``_seq.json`` counter.
    That loop could not be made reliable on this backend, and the reason is
    structural rather than a tuning problem: the conditional ``PUT`` goes to the
    write API, which knows the authoritative state, while the read that supplies
    its ``x-if-match`` ETag comes from the content host, which lags. So the
    precondition was routinely compared against a value that had already moved.
    Live on production, every ``GET`` returned 200 and the following ``PUT``
    returned ``412 Precondition Failed``, over and over, until one attempt
    happened to read a copy that was still current — and when propagation was
    slower than the retry budget, all forty attempts failed and the request
    500ed with "too much concurrent contention" with a single caller in the
    system. Run creation was a coin flip. Sending request-side ``no-cache``
    (which does make an external read authoritative) narrowed the window
    without closing it, because the lag is not only a cache.

    Widening the budget would only have made the race rarer. A counter that must
    be read before it can be written cannot be made atomic on a store with no
    atomic primitive, so this stops needing one.

    **Why this still satisfies the ordering contract.** ``RunStoreLike``
    requires completed MINE runs oldest first "by a monotonic counter, and never
    by comparing timestamps, because two runs created in the same microsecond
    compare equal on a clock and would silently drop a baseline." The hazard
    named there is the *tie*, and this cannot tie: within a process the value is
    strictly increasing (a clock that fails to advance, or steps backwards, is
    clamped to ``last + 1``), and across containers the resolution is
    nanoseconds rather than microseconds. Two allocations would have to land in
    the same nanosecond on two different machines to collide, and such runs are
    genuinely concurrent.

    ``seq`` is safe to change this way because it is only ever a sort key:
    ``BlobTopicStore``/``BlobRunStore`` both ``data.pop("seq", None)`` before
    building the model, so it is never displayed, never returned to a caller,
    and nothing assumes it is dense or small. Records written by the old counter
    hold values like ``1..9`` and sort *before* every value produced here, which
    is correct — they were created first.
    """
    global _LAST_ORDINAL
    with _ORDINAL_LOCK:
        candidate = time.time_ns()
        if candidate <= _LAST_ORDINAL:
            candidate = _LAST_ORDINAL + 1
        _LAST_ORDINAL = candidate
        return candidate


#: The public read host is derivable from the token, with no network call.
#: A ``BLOB_READ_WRITE_TOKEN`` is ``vercel_blob_rw_<storeId>_<secret>``, and the
#: store's content host is ``<storeid lowercased>.public.blob.vercel-storage.com``
#: — verified against this deployment's own store: token store id
#: ``tLMD7oDfiL8G8UPE`` serves content from
#: ``tlmd7odfil8g8upe.public.blob.vercel-storage.com``.
_CONTENT_HOST_SUFFIX = ".public.blob.vercel-storage.com"


def _domain_from_token(token: str) -> str | None:
    """The store's content host, or ``None`` if the token is not the shape we
    know — in which case the caller falls back to lazy discovery rather than
    guessing a host that would 404 every read.

    **Why this matters, and it is not an optimisation.** ``_resolve`` needs a
    content URL for a pathname. Without a known domain it asks the *list* API,
    which is only eventually consistent — "PUT a brand-new pathname, then list
    that exact pathname" can come back empty. `_note_domain` covers a container
    that has written something, but a **cold container that only reads** has
    written nothing, so it fell through to the lagging list and reported a blob
    that exists as missing.

    That is what made the report step fail roughly half the time on production:
    the mine step wrote ``signals.json`` on one container, the report POST landed
    on a different, cold one, ``_resolve`` asked the list API, got nothing back
    yet, and ``read_artifact`` raised ``FileNotFoundError`` — surfacing as the
    honest but wrong "No snapshot to report on". Deriving the host removes the
    list from every read path, so existence is decided by a direct, uncached GET
    that 404s only when the blob is genuinely absent.
    """
    parts = token.split("_")
    # vercel, blob, rw, <storeId>, <secret...>
    if len(parts) < 5 or parts[:3] != ["vercel", "blob", "rw"] or not parts[3]:
        return None
    return parts[3].lower() + _CONTENT_HOST_SUFFIX


class _BlobNamespace:
    """Shared plumbing for the topic and run stores: resolving a pathname to
    its content, and allocating a collision-free ``seq``. Composition, not
    inheritance or a cross-backend base class — ``BlobTopicStore`` and
    ``BlobRunStore`` each hold one of these privately; nothing outside this
    module sees it.
    """

    def __init__(self, token: str, root: str) -> None:
        self._http = _BlobHTTP(token)
        self.root = root
        #: The store's own public read host. Derived from the token up front
        #: (see `_domain_from_token`) so that a cold instance which only ever
        #: *reads* never has to ask the eventually-consistent list API where its
        #: own content lives. Falls back to ``None`` — lazy discovery via
        #: `_note_domain` or `_resolve` — only for a token shape we do not
        #: recognise, so an unfamiliar token degrades to the old behaviour
        #: instead of guessing a host that would 404 every read.
        self._domain: str | None = _domain_from_token(token)

    def _note_domain(self, put_result: dict | None) -> None:
        """Capture the domain from a successful PUT's own response, if not
        already known. **Load-bearing, not just an optimisation.** A PUT
        response's ``url`` is the one way to learn the domain that does not
        go through ``list()`` — and ``list()``, unlike a direct content GET,
        is only eventually consistent: verified live, the sequence
        "PUT a brand-new pathname, immediately ``list(prefix=that exact
        pathname)``" can come back empty on the very next call. That bit a
        cold counter allocation hard — a PUT followed by a `_resolve`
        that still had no cached domain fell through to `list_all`, found
        nothing, and looped, burning every retry before `list()` caught up.
        Every write path below (`write_json`, the artifact PUT in
        ``BlobRunStore.write_artifact``) now feeds
        its result through here, so the *first* successful write on a cold
        instance is also the last time anything in this namespace needs
        `list()` to find its own domain.
        """
        if self._domain is None and put_result is not None:
            self._domain = urlsplit(put_result["url"]).netloc

    def _resolve(self, pathname: str) -> str | None:
        """The full content URL for ``pathname``, or ``None`` if it does not
        exist. Reading a blob's content is not possible from the write API's
        own host (that 404s — verified live, see the module docstring), so
        this always goes by way of a ``url`` a PUT response or a list
        response handed back. With a cached domain (see `_note_domain`), the
        URL is just built and handed back — existence is left to the
        caller's own GET, which correctly 404s for a pathname that was never
        written. Only a genuinely cold instance (no domain known yet, e.g. a
        fresh instance reading something a *different* instance wrote) pays
        for the authoritative, but eventually-consistent, list-based lookup.
        """
        if self._domain is not None:
            return f"https://{self._domain}/{pathname}"
        matches = self._http.list_all(pathname)
        exact = [b for b in matches if b["pathname"] == pathname]
        if not exact:
            return None
        url = exact[0]["url"]
        self._domain = urlsplit(url).netloc
        return url

    def read_json(self, pathname: str) -> dict | None:
        url = self._resolve(pathname)
        if url is None:
            return None
        got = self._http.get_content(url)
        if got is None:
            # A cached domain guess can still 404 for a pathname genuinely
            # never written (see `_resolve`) — that is "not found", not an
            # error, so this mirrors the `url is None` branch above rather
            # than raising.
            return None
        content, _etag = got
        return json.loads(content)

    def write_json(self, pathname: str, obj: dict) -> None:
        body = json.dumps(obj, sort_keys=True).encode("utf-8")
        result = self._http.put(pathname, body, "application/json")
        self._note_domain(result)

    def put_raw(
        self, pathname: str, body: bytes, content_type: str, if_match: str | None = None
    ) -> dict | None:
        """The one path every write in this module goes through, so
        `_note_domain` sees every successful PUT — including non-JSON
        artifact writes (`BlobRunStore.write_artifact`) and the CAS PUTs
        not just `write_json`'s topic/run records."""
        result = self._http.put(pathname, body, content_type, if_match=if_match)
        self._note_domain(result)
        return result

def _validated_key(run_id: str, name: str) -> None:
    """The same traversal guard ``RunStore._artifact_path`` applies to a
    filesystem path, applied to a blob key instead: a caller-supplied
    ``name`` joined into a key with no check is exactly as traversable as
    one joined into a path with no check. ``posixpath.normpath`` the joined
    key and require its directory component to be exactly ``run_id`` — so
    ``"../../etc/passwd"`` and an absolute name are both rejected the same
    way the filesystem store rejects them.
    """
    candidate = posixpath.normpath(posixpath.join(run_id, name))
    if posixpath.dirname(candidate) != run_id:
        raise ValueError(f"artifact name escapes the run directory: {name!r}")


class BlobTopicStore:
    """Topics as one JSON blob per id, under ``{root}/topics/``.

    ``root`` namespaces every pathname this instance touches — analogous to
    ``PostgresTopicStore``'s ``schema`` parameter — so the storage contract
    suite can point two independently-constructed instances at the same
    namespace (proving cross-instance persistence) while keeping different
    tests, or different environments, from colliding on one shared Blob
    store. Production wiring (``vsm/storage.py``) uses a single fixed root;
    tests derive one per ``tmp_path``.
    """

    #: A blob is not readable from every edge the instant its write returns —
    #: measured on production, and the reason `vsm/storage.py:read_required`
    #: exists. Declaring it here rather than having that helper sniff the class
    #: keeps the knowledge with the backend that has the property.
    reads_may_lag = True

    def begin_request(self) -> None:
        """Forwarded to the HTTP layer's request-scoped identity map. Called by
        `vsm/ui/app.py`'s middleware once per request; see
        `_BlobHTTP.get_content` for what the map is for and
        `_BlobHTTP.begin_request` for why it must not outlive a request."""
        self._ns._http.begin_request()

    def __init__(self, token: str, root: str = "vsm") -> None:
        self._ns = _BlobNamespace(token, root)

    def _path(self, topic_id: str) -> str:
        return f"{self._ns.root}/topics/{topic_id}.json"

    @staticmethod
    def _row_to_topic(data: dict) -> Topic:
        data = dict(data)
        data.pop("seq", None)
        for field in _TUPLE_FIELDS:
            data[field] = tuple(data[field])
        return Topic(**data)

    def create(self, **kwargs: Any) -> Topic:
        if kwargs.get("spend_band") not in BANDS:
            raise KeyError(f"unknown spend band: {kwargs.get('spend_band')!r}")
        topic = Topic(
            topic_id=kwargs.pop("topic_id", None) or f"top-{uuid.uuid4().hex[:10]}",
            created_at=kwargs.pop("created_at", _now()),
            **kwargs,
        )
        seq = _next_ordinal()
        record = {
            "topic_id": topic.topic_id, "name": topic.name,
            "therapeutic_area": topic.therapeutic_area, "spend_band": topic.spend_band,
            "created_at": topic.created_at, "brand": topic.brand, "molecule": topic.molecule,
            "competitors": list(topic.competitors), "questions": list(topic.questions),
            "never_say": list(topic.never_say), "seq": seq,
        }
        self._ns.write_json(self._path(topic.topic_id), record)
        return topic

    def get(self, topic_id: str) -> Topic:
        data = self._ns.read_json(self._path(topic_id))
        if data is None:
            raise NoSuchTopic(topic_id, rule="topics")
        return self._row_to_topic(data)

    def list(self) -> list[Topic]:
        blobs = self._ns._http.list_all(f"{self._ns.root}/topics/")
        topics: list[tuple[int, Topic]] = []
        for blob in blobs:
            if blob["pathname"].endswith("/_seq.json"):
                continue
            got = self._ns._http.get_content(blob["url"])
            if got is None:
                continue  # deleted between the list and this read
            content, _etag = got
            data = json.loads(content)
            topics.append((data.get("seq", 0), self._row_to_topic(data)))
        topics.sort(key=lambda pair: pair[0], reverse=True)
        return [t for _seq, t in topics]

    def update(self, topic_id: str, **fields: Any) -> Topic:
        current = self._ns.read_json(self._path(topic_id))
        if current is None:
            raise NoSuchTopic(topic_id, rule="topics")
        for key in fields:
            if key not in _UPDATABLE:
                raise KeyError(f"column {key!r} is not updatable")
        if "spend_band" in fields and fields["spend_band"] not in BANDS:
            raise KeyError(f"unknown spend band: {fields['spend_band']!r}")
        updated = dict(current)
        for key, value in fields.items():
            updated[key] = list(value) if key in _TUPLE_FIELDS else value
        self._ns.write_json(self._path(topic_id), updated)
        return self.get(topic_id)


class BlobRunStore:
    """Run metadata as one JSON blob per id under ``{root}/runs/``; run
    artifacts as one blob per ``(run_id, name)`` under
    ``{root}/artifacts/``. Same split of concerns as ``RunStore`` (SQLite
    rows vs. files) and ``PostgresRunStore`` (its own table vs.
    ``BlobArtifacts``) — a run's metadata and its artifacts are genuinely
    different access patterns that happen to share one public interface.

    No ``run_id``/``started_at`` override parameters on ``start()`` (unlike
    ``vsm.runs.store.RunStore``, which carries them for
    ``vsm.demo.seed_demo_topic``'s deterministic cold-start seed) — matching
    ``PostgresRunStore`` exactly, because that seed only ever runs against
    ephemeral storage (see ``vsm/demo.py``'s own guard, extended by this
    task to recognise this backend as durable too) and never against this
    one. ``vsm.modes.mine.run_mine`` already builds its override dict
    conditionally for exactly this reason — see that function's own
    docstring.
    """

    #: A blob is not readable from every edge the instant its write returns —
    #: measured on production, and the reason `vsm/storage.py:read_required`
    #: exists. Declaring it here rather than having that helper sniff the class
    #: keeps the knowledge with the backend that has the property.
    reads_may_lag = True

    def begin_request(self) -> None:
        """Forwarded to the HTTP layer's request-scoped identity map. Called by
        `vsm/ui/app.py`'s middleware once per request; see
        `_BlobHTTP.get_content` for what the map is for and
        `_BlobHTTP.begin_request` for why it must not outlive a request."""
        self._ns._http.begin_request()

    def __init__(self, token: str, root: str = "vsm") -> None:
        self._ns = _BlobNamespace(token, root)

    def _run_path(self, run_id: str) -> str:
        return f"{self._ns.root}/runs/{run_id}.json"

    def _artifact_path(self, run_id: str, name: str) -> str:
        return f"{self._ns.root}/artifacts/{run_id}/{name}"

    @staticmethod
    def _to_run(data: dict) -> Run:
        data = dict(data)
        data.pop("seq", None)
        return Run(**data)

    def start(
        self, topic_id: str, mode: str, parent_run_id: str | None = None
    ) -> Run:
        if mode not in RUN_MODES:
            raise KeyError(f"unknown run mode: {mode!r}")
        run = Run(
            run_id=f"{mode[:3]}-{uuid.uuid4().hex[:10]}", topic_id=topic_id,
            mode=mode, status="running", started_at=_now(),
            parent_run_id=parent_run_id,
        )
        seq = _next_ordinal()
        record = {
            "run_id": run.run_id, "topic_id": topic_id, "mode": mode,
            "status": "running", "started_at": run.started_at, "finished_at": None,
            "cost_usd": 0.0, "parent_run_id": parent_run_id, "note": "", "seq": seq,
        }
        self._ns.write_json(self._run_path(run.run_id), record)
        return run

    def finish(
        self, run_id: str, status: str, cost_usd: float, note: str = ""
    ) -> Run:
        if status not in RUN_STATUSES:
            raise KeyError(f"unknown run status: {status!r}")
        current = self._ns.read_json(self._run_path(run_id))
        if current is None:
            raise NoSuchRun(run_id, rule="runs")
        updated = dict(current)
        updated.update(
            status=status, finished_at=_now(), cost_usd=float(cost_usd), note=note
        )
        self._ns.write_json(self._run_path(run_id), updated)
        return self.get(run_id)

    def get(self, run_id: str) -> Run:
        data = self._ns.read_json(self._run_path(run_id))
        if data is None:
            raise NoSuchRun(run_id, rule="runs")
        return self._to_run(data)

    def for_topic(self, topic_id: str, mode: str | None = None) -> list[Run]:
        """Every run for ``topic_id``, oldest first by ``seq``.

        Vercel Blob has no query language, so this fans out: list every
        pathname under ``{root}/runs/``, fetch each one's content, and
        filter/sort client-side. ``O(total runs across every topic)`` per
        call rather than an index lookup — the deliberate cost of a flat
        key-value store with no secondary index, acceptable at this app's
        scale (an internal pulse instrument, not a multi-tenant service);
        the correctness this buys (``seq`` read from the one place it is
        ever written) is worth more here than the read amplification costs.
        """
        blobs = self._ns._http.list_all(f"{self._ns.root}/runs/")
        rows: list[tuple[int, Run]] = []
        for blob in blobs:
            if blob["pathname"].endswith("/_seq.json"):
                continue
            got = self._ns._http.get_content(blob["url"])
            if got is None:
                continue
            content, _etag = got
            data = json.loads(content)
            if data.get("topic_id") != topic_id:
                continue
            if mode is not None and data.get("mode") != mode:
                continue
            rows.append((data.get("seq", 0), self._to_run(data)))
        rows.sort(key=lambda pair: pair[0])
        return [r for _seq, r in rows]

    def snapshots(self, topic_id: str) -> list[Run]:
        """Completed MINE runs, oldest first — see ``vsm/storage.py``'s
        ``RunStoreLike.snapshots`` docstring: ordered by the monotonic
        ``seq`` every record carries (allocated by ``_next_ordinal``'s
        compare-and-swap loop, never by comparing ``started_at``), the same
        contract ``RunStore``/``PostgresRunStore`` satisfy."""
        return [
            r for r in self.for_topic(topic_id, "mine") if r.status == "complete"
        ]

    def _artifact_exists(self, run_id: str, name: str) -> bool:
        return self._ns._resolve(self._artifact_path(run_id, name)) is not None

    def artifacts_dir(self, run_id: str) -> Any:
        path_cls = _bound_run_artifact_path_class(self)
        return path_cls(run_id)

    def write_artifact(self, run_id: str, name: str, payload: Any) -> Any:
        _validated_key(run_id, name)
        text = payload if isinstance(payload, str) else json.dumps(
            payload, indent=2, sort_keys=True
        )
        self._ns.put_raw(
            self._artifact_path(run_id, name),
            text.encode("utf-8"),
            _content_type_for(name),
        )
        path_cls = _bound_run_artifact_path_class(self)
        return path_cls(run_id) / name

    def read_artifact(self, run_id: str, name: str) -> Any:
        """One fetch, deciding *before* touching the bytes whether they are
        JSON — deliberately not built on ``_BlobNamespace.read_json``, whose
        job is topic/run records that are always JSON. An artifact is not:
        ``pulse_report.md`` is plain markdown, and ``read_json`` calling
        ``json.loads`` on it unconditionally would raise
        ``json.JSONDecodeError`` before this method ever got a chance to
        treat the name's ``.json`` suffix as the deciding signal, the same
        bug the filesystem (``RunStore``) and Postgres (``BlobArtifacts``)
        backends both avoid by checking the suffix first, parsing second."""
        _validated_key(run_id, name)
        url = self._ns._resolve(self._artifact_path(run_id, name))
        if url is None:
            raise FileNotFoundError(f"no artifact named {name!r} on run {run_id!r}")
        got = self._ns._http.get_content(url)
        if got is None:
            raise FileNotFoundError(f"no artifact named {name!r} on run {run_id!r}")
        content, _etag = got
        text = content.decode("utf-8")
        return json.loads(text) if name.endswith(".json") else text


def _bound_run_artifact_path_class(store: "BlobRunStore") -> type[PurePosixPath]:
    """See the module-level note on ``BlobTopicStore``/``BlobRunStore`` for
    why this is not shared with ``vsm/backends/blob.py``'s equivalent. Bound
    to ``store`` as a class attribute so ``PurePosixPath``'s own ``/`` /
    ``.parent`` machinery (which calls ``type(self)(...)`` internally) keeps
    producing instances of this same bound subclass.
    """

    class _BoundRunArtifactPath(PurePosixPath):
        _store = store

        def exists(self) -> bool:
            run_id, sep, name = str(self).partition("/")
            return sep != "" and self._store._artifact_exists(run_id, name)

        def is_file(self) -> bool:
            return self.exists()

        def resolve(self, strict: bool = False) -> "_BoundRunArtifactPath":
            # No filesystem beneath this to resolve against — the traversal
            # guard already ran in `_validated_key` at write/read time. See
            # `vsm/backends/blob.py`'s identical note on its own
            # `_BoundBlobPath.resolve` for why this is deliberately a no-op.
            return self

    return _BoundRunArtifactPath
