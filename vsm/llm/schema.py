"""JSON schemas for every analysis pass, one per call.

Each schema sets ``additionalProperties: false`` and lists every property in
``required``. A schema that permits extra keys lets the model invent a field,
and the first thing it invents is a confidence score — which is exactly the
trust state this tool computes elsewhere and never lets the model author. See
``tests/test_llm.py::test_every_schema_forbids_extra_properties``.

The top-level key of each schema is load-bearing across later tasks and must
not be renamed: ``LEXICON_SCHEMA`` -> ``clusters``, ``THEMES_SCHEMA`` ->
``themes``, ``STANCE_SCHEMA`` -> ``items``, ``ANOMALY_NARRATION_SCHEMA`` ->
``notes``, ``REPORT_SCHEMA`` -> ``sections`` plus ``considerations``.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "LEXICON_SCHEMA",
    "THEMES_SCHEMA",
    "STANCE_SCHEMA",
    "ANOMALY_NARRATION_SCHEMA",
    "REPORT_SCHEMA",
]

#: The five stances a passage can be classified as. "unclear" is a first-class
#: value, not an absence of one — see ``vsm.llm.prompts.STANCE_SYSTEM``.
_STANCES: tuple[str, ...] = ("positive", "negative", "mixed", "neutral", "unclear")


def _no_extra(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


def _string_array() -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}}


# --------------------------------------------------------------------------- #
# Stage: lexicon expansion — a topic into search clusters                     #
# --------------------------------------------------------------------------- #

_LEXICON_CLUSTER = _no_extra(
    {
        "cluster_id": {"type": "string"},
        "label": {"type": "string"},
        "terms": _string_array(),
        "areas": _string_array(),
        "queries": _string_array(),
    },
    ["cluster_id", "label", "terms", "areas", "queries"],
)

LEXICON_SCHEMA: dict[str, Any] = _no_extra(
    {"clusters": {"type": "array", "items": _LEXICON_CLUSTER}},
    ["clusters"],
)

# --------------------------------------------------------------------------- #
# Stage: theme clustering — signal rows into named themes                     #
# --------------------------------------------------------------------------- #

_THEME = _no_extra(
    {
        "theme_id": {"type": "string"},
        "name": {"type": "string"},
        "signal_ids": _string_array(),
    },
    ["theme_id", "name", "signal_ids"],
)

THEMES_SCHEMA: dict[str, Any] = _no_extra(
    {"themes": {"type": "array", "items": _THEME}},
    ["themes"],
)

# --------------------------------------------------------------------------- #
# Stage: stance classification                                                #
# --------------------------------------------------------------------------- #

_STANCE_ITEM = _no_extra(
    {
        "signal_id": {"type": "string"},
        "stance": {"type": "string", "enum": list(_STANCES)},
        "rationale": {"type": "string"},
    },
    ["signal_id", "stance", "rationale"],
)

STANCE_SCHEMA: dict[str, Any] = _no_extra(
    {"items": {"type": "array", "items": _STANCE_ITEM}},
    ["items"],
)

# --------------------------------------------------------------------------- #
# Stage: anomaly narration — explaining a change already computed elsewhere   #
# --------------------------------------------------------------------------- #

_ANOMALY_NOTE = _no_extra(
    {
        "anomaly_id": {"type": "string"},
        "note": {"type": "string"},
    },
    ["anomaly_id", "note"],
)

ANOMALY_NARRATION_SCHEMA: dict[str, Any] = _no_extra(
    {"notes": {"type": "array", "items": _ANOMALY_NOTE}},
    ["notes"],
)

# --------------------------------------------------------------------------- #
# Stage: report writing                                                       #
# --------------------------------------------------------------------------- #

_REPORT_SECTION = _no_extra(
    {
        "heading": {"type": "string"},
        "body": {"type": "string"},
        "signal_ids": _string_array(),
    },
    ["heading", "body", "signal_ids"],
)

_CONSIDERATION = _no_extra(
    {
        "text": {"type": "string"},
        "signal_ids": _string_array(),
    },
    ["text", "signal_ids"],
)

REPORT_SCHEMA: dict[str, Any] = _no_extra(
    {
        "sections": {"type": "array", "items": _REPORT_SECTION},
        "considerations": {"type": "array", "items": _CONSIDERATION},
    },
    ["sections", "considerations"],
)
