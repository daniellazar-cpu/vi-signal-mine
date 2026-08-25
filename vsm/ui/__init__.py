"""The web UI: FastAPI routes and Jinja2 templates over the engine's stores.

Nothing in here computes a fact the engine has not already computed. A
template's job is to arrange numbers that ``vsm.modes`` and ``vsm.analysis``
already produced, and to say plainly when one of them is absent — never to
fill a gap with a zero or a blank cell.
"""

from __future__ import annotations
