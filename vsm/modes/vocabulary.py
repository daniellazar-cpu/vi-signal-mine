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


#: How well-supported a finding is, said as the count rather than as a category.
#:
#: "Corroborated" was a word invented in this codebase and surfaced raw; the
#: owner's reaction to meeting it was "wtf is Corroborated". The count is the
#: label, so there is nothing to learn: three sources is three sources.
SOURCE_LABEL: dict[str, str] = {
    "corroborated": "3+ sources",
    "emerging": "2 sources",
    "single_source": "1 source",
}

#: What each count means for what you may say, stated once as a legend rather
#: than repeated per row. Advisory, never an instruction (guard G2).
SOURCE_ADVICE: dict[str, str] = {
    "corroborated": "safe to state as-is",
    "emerging": "attribute it",
    "single_source": "quote it, don't generalise",
}
