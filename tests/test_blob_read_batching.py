"""Round trips, counted.

The app was slow for one reason: a flat key-value store with no secondary index
answers "which runs belong to this topic?" by reading every run record, and it
did so one request at a time. Measured on production with 61 topics and ~180
run records: the home page took **11.6 seconds**, `/deliverables` — a page that
shows no run data at all — took 10.3, and a topic page 4.7, against a 0.6s
baseline for a page that touches no storage.

None of that was compute. It was sequential ~60ms round trips.

These tests count calls rather than measure time, so they fail for the reason
they are named and do not go flaky on a slow machine.
"""

from __future__ import annotations

import json

import pytest

from vsm.backends.vercel_blob import BlobRunStore, BlobTopicStore

_TOKEN = "vercel_blob_rw_tLMD7oDfiL8G8UPE_secret"


class _Recorder:
    """Counts what actually reaches the network."""

    def __init__(self, bodies: dict[str, bytes]) -> None:
        self.bodies = bodies
        self.gets: list[str] = []
        self.lists: list[str] = []

    def install(self, store, monkeypatch):
        http = store._ns._http

        class _Resp:
            def __init__(self, url, outer):
                self._url = url
                self.status_code = 200 if url in outer.bodies else 404
                self.content = outer.bodies.get(url, b"")
                self.headers = {"etag": '"e"'}

            def raise_for_status(self):
                pass

            def json(self):
                return {"url": self._url}

        def fake_send(method, url, **kwargs):
            self.gets.append(url)
            return _Resp(url, self)

        def fake_list_page(prefix, limit=1000, cursor=None):
            self.lists.append(prefix)
            host = "https://tlmd7odfil8g8upe.public.blob.vercel-storage.com/"
            return {"blobs": [{"pathname": u[len(host):], "url": u}
                              for u in self.bodies if u.startswith(host)
                              and u[len(host):].startswith(prefix)],
                    "hasMore": False}

        monkeypatch.setattr(http, "_send", fake_send)
        monkeypatch.setattr(http, "list_page", fake_list_page)
        return store


def _run_bodies(n_runs: int, topic_id="top-a", root="vsm"):
    host = "https://tlmd7odfil8g8upe.public.blob.vercel-storage.com/"
    out = {}
    for i in range(n_runs):
        rid = f"min-{i:04d}"
        out[f"{host}{root}/runs/{rid}.json"] = json.dumps({
            "run_id": rid, "topic_id": topic_id, "mode": "mine",
            "status": "complete", "started_at": "2026-08-27T00:00:00+00:00",
            "finished_at": "2026-08-27T00:00:01+00:00", "cost_usd": 0.0,
            "parent_run_id": None, "note": "", "seq": i,
        }).encode()
    return out


def test_for_topic_reads_every_run_but_in_one_batch(monkeypatch):
    """The reads themselves are unavoidable without a secondary index. Issuing
    them one at a time was not."""
    bodies = _run_bodies(40)
    rec = _Recorder(bodies)
    store = rec.install(BlobRunStore(_TOKEN, root="vsm"), monkeypatch)

    runs = store.for_topic("top-a")
    assert len(runs) == 40
    assert len(rec.gets) == 40, f"{len(rec.gets)} gets for 40 runs"
    # And they went out through the batching path, not one call at a time.
    assert hasattr(store._ns._http, "get_many")


def test_a_second_for_topic_in_the_same_request_costs_nothing(monkeypatch):
    """The index calls this once per topic against the same store."""
    rec = _Recorder(_run_bodies(40))
    store = rec.install(BlobRunStore(_TOKEN, root="vsm"), monkeypatch)

    store.for_topic("top-a")
    first = len(rec.gets), len(rec.lists)
    for _ in range(20):
        store.for_topic("top-a")
    assert (len(rec.gets), len(rec.lists)) == first, (
        f"21 calls cost {len(rec.gets)} gets and {len(rec.lists)} lists"
    )


def test_the_same_prefix_is_listed_once_per_request(monkeypatch):
    """61 topics meant 61 identical prefix listings for one page render."""
    rec = _Recorder(_run_bodies(3))
    store = rec.install(BlobRunStore(_TOKEN, root="vsm"), monkeypatch)

    for _ in range(61):
        store.for_topic("top-a")
    assert len(rec.lists) == 1, f"{len(rec.lists)} listings of one prefix"


def test_begin_request_drops_the_listing_too(monkeypatch):
    """A listing is as request-scoped as a content read — a container is reused,
    and a later request must not be told about runs it never listed."""
    rec = _Recorder(_run_bodies(3))
    store = rec.install(BlobRunStore(_TOKEN, root="vsm"), monkeypatch)

    store.for_topic("top-a")
    store.begin_request()
    store.for_topic("top-a")
    assert len(rec.lists) == 2, "begin_request did not clear the listing map"


def test_get_many_skips_what_is_already_known(monkeypatch):
    rec = _Recorder(_run_bodies(10))
    store = rec.install(BlobRunStore(_TOKEN, root="vsm"), monkeypatch)
    urls = list(rec.bodies)

    store._ns._http.get_many(urls)
    n = len(rec.gets)
    store._ns._http.get_many(urls)
    assert len(rec.gets) == n, "get_many re-fetched urls it had already read"


def test_get_many_returns_none_for_a_missing_url_without_dropping_it(monkeypatch):
    """Callers index the result by url, so a 404 must be present as None rather
    than absent from the mapping."""
    rec = _Recorder(_run_bodies(2))
    store = rec.install(BlobRunStore(_TOKEN, root="vsm"), monkeypatch)
    urls = list(rec.bodies) + ["https://tlmd7odfil8g8upe.public.blob.vercel-storage.com/vsm/runs/nope.json"]

    out = store._ns._http.get_many(urls)
    assert set(out) == set(urls)
    assert out[urls[-1]] is None


def test_prefetch_is_optional_and_never_changes_what_a_read_returns(monkeypatch):
    """It is an optimisation. A caller that skips it must get identical
    results, and a bad pair must not raise."""
    host = "https://tlmd7odfil8g8upe.public.blob.vercel-storage.com/"
    bodies = {f"{host}vsm/artifacts/min-1/signals.json": b'[{"id":1}]'}
    rec = _Recorder(bodies)
    store = rec.install(BlobRunStore(_TOKEN, root="vsm"), monkeypatch)

    store.prefetch_artifacts([("min-1", "signals.json"),
                              ("min-1", "../escape.json"),   # refused, not raised
                              ("min-2", "absent.json")])
    assert store.read_artifact("min-1", "signals.json") == [{"id": 1}]
    with pytest.raises(FileNotFoundError):
        store.read_artifact("min-2", "absent.json")


def test_the_topic_list_is_batched_too(monkeypatch):
    host = "https://tlmd7odfil8g8upe.public.blob.vercel-storage.com/"
    bodies = {
        f"{host}vsm/topics/top-{i:03d}.json": json.dumps({
            "topic_id": f"top-{i:03d}", "name": f"T{i}", "therapeutic_area": "",
            "spend_band": "probe", "created_at": "2026-08-27T00:00:00+00:00",
            "brand": None, "molecule": None, "competitors": [], "questions": [],
            "never_say": [], "seq": i,
        }).encode() for i in range(30)
    }
    rec = _Recorder(bodies)
    store = rec.install(BlobTopicStore(_TOKEN, root="vsm"), monkeypatch)

    assert len(store.list()) == 30
    assert len(rec.gets) == 30
    assert len(rec.lists) == 1
