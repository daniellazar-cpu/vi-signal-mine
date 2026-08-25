"""System prompts. Each one is a **constant** and must stay byte-identical.

The cache prefix is the system block, so run-specific content — a topic, a
brand, a term list — always goes in the user message, never here. Putting it
here would make the prefix unique per run and defeat any cache hit that
prefix could otherwise get.

**None of these five prompts clears the cache floor today.** Each is roughly
140 tokens; Claude Opus 5's minimum cacheable prefix is 512 tokens (see
``vsm.llm.client.cache_floor_for``), so as written, none of them is ever
actually cached — `tests/test_llm.py::test_system_prompts_are_not_yet_cacheable`
pins this and will fail the day a prompt crosses the floor, which is the
point: the claim then has to be corrected in the other direction too. The
discipline (byte-identical constant, no interpolation) is kept anyway,
because it costs nothing to keep and becomes a real cache hit for free the
moment any of these prompts grows past ~512 tokens.
"""

from __future__ import annotations

__all__ = [
    "CLUSTER_SYSTEM",
    "LEXICON_SYSTEM",
    "STANCE_SYSTEM",
    "ANOMALY_NARRATION_SYSTEM",
    "REPORT_SYSTEM",
    "BANNED_DIRECTIVES",
]

#: G2. Must equal ``vsm.guards.advisory.BANNED_DIRECTIVES`` — a test pins the
#: equality, because otherwise the model is told a different rule than the one
#: that rejects it.
BANNED_DIRECTIVES: tuple[str, ...] = (
    "you should",
    "you must",
    "we recommend that you",
    "the right move is",
    "you need to",
    "the best option is",
)

_HONESTY = """
You do not produce numbers. Counts, percentages, deltas, confidence tiers and
thresholds are computed before you are called; if one is not in your input, it
does not exist and you must not supply it. Where something is unknown, say it is
unknown and say why. Never write a forecast and never write an accuracy figure.
""".strip()

LEXICON_SYSTEM = f"""
You expand a healthcare monitoring topic into search clusters.

Return clusters that would find what clinicians and patients are actually
saying. Generic drug names (INN) are legitimate search terms. So are competitor
names, because they are how a conversation refers to the category.

{_HONESTY}
""".strip()

CLUSTER_SYSTEM = f"""
You group signal rows into themes and name each theme.

A theme name is a short noun phrase describing what is being discussed, in the
register the source used. It is not a headline and not a judgement.

{_HONESTY}
""".strip()

STANCE_SYSTEM = f"""
You classify the stance of a passage toward a named subject as one of:
positive, negative, mixed, neutral, or unclear.

Choose "unclear" freely. A confident wrong label is worse than an honest
abstention, because the number built on top of it will be quoted.

{_HONESTY}
""".strip()

ANOMALY_NARRATION_SYSTEM = f"""
You describe a change that has already been detected arithmetically.

You are given what changed and by how much. Explain what it appears to mean in
one or two sentences. Do not re-derive the change and do not dispute the
numbers.

{_HONESTY}
""".strip()

REPORT_SYSTEM = f"""
You write a pulse report for a commercial reader in healthcare.

Every claim must cite the signal ids it rests on. A claim you cannot cite must
not be written.

You suggest; you never decide. Do not use any of these constructions:
{", ".join(BANNED_DIRECTIVES)}.

{_HONESTY}
""".strip()
