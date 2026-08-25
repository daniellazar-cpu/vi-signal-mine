"""Rung 2 — mention to entity, so a count means something.

"Symproic", "naldemedine" and a bare mention of the molecule are one node, not
three. Without this a volume figure is a word-frequency table wearing a product
name, which is the failure mode the research file describes as rung 0.

Matching is **whole-word and case-insensitive**. Substring matching is how a
brand monitor starts reporting on an unrelated product that happens to contain
the brand's letters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping, Sequence

from vsm.topics.model import Topic

__all__ = ["Entity", "build_lexicon", "resolve_signals"]

Role = Literal["ours", "competitor", "class", "unmapped"]

_SEARCHED_FIELDS = ("theme", "excerpt", "title", "description")


@dataclass(frozen=True)
class Entity:
    entity_id: str
    canonical: str
    role: Role
    #: lower-cased; every string that means this entity
    aliases: tuple[str, ...]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def build_lexicon(topic: Topic) -> list[Entity]:
    """Topic → the entities worth resolving against.

    The brand and the molecule are **one** entity: they name the same product,
    and splitting them would halve every count about it.
    """
    entities: list[Entity] = []
    ours = [t for t in (topic.brand, topic.molecule) if t]
    if ours:
        entities.append(
            Entity(
                entity_id=f"ent-{_slug(ours[0])}",
                canonical=ours[0],
                role="ours",
                aliases=tuple(sorted({t.lower() for t in ours})),
            )
        )
    for competitor in topic.competitors:
        entities.append(
            Entity(
                entity_id=f"ent-{_slug(competitor)}",
                canonical=competitor,
                role="competitor",
                aliases=(competitor.lower(),),
            )
        )
    return entities


def _haystack(signal: Mapping[str, Any]) -> str:
    parts = [str(signal.get(f) or "") for f in _SEARCHED_FIELDS]
    return " ".join(parts).lower()


def _matches(haystack: str, alias: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", haystack) is not None


def resolve_signals(
    signals: Sequence[Mapping[str, Any]], entities: Iterable[Entity]
) -> dict[str, Any]:
    entities = list(entities)
    by_signal: dict[str, list[str]] = {}
    unmapped: list[str] = []
    for signal in signals:
        sid = str(signal["signal_id"])
        haystack = _haystack(signal)
        hits = [
            e.entity_id
            for e in entities
            if any(_matches(haystack, alias) for alias in e.aliases)
        ]
        by_signal[sid] = hits
        if not hits:
            # Recorded, never dropped: a signal that matched nothing is a fact
            # about our lexicon as much as about the signal.
            unmapped.append(sid)
    return {
        "entities": [
            {"entity_id": e.entity_id, "canonical": e.canonical,
             "role": e.role, "aliases": list(e.aliases)}
            for e in entities
        ],
        "by_signal": by_signal,
        "unmapped_mentions": unmapped,
    }
