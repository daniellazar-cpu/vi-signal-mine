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
2. **Only when storage is actually ephemeral.** A configured database URL
   means topics persist for real (spec'd by
   :func:`vsm.backends.dburl.resolve_db_url`, the same function
   ``open_stores`` itself defers to) — seeding a synthetic demonstration
   topic into a *real* database would leave fabricated rows sitting there
   forever next to genuine ones, which is a worse failure than the empty
   list this function exists to fix.
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

import logging
import os
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


def seed_demo_topic(
    topic_store: Any, run_store: Any, *, env: Mapping[str, str] | None = None
) -> None:
    """Seed one fully-worked demonstration topic, but only on a cold, empty,
    ephemeral store. A no-op in every other case — see the module docstring
    for the three guards this checks, in the order it checks them.
    """
    if resolve_db_url(env if env is not None else os.environ) is not None:
        return  # a real database is configured — topics here persist for real
    if topic_store.list():
        return  # not a cold, empty container — never overwrite, never duplicate

    # Forced offline regardless of this process's real settings: a cold-start
    # seed must never place one real, billed request. See vsm.mining.get_miner
    # — offline=True is what makes effective_miner_mode() return "fake".
    offline = Settings(offline=True)

    topic = topic_store.create(
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
    first = run_mine(
        topic, run_store, client=None,
        miner=get_miner(offline, band=BANDS["probe"]),
    )
    second = run_mine(
        topic, run_store, client=None,
        miner=get_miner(offline, band=BANDS["standard"]),
    )

    insight = run_insight(topic, second.run_id, run_store, client=None)
    run_report(topic, insight.run_id, run_store, client=None)

    _log.info(
        "seeded a demonstration topic (%s) on a cold, empty store — two "
        "snapshots (%s, %s), one insight run and one report run, every row "
        "synthetic",
        topic.topic_id, first.run_id, second.run_id,
    )
