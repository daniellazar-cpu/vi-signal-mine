"""How each theme is being talked about — split by who is talking.

Only 2-5% of conversation in a disease area comes from clinicians. A single
sentiment number over an unfiltered disease corpus is therefore a *patient*
sentiment number wearing a clinical label, and it is the most common way a
listening report says something untrue while every individual row is correct.

So :class:`ThemeStance` has no field for a blended figure. Not a policy anyone
has to remember — nowhere to put one.

The stance pass writes its own artifact and **never back-fills** the signal
row's ``sentiment``, which the miner deliberately leaves ``None``. A signal row
says what collection witnessed; a classification is a later opinion about it.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from vsm.analysis.authorclass import Resolver
from vsm.llm.prompts import STANCE_SYSTEM
from vsm.llm.schema import STANCE_SCHEMA

__all__ = ["STANCES", "ThemeStance", "classify_signals", "stance_for_themes"]

STANCES: tuple[str, ...] = ("positive", "negative", "mixed", "neutral", "unclear")


@dataclass(frozen=True)
class ThemeStance:
    theme_id: str
    #: author class → stance → count. Never summed across classes.
    by_class: dict[str, dict[str, int]]
    #: ``venue`` or ``identity`` — which resolver produced the classes above
    basis: str


def classify_signals(
    signals: Sequence[Mapping[str, Any]], *, client: Any | None
) -> dict[str, str]:
    """signal_id → stance. Everything is ``unclear`` when no classifier ran.

    ``unclear`` rather than ``neutral``: neutral is a finding about the text,
    and we did not look at the text.
    """
    if client is None or not signals:
        return {str(s["signal_id"]): "unclear" for s in signals}

    by_id = {str(s["signal_id"]): s for s in signals}
    listing = "\n".join(
        f"- {sid}: {str(s.get('excerpt') or s.get('theme') or '')[:400]}"
        for sid, s in by_id.items()
    )
    out = client.complete_structured(
        system=STANCE_SYSTEM,
        user=f"Classify the stance of each passage.\n\n{listing}",
        schema=STANCE_SCHEMA,
        max_output_tokens=4096,
    )
    result = {sid: "unclear" for sid in by_id}
    if not out.ok or not out.data:
        return result
    for item in out.data.get("items", []):
        sid = str(item.get("signal_id", ""))
        if sid in result:
            stance = str(item.get("stance", "")).strip().lower()
            # An unrecognised label is an abstention, not a new category.
            result[sid] = stance if stance in STANCES else "unclear"
    return result


def stance_for_themes(
    themes: Sequence[Any],
    signals: Sequence[Mapping[str, Any]],
    resolver: Resolver,
    *,
    client: Any | None = None,
) -> list[ThemeStance]:
    by_id = {str(s["signal_id"]): s for s in signals}
    stances = classify_signals(signals, client=client)
    classes = {sid: resolver.resolve(row) for sid, row in by_id.items()}
    basis = next((c.basis for c in classes.values()), "venue")

    results: list[ThemeStance] = []
    for theme in themes:
        buckets: dict[str, Counter] = defaultdict(Counter)
        for sid in theme.signal_ids:
            if sid not in by_id:
                continue
            buckets[classes[sid].value][stances.get(sid, "unclear")] += 1
        results.append(
            ThemeStance(
                theme_id=theme.theme_id,
                by_class={k: dict(v) for k, v in buckets.items()},
                basis=basis,
            )
        )
    return results
