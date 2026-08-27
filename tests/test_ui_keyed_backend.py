"""The UI against a backend whose ``artifacts_dir`` is a **key, not a path**.

Every other UI test runs on ``RunStore``, whose ``artifacts_dir`` returns a real
``pathlib.Path``. Two of the three shipped backends return a ``PurePosixPath``
subclass standing in for a blob key — no ``.stat()``, no file behind it — and
the UI reached for both. The result was a total outage of the write path on the
deployed app: reads of pre-seeded data worked, and the first run created through
the UI 500ed on its run page, its snapshot, its insight, its report, its topic
detail, and all ten downloads.

Nothing caught it, because a green suite proves the UI works on the one backend
it was tested against. This module tests it against the other contract, using a
local store wrapped so ``artifacts_dir`` behaves exactly as the Blob backend's
does — which needs no token and no network, because the defect was never about
the network.
"""

from __future__ import annotations

import json
from pathlib import PurePosixPath

import pytest
from fastapi.testclient import TestClient

from vsm.demo import seed_demo_topic
from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore
from vsm.ui.app import create_app


class _KeyPath(PurePosixPath):
    """The Blob backend's ``artifacts_dir`` return value, in miniature.

    Deliberately implements only what that class implements — ``exists`` /
    ``is_file`` / ``resolve`` — so that any UI code reaching for ``.stat()``,
    ``.read_text()``, ``.open()`` or handing this to ``FileResponse`` fails
    here the same way it failed in production. Do **not** add methods to make a
    test pass; that is the bug, not the fix.
    """

    _real = None  # set per-instance by the store below

    def exists(self) -> bool:
        return bool(self._real and (self._real / str(self).partition("/")[2]).exists())

    def is_file(self) -> bool:
        return self.exists()

    def resolve(self, strict: bool = False):
        return self


class KeyedRunStore:
    """A real store that hands its *callers* keys instead of paths.

    A delegating proxy rather than a subclass, and that distinction is the
    point: ``RunStore.create`` calls ``self.artifacts_dir(...).mkdir()``, so a
    subclass overriding the method breaks the store's own writes. Delegation
    reproduces the real shape — ``BlobRunStore``'s internals never treat its
    artifact path as a filesystem path either; only the UI did.
    """

    def __init__(self, real: RunStore) -> None:
        self._real = real

    def __getattr__(self, item):
        return getattr(self._real, item)

    def artifacts_dir(self, run_id: str):
        real = self._real.artifacts_dir(run_id)

        class _Bound(_KeyPath):
            _real = real

        return _Bound(run_id)


@pytest.fixture
def keyed(tmp_path, monkeypatch):
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    ts = TopicStore(tmp_path / "db")
    real = RunStore(tmp_path / "db", tmp_path / "var")
    seed_demo_topic(ts, real, env={})
    # Seed through the real store, then serve the UI through the keyed
    # view — the deployed shape, where data exists and the UI must read it
    # back without assuming a filesystem.
    rs = KeyedRunStore(real)
    topic = ts.list()[0]
    runs = {m: [r for r in rs.for_topic(topic.topic_id, m) if r.status == "complete"]
            for m in ("mine", "insight", "report")}
    return {"client": TestClient(create_app(topic_store=ts, run_store=rs)),
            "topic": topic, "runs": runs, "run_store": rs}


def test_every_page_that_renders_a_deliverable_card_survives_a_keyed_backend(keyed):
    """The five routes that 500ed in production, all of which call
    `_deliverable_cards`, which called `.stat()` on a key."""
    topic_id = keyed["topic"].topic_id
    paths = [f"/topics/{topic_id}"]
    for mode, suffix in (("mine", "snapshot"), ("insight", "insight"), ("report", "report")):
        for run in keyed["runs"][mode]:
            paths += [f"/runs/{run.run_id}", f"/runs/{run.run_id}/{suffix}"]
    assert len(paths) > 4, "fixture produced too few runs to be a real test"
    for path in paths:
        r = keyed["client"].get(path)
        assert r.status_code == 200, f"{path} → {r.status_code} on a keyed backend"


def test_every_artifact_downloads_on_a_keyed_backend(keyed):
    """`FileResponse` needs a real local file. Two backends have none."""
    seen = 0
    for mode in ("mine", "insight", "report"):
        for run in keyed["runs"][mode]:
            page = keyed["client"].get(f"/runs/{run.run_id}")
            assert page.status_code == 200
            import re
            for name in set(re.findall(
                rf"/runs/{run.run_id}/artifact/([A-Za-z0-9_.\-]+)", page.text
            )):
                r = keyed["client"].get(f"/runs/{run.run_id}/artifact/{name}")
                assert r.status_code == 200, f"{name} → {r.status_code}"
                assert r.content, f"{name} downloaded empty"
                seen += 1
    assert seen >= 3, f"only {seen} downloads exercised — expected the full set"


def test_a_downloaded_artifact_is_byte_identical_to_what_the_store_holds(keyed):
    """The size on the card and the bytes of the download are both
    reconstructed rather than streamed off disk. If that reconstruction ever
    stops matching what the writers write, a download silently differs from the
    stored artifact — so pin it."""
    # One markdown and one JSON artifact, discovered rather than assumed —
    # the two reconstruction branches must both be covered.
    pairs = []
    for mode in ("report", "insight", "mine"):
        for run in keyed["runs"][mode]:
            import re
            page = keyed["client"].get(f"/runs/{run.run_id}").text
            for name in sorted(set(re.findall(
                rf"/runs/{run.run_id}/artifact/([A-Za-z0-9_.\-]+)", page
            ))):
                pairs.append((run.run_id, name))
    assert any(n.endswith(".md") for _, n in pairs), "no markdown artifact found"
    assert any(n.endswith(".json") for _, n in pairs), "no JSON artifact found"
    for run_id, name in pairs:
        content = keyed["run_store"].read_artifact(run_id, name)
        expected = (content if isinstance(content, str)
                    else json.dumps(content, indent=2, sort_keys=True)).encode("utf-8")
        r = keyed["client"].get(f"/runs/{run_id}/artifact/{name}")
        assert r.status_code == 200
        assert r.content == expected, f"{name} download differs from the stored bytes"


def test_an_unknown_artifact_is_404_not_500_on_a_keyed_backend(keyed):
    run = keyed["runs"]["report"][0]
    r = keyed["client"].get(f"/runs/{run.run_id}/artifact/nope.json")
    assert r.status_code == 404, f"unknown artifact → {r.status_code}"


def test_a_traversing_artifact_name_is_still_refused(keyed):
    """The route no longer does its own path arithmetic — it relies on each
    backend's guard. Prove that guard is actually reached and does not 500."""
    run = keyed["runs"]["report"][0]
    for name in ("../../etc/passwd", "..%2f..%2fetc%2fpasswd", "/etc/passwd"):
        r = keyed["client"].get(f"/runs/{run.run_id}/artifact/{name}")
        assert r.status_code in (307, 404), f"{name!r} → {r.status_code}"
        assert b"root:" not in r.content
