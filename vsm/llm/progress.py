"""Where analysis-pass progress goes while a run is in flight.

Vendored from ``forum-engine``'s ``engine/llm/progress.py`` and reshaped: the
parent keys its registry by ``campaign_id`` and calls a sink with three
positional values (``asset_id, kind, value``) tied to article drafting. This
fork has one call shape (:meth:`vsm.llm.client.AnthropicClient.complete_structured`'s
``on_progress``), which reports a single event dict, so the registry is keyed
by ``run_id`` and ``publish`` takes one ``event`` payload instead of three
drafting-specific positional fields.

A process-level registry, keyed by run id, rather than something threaded
through run state, for the same two reasons the parent had:

* Run state is meant to be durable and serialisable; a callable stashed
  inside it is not a design choice, it is a crash the next time the run is
  saved.
* Progress is a *view* concern with the lifetime of one HTTP connection,
  whereas run state belongs to the run itself. Putting a browser's live feed
  into persisted state would confuse the two.

Registration is scoped with a context manager so a sink cannot outlive the
run that installed it. Nothing here may ever raise into a call: a browser
that disconnected mid-generation must not cost a paid completion.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

log = logging.getLogger(__name__)

__all__ = ["publish", "sink_for", "using_sink"]

#: ``run_id -> sink(event)``.
_SINKS: dict[str, Callable[[dict[str, Any]], None]] = {}
_LOCK = threading.Lock()


@contextmanager
def using_sink(run_id: str, sink: Callable[[dict[str, Any]], None]) -> Iterator[None]:
    """Install ``sink`` for ``run_id`` for the duration of the block."""
    if not run_id:
        yield
        return
    with _LOCK:
        previous = _SINKS.get(run_id)
        _SINKS[run_id] = sink
    try:
        yield
    finally:
        with _LOCK:
            if previous is None:
                _SINKS.pop(run_id, None)
            else:
                _SINKS[run_id] = previous


def sink_for(run_id: str) -> Callable[[dict[str, Any]], None] | None:
    with _LOCK:
        return _SINKS.get(run_id or "")


def publish(run_id: str, event: dict[str, Any]) -> None:
    """Report progress, swallowing anything the sink throws.

    Called from wherever an analysis pass is running, so it is both hot and
    untrusted. A sink that raises is logged once at debug and otherwise
    ignored — the analysis pass matters more than the animation.
    """
    sink = sink_for(run_id)
    if sink is None:
        return
    try:
        sink(event)
    except Exception:  # noqa: BLE001 - progress must never break a call
        log.debug("progress sink raised; continuing", exc_info=True)
