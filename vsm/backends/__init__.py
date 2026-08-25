"""The Postgres-plus-blob backend (Task 24).

Nothing in this package is imported eagerly by the rest of the app.
``vsm/storage.py`` imports ``vsm.backends.dburl`` unconditionally — it is pure
stdlib — but only reaches into ``vsm.backends.postgres`` / ``.blob`` (which
import ``psycopg``) once ``resolve_db_url`` has actually found a URL. That is
what keeps ``psycopg`` an optional extra rather than a core dependency: the
local tool, and the whole hermetic test suite, must install and run without it.
"""

from __future__ import annotations
