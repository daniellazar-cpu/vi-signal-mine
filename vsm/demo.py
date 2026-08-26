"""The worked example seeded on a cold, empty, ephemeral store.

**The failure this exists to fix.** With no database URL configured,
``vsm.storage.open_stores`` wires up SQLite-plus-filesystem under
``settings.var_dir`` (spec'd out in that module's own docstring) — and on
Vercel, ``var_dir`` is ``/tmp``, which belongs to a single invocation and
does not survive a container being recycled. An owner who creates a topic on
that deployment gets redirected to it and, on the very next request, meets
"No topic with id ...": the write happened, the redirect fired, and the
container that held the row was already gone. No database can be
provisioned from here, so the fix is not to pretend the storage is durable —
it is to make sure a cold, empty container is never actually empty: on
startup, if the store holds no topics, seed one fully-worked example —
a topic, two dated snapshots, an INSIGHT run and a REPORT run — so every
screen (topics, snapshot, the forest plot, all four report artifacts,
downloads) is explorable the moment anyone lands here, container recycle or
not.

**Guarded three ways, all required:**

1. **Only on a genuinely empty store.** ``topic_store.list()`` non-empty
   means some earlier call already seeded this container, or a real visitor
   already created something real — either way, seeding again would
   silently duplicate the demo topic or race a concurrent write. An empty
   store is the only signal this function trusts, and it never updates or
   deletes anything to get there.
2. **Only when storage is actually ephemeral.** A configured database URL,
   or a configured ``BLOB_READ_WRITE_TOKEN``, means topics persist for real
   — the same two names, checked in the same order, that
   :func:`vsm.storage.open_stores` itself defers to when picking a backend
   (:func:`vsm.backends.dburl.resolve_db_url` for the former). Seeding a
   synthetic demonstration topic into either real backend would leave
   fabricated rows sitting there forever next to genuine ones, which is a
   worse failure than the empty list this function exists to fix — this
   check is deliberately "would ``open_stores`` pick something other than
   SQLite+filesystem", not ``vsm.platform.storage_is_durable``, which would
   also say yes for a plain local install with neither configured (SQLite on
   a real filesystem *is* durable there) and wrongly skip the seed a fresh
   local checkout still needs.
3. **Always the offline, deterministic fake miner, regardless of this
   process's own ``VSM_OFFLINE``/``VSM_MINER``.** A cold-start seed must
   never place one real, billed request — so the ``Settings`` handed to
   :func:`vsm.mining.get_miner` here is a fresh, forced-offline instance,
   never whatever the caller's actual environment resolved to. Every row
   :class:`~vsm.mining.fake.DeterministicMiner` produces already carries
   ``synthetic: True`` (see that module), which is what makes the existing
   fabrication notice on every downstream artifact fire honestly for this
   topic exactly as it would for any other synthetic run.

Called once, from the composition root (``vsm/app.py``), never from a test:
the test suite builds its own stores directly and never imports
``vsm.app`` — see ``tests/test_deployment_scaffolding.py`` and
``api/index.py`` for the only real caller.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from vsm.backends.dburl import resolve_db_url
from vsm.config import Settings
from vsm.mining import get_miner
from vsm.modes.insight import run_insight
from vsm.modes.mine import run_mine
from vsm.modes.report import run_report
from vsm.topics.model import BANDS

__all__ = ["seed_demo_topic"]

_log = logging.getLogger(__name__)

#: The worked example. "obesity" appears in the name on purpose — it is an
#: ``endocrinology`` keyword in ``vsm.mining.venues.AREA_KEYWORDS``, so the
#: gold-list router actually scopes this topic's queries the way a real one
#: would, rather than falling back to the general venue pool.
_TOPIC_NAME = "Tirzepatide for obesity — a worked example"
_THERAPEUTIC_AREA = "obesity"
_BRAND = "Zepbound"
_MOLECULE = "tirzepatide"
_COMPETITORS = ("Wegovy", "Ozempic")
_QUESTIONS = (
    "What do clinicians say about tolerability and titration?",
    "What are patients saying about side effects and access?",
)

# ---------------------------------------------------------------------------
# Deterministic identity for the seeded topic and its four runs.
#
# **The bug this fixes.** ``TopicStore.create``/``RunStore.start`` normally
# mint ids from ``uuid.uuid4()`` and timestamps from the real wall clock —
# fine for a real topic, but this function runs once *per cold container*.
# On a platform with no shared database (the entire reason this module
# exists — see the module docstring), every container that starts cold calls
# this with an empty store and seeds its *own* copy of the worked example,
# with its *own* random ids. A link minted while container A answered one
# request 404s the instant it is clicked and the request lands on container
# B, whose seed used different ids — "sometimes it works, sometimes it
# doesn't", entirely depending on which container happens to answer which
# request. There is no way to coordinate containers that share no storage,
# so the only fix is to make every container derive the *same* ids and
# timestamps from the *same* fixed inputs, with no ``uuid4()`` and no clock
# read anywhere in this path — a link minted anywhere resolves everywhere.
#
# **Scope, precisely.** Nothing here touches ``TopicStore``/``RunStore``'s
# normal id generation — a real topic or run a visitor creates still gets a
# fresh ``uuid4()`` id from the unmodified default path (``run_id=None`` is
# still what every other caller passes), so two genuine runs can never
# collide with each other or with the seed. Only this module ever passes the
# ``run_id``/``started_at``/``finished_at`` overrides that ``run_mine``,
# ``run_insight`` and ``run_report`` accept for exactly this purpose.
_ID_SEED = "vi-signal-mine/demo-topic/v1"

#: Anchors every seeded timestamp. Deliberately close to (but distinct from)
#: ``vsm.mining.fake.DeterministicMiner``'s own fixed clock
#: (2026-07-31) — both exist for the same reason: a re-run must be
#: byte-identical, so neither may ever read ``datetime.now()``.
_BASE_CLOCK = datetime(2026, 7, 31, tzinfo=timezone.utc)


def _stable_hex(*parts: object) -> str:
    """A short, deterministic hex id — same shape as ``uuid4().hex[:10]``
    (10 lowercase hex characters), but a pure function of ``_ID_SEED`` plus
    ``parts`` rather than of the process's random source. Two different
    ``parts`` (e.g. the mine-1 vs. mine-2 run) must never collide, which is
    why every id below passes a distinct discriminator through this."""
    digest = hashlib.sha256(
        "|".join((_ID_SEED, *(str(p) for p in parts))).encode("utf-8")
    ).hexdigest()
    return digest[:10]


def _stable_topic_id() -> str:
    return f"top-{_stable_hex('topic')}"


def _stable_run_id(mode: str, ordinal: int) -> str:
    # `mode[:3]` matches RunStore.start's own real-id format exactly
    # ("min-", "ins-", "rep-") so a seeded run id is indistinguishable in
    # shape from a genuine one.
    return f"{mode[:3]}-{_stable_hex('run', mode, ordinal)}"


def _stable_ts(offset_seconds: int) -> str:
    """A fixed point in time, ``offset_seconds`` after ``_BASE_CLOCK`` — never
    ``datetime.now()``. The offsets below are spaced out and strictly
    increasing in call order purely so a human reading two artifacts'
    timestamps sees a sensible before/after story; nothing downstream
    depends on the actual gaps."""
    return (_BASE_CLOCK + timedelta(seconds=offset_seconds)).isoformat()


def seed_demo_topic(
    topic_store: Any, run_store: Any, *, env: Mapping[str, str] | None = None
) -> None:
    """Seed one fully-worked demonstration topic, but only on a cold, empty,
    ephemeral store. A no-op in every other case — see the module docstring
    for the three guards this checks, in the order it checks them.
    """
    env = env if env is not None else os.environ
    if resolve_db_url(env) is not None:
        return  # a real database is configured — topics here persist for real
    if (env.get("BLOB_READ_WRITE_TOKEN") or "").strip():
        return  # Vercel Blob is configured — topics here persist for real too
    if topic_store.list():
        return  # not a cold, empty container — never overwrite, never duplicate

    # Forced offline regardless of this process's real settings: a cold-start
    # seed must never place one real, billed request. See vsm.mining.get_miner
    # — offline=True is what makes effective_miner_mode() return "fake".
    offline = Settings(offline=True)

    topic = topic_store.create(
        # Deterministic, not `uuid.uuid4()`: see the module-level comment
        # above `_ID_SEED` for why every id and timestamp in this function
        # must be a pure function of a fixed seed rather than of this
        # process's random source or its wall clock.
        topic_id=_stable_topic_id(),
        created_at=_stable_ts(0),
        name=_TOPIC_NAME,
        therapeutic_area=_THERAPEUTIC_AREA,
        # "probe" is the only band Vercel's own guard (vsm.platform.assert_band_allowed)
        # lets a MINE run use in production — seeding a topic in a band that
        # would refuse to run its own next sweep would be a strange first thing
        # for a visitor to hit.
        spend_band="probe",
        brand=_BRAND,
        molecule=_MOLECULE,
        competitors=_COMPETITORS,
        questions=_QUESTIONS,
    )

    # Two dated snapshots, not one: momentum and anomaly detection both need a
    # prior snapshot to compare against, and a lone snapshot would leave both
    # reading "no prior snapshot" everywhere — not a worked example of either
    # pass. The second snapshot draws from the wider "standard" band (more
    # queries than the first's "probe"-sized sweep), so the two are not
    # byte-identical: there is a real, if modest, change for momentum to
    # report, and "standard" (queries_per_cluster=4) is exactly the
    # configuration already proven to produce a measured, non-"NE" dual-lens
    # divergence for the forest plot (see
    # tests/test_synthetic.py::test_produces_a_measurable_dual_lens_divergence).
    #
    # `run_id`/`started_at`/`finished_at` are the same kind of override as
    # `topic_id`/`created_at` above. `started_at` matters beyond the run row
    # itself: `run_mine` stamps it onto every signal row as `snapshot_at`
    # (vsm/modes/mine.py), so leaving it to the real clock would make
    # `signals.json` itself come out different bytes on every container —
    # the artifact, not just the link to it.
    first = run_mine(
        topic, run_store, client=None,
        miner=get_miner(offline, band=BANDS["probe"]),
        run_id=_stable_run_id("mine", 1),
        started_at=_stable_ts(10),
        finished_at=_stable_ts(11),
    )
    second = run_mine(
        topic, run_store, client=None,
        miner=get_miner(offline, band=BANDS["standard"]),
        run_id=_stable_run_id("mine", 2),
        started_at=_stable_ts(20),
        finished_at=_stable_ts(21),
    )

    insight = run_insight(
        topic, second.run_id, run_store, client=None,
        run_id=_stable_run_id("insight", 1),
        started_at=_stable_ts(30),
        finished_at=_stable_ts(31),
    )
    run_report(
        topic, insight.run_id, run_store, client=None,
        run_id=_stable_run_id("report", 1),
        started_at=_stable_ts(40),
        finished_at=_stable_ts(41),
    )

    _log.info(
        "seeded a demonstration topic (%s) on a cold, empty store — two "
        "snapshots (%s, %s), one insight run and one report run, every row "
        "synthetic",
        topic.topic_id, first.run_id, second.run_id,
    )
