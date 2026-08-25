"""The model seam: one schema-injected completion per analysis pass.

Vendored from the sibling ``forum-engine`` repo's ``engine/llm/`` and
reshaped. The parent hard-codes two output schemas (an article, a query plan)
behind two entry points (``draft``, ``plan_queries``). This tool runs five
different analysis passes over the same shape instead — a byte-stable system
prompt, a run-specific user message, an injected JSON schema — so there is one
entry point: :meth:`~vsm.llm.client.AnthropicClient.complete_structured`.

* :class:`~vsm.llm.client.AnthropicClient` — the client. Hand-rolled retry
  loop (never the SDK's own ``max_retries``, which billed retried-away
  attempts invisibly), per-attempt metering, a spend cap re-checked between
  attempts, and the prompt-cache prefix check.
* :func:`~vsm.llm.client.get_client` — the offline/live seam. ``VSM_OFFLINE=1``
  is the master switch and wins over ``VSM_DRAFTER``; live without a key
  raises rather than silently generating nothing.
* :mod:`~vsm.llm.prompts` — one byte-stable system prompt per pass. Never
  interpolate run-specific content into one of these; that is what the user
  message is for, and it is the entire reason the prefix is cacheable.
* :mod:`~vsm.llm.schema` — one JSON schema per pass, each closed
  (``additionalProperties: false``) so the model cannot invent a field the
  rest of this tool has to treat as trustworthy.
* :mod:`~vsm.llm.progress` — a run-keyed progress registry, scoped by a
  context manager so a sink cannot outlive the run that installed it.

Every client takes an injectable ``sdk`` so this package is testable with zero
network — see ``tests/test_llm.py``.
"""

from __future__ import annotations

from vsm.llm.client import (
    AnthropicClient,
    LlmSpend,
    StructuredOutcome,
    cache_floor_for,
    get_client,
    prefix_is_cacheable,
    worst_case_usd,
)

__all__ = [
    "AnthropicClient",
    "StructuredOutcome",
    "LlmSpend",
    "get_client",
    "worst_case_usd",
    "cache_floor_for",
    "prefix_is_cacheable",
]
