"""The composed app. Stores are constructed here and nowhere else.

``open_stores`` is the seam a later Postgres-plus-blob backend (task 24's
Vercel constraint) lands behind without this module changing at all.
"""

from __future__ import annotations

from vsm.config import get_settings
from vsm.demo import seed_demo_topic
from vsm.storage import open_stores
from vsm.ui.app import create_app

_settings = get_settings()
_topic_store, _run_store = open_stores(_settings)

# Cold-start seed: a no-op unless the store is genuinely empty *and*
# ephemeral (see vsm/demo.py's own guards) — the fix for "the app does not
# work" on a fresh serverless container with no database configured.
seed_demo_topic(_topic_store, _run_store)

app = create_app(topic_store=_topic_store, run_store=_run_store)
