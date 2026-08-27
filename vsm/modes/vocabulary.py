"""Plain-language names for internal terms, shared by the artifacts and the UI.

The interface and the generated documents have to agree, and they are produced
by different code: `vsm/ui/render.py` renders a screen, `vsm/modes/report.py`
writes a file a client receives. A term translated in one and not the other is
worse than translating neither, because the screen and the deliverable then
disagree about what the same figure is called.

`band` is banned from anything a reader sees. It means two unrelated things —
how wide a collection run is, and what kind of venue a site is — and two
meanings on one word is how a vocabulary rots.
"""

from __future__ import annotations

__all__ = ["SWEEP_SIZE", "MODE_LABEL"]

#: `spend_band` values, in words.
SWEEP_SIZE: dict[str, str] = {
    "probe": "Narrow",
    "standard": "Standard",
    "deep": "Wide",
}

#: Run modes as what the step does, not the internal verb.
MODE_LABEL: dict[str, str] = {
    "mine": "Collection",
    "insight": "Analysis",
    "report": "Report",
}
