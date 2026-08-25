"""The Anthropic client, behind the same offline/live seam as ``vsm.mining``.

Vendored from the sibling ``forum-engine`` repo's ``engine/llm/client.py`` and
reshaped: the parent hard-codes two output schemas (an article, a query plan)
behind two entry points (``draft``, ``plan_queries``). This tool runs five
different analysis passes (lexicon expansion, theme clustering, stance,
anomaly narration, report writing) that all share one shape — one call, one
injected system/user prompt, one injected JSON schema — so there is exactly
one entry point here: :meth:`AnthropicClient.complete_structured`.

Design rules this file follows, carried over unchanged from the parent because
they were already learned there the hard way:

* **Offline never calls out.** ``get_client`` never reads a key or opens a
  socket while ``VSM_OFFLINE=1``. A dry run is a true rehearsal of a paid run.
* **Live without a key is an error, not a downgrade.** A run that silently
  stopped generating would look identical, from the outside, to one that
  generated. ``get_client`` raises and names the variable instead.
* **Cost is recorded per call, and per *attempt*, and checked against a cap
  before spending.** Every HTTP attempt that may have been billed lands in the
  ledger — exactly, from a usage block, or as a flagged estimate when the
  usage block never arrived. The retry loop is ours, not the SDK's own
  ``max_retries``, because a retried-away attempt that reached the model was
  billed and invisible to a ledger that only sees the final response: three
  generations could log as one, or as $0.00 on the failure paths. See
  :meth:`AnthropicClient.complete_structured` and :class:`_AttemptMeter`.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Protocol

from vsm.config import Settings, get_settings
from vsm.errors import BudgetExceeded, ConfigError

log = logging.getLogger(__name__)

__all__ = [
    "AnthropicClient",
    "StructuredOutcome",
    "LlmSpend",
    "cache_floor_for",
    "get_client",
    "prefix_is_cacheable",
    "worst_case_usd",
]

#: Per-million-token rates for the model, used to record spend. These are the
#: published Claude Opus 5 rates. They are a *record*, not a bill — the
#: authoritative number is Anthropic's own usage reporting, and this exists so
#: a run can be stopped before it overspends and so a run can show what it
#: cost.
_RATE_IN_PER_M = 5.00
_RATE_OUT_PER_M = 25.00
_RATE_CACHE_READ_PER_M = 0.50   # ~0.1x input
_RATE_CACHE_WRITE_PER_M = 6.25  # ~1.25x input

#: Chars per token when *estimating* an unmetered bill. English prose runs
#: about 3.7-4.0; 3.0 deliberately over-counts. Every use of this number is a
#: bill we could not read, and an estimate that under-states an unreadable
#: bill repeats the error it exists to fix.
_EST_CHARS_PER_TOKEN = 3.0

#: Chars per token when asking "is this prompt long enough to cache?". The
#: opposite bias to the one above: over-counting there is safe, over-counting
#: here would let us claim a prefix caches when it does not.
_CACHE_CHARS_PER_TOKEN = 4.0

#: Minimum cacheable prefix, in tokens, per model. Below it the API silently
#: does not cache — no error, no warning, just a bill several times what the
#: operator thinks it is. ``VSM_LLM_MODEL`` is env-settable and the floor is
#: **not monotonic across generations** (512 on the newest models, 4096 on
#: Opus 4.6 and Haiku 4.5), so pointing this tool at an older model turns off
#: the caching the whole prompt split was designed around.
_CACHE_MIN_PREFIX_TOKENS: dict[str, int] = {
    "claude-opus-5": 512,
    "claude-fable-5": 512,
    "claude-mythos-5": 512,
    "claude-opus-4-8": 1024,
    "claude-sonnet-5": 1024,
    "claude-sonnet-4-6": 1024,
    "claude-sonnet-4-5": 1024,
    "claude-opus-4-7": 2048,
    "claude-opus-4-6": 4096,
    "claude-opus-4-5": 4096,
    "claude-haiku-4-5": 4096,
}

#: HTTP attempts per call, matching what the SDK's ``max_retries=2`` default
#: gave us — same billing and wall-clock envelope as before, but every attempt
#: metered.
_MAX_ATTEMPTS = 3

#: Statuses that mean the request was rejected *before* the model ran, so $0
#: is the honest record rather than an under-count. 429 and 529 are admission
#: control; 4xx are validation and auth. None of them sample the model.
_UNBILLED_STATUSES = frozenset({400, 401, 403, 404, 413, 422, 429, 529})

#: Statuses worth another attempt. Same set the SDK retries.
_RETRY_STATUSES = frozenset({408, 409, 429, 500, 502, 503, 504, 529})

#: Longest we will honour a ``retry-after`` header. A stage that blocks for
#: minutes on a header value is a hung run, not a polite client.
_MAX_RETRY_AFTER_S = 8.0


class UsageLike(Protocol):
    """The shape of an Anthropic ``Usage`` block, without importing the SDK.

    Every field is still read through ``getattr`` in :meth:`LlmSpend.record`,
    because the usage object hanging off a mid-stream *snapshot* carries only
    the fields that have arrived so far — the cache counters in particular are
    absent until the terminal ``message_delta``.
    """

    input_tokens: int
    output_tokens: int


@dataclass
class LlmSpend:
    """Accumulated model spend for one run.

    ``calls`` is meant to be usable as a cross-check against Anthropic's own
    usage reporting, which is why :meth:`record` refuses to count a call it
    was handed no usage for. ``estimated_calls`` / ``estimated_usd`` separate
    the part of the total we read from the part we had to guess, so a reader
    can tell them apart instead of trusting a single blended number.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    calls: int = 0
    estimated_calls: int = 0
    estimated_usd: float = 0.0

    @property
    def usd(self) -> float:
        return round(
            self.input_tokens / 1_000_000 * _RATE_IN_PER_M
            + self.output_tokens / 1_000_000 * _RATE_OUT_PER_M
            + self.cache_read_tokens / 1_000_000 * _RATE_CACHE_READ_PER_M
            + self.cache_write_tokens / 1_000_000 * _RATE_CACHE_WRITE_PER_M,
            6,
        )

    @property
    def estimated(self) -> bool:
        """True when any part of ``usd`` was estimated rather than metered."""
        return self.estimated_calls > 0

    def record(self, usage: UsageLike | None) -> float:
        """Add one metered call. Returns the USD it added.

        ``None`` records **nothing** and returns 0.0. It used to increment
        ``calls`` and add zero tokens, which made ``calls`` useless as a
        ledger cross-check: a response with no usage block would otherwise
        book a phantom call. The guard belongs here, once, so every caller
        behaves the same way.
        """
        if usage is None:
            return 0.0
        before = self.usd
        self.calls += 1
        self.input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
        self.output_tokens += int(getattr(usage, "output_tokens", 0) or 0)
        self.cache_read_tokens += int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        self.cache_write_tokens += int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        return round(self.usd - before, 6)

    def record_estimate(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> float:
        """Book a call whose usage block never arrived. Returns the USD it added.

        Counts against ``calls`` like any other call, because the call
        happened — and separately against ``estimated_calls``, so nobody
        mistakes the number for something Anthropic told us.
        """
        before = self.usd
        self.calls += 1
        self.estimated_calls += 1
        self.input_tokens += max(0, int(input_tokens))
        self.output_tokens += max(0, int(output_tokens))
        self.cache_read_tokens += max(0, int(cache_read_tokens))
        self.cache_write_tokens += max(0, int(cache_write_tokens))
        added = round(self.usd - before, 6)
        self.estimated_usd = round(self.estimated_usd + added, 6)
        return added

    def as_dict(self) -> dict[str, Any]:
        """The ledger as JSON, for a run artifact.

        ``estimated`` is part of the payload on purpose: a cost line that
        mixes metered and guessed dollars without saying so is the same class
        of lie as an unlabelled analytics console.
        """
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "usd": self.usd,
            "estimated_calls": self.estimated_calls,
            "estimated_usd": self.estimated_usd,
            "estimated": self.estimated,
        }


@dataclass
class StructuredOutcome:
    """One structured completion, and what it cost whether or not it worked."""

    ok: bool
    data: dict[str, Any] | None
    spend: LlmSpend
    reason: str = ""


# --------------------------------------------------------------------------- #
# cost estimation and the cacheable-prefix floor                              #
# --------------------------------------------------------------------------- #


def worst_case_usd(*, prompt_chars: int, max_output_tokens: int) -> float:
    """The most one call can possibly cost, given the published rates.

    Input is priced at the cache-*write* rate, which is the expensive case
    (the first call of a run writes the prefix it later reads), and output at
    the full ``max_tokens`` ceiling, which the model cannot exceed. This is
    what makes the cap a ceiling instead of a tripwire — see
    ``AnthropicClient._check_budget``.
    """
    tokens_in = math.ceil(max(0, prompt_chars) / _EST_CHARS_PER_TOKEN)
    return round(
        tokens_in / 1_000_000 * _RATE_CACHE_WRITE_PER_M
        + max(0, max_output_tokens) / 1_000_000 * _RATE_OUT_PER_M,
        6,
    )


def cache_floor_for(model: str) -> int | None:
    """Minimum cacheable prefix for ``model`` in tokens, or ``None`` if unknown."""
    return _CACHE_MIN_PREFIX_TOKENS.get((model or "").strip().lower())


def prefix_is_cacheable(model: str, prompt: str) -> bool | None:
    """Whether ``prompt`` is long enough to be cached on ``model``.

    ``None`` means the model is not in the table and the answer is unknown —
    an unknown model is reported as unknown rather than assumed fine.
    """
    floor = cache_floor_for(model)
    if floor is None:
        return None
    return len(prompt) / _CACHE_CHARS_PER_TOKEN >= floor


# --------------------------------------------------------------------------- #
# metering one HTTP attempt                                                   #
# --------------------------------------------------------------------------- #


@dataclass
class _AttemptMeter:
    """What one HTTP attempt is known to have consumed — readable after a crash.

    This exists because the interesting failures happen *mid-generation*: a
    read timeout, a dropped connection, a 529 arriving as a stream error. In
    all of those the tokens were generated and billed, and the terminal
    ``message_delta`` that carries the usage block never arrives. A handler
    that returns without touching ``usage`` at all would record $0.00 against
    a real bill.

    So a caller writes what it knows *into this object as it goes* — the
    SDK's mid-stream snapshot (which carries input tokens from
    ``message_start``) and the byte count actually received — and reads it
    whether the attempt finished or exploded.
    """

    prompt_chars: int = 0
    received_chars: int = 0
    #: Usage off the finished message. Authoritative only when ``truncated``
    #: is False — see below.
    usage: Any = None
    #: Partial usage off the SDK's accumulating snapshot. Input tokens are
    #: real; output tokens are whatever had been reported, usually zero.
    snapshot_usage: Any = None
    #: The stream ended without a terminal ``message_delta``. A non-streaming
    #: ``create`` call leaves this ``False`` unconditionally.
    truncated: bool = False

    def estimate(self) -> dict[str, int]:
        """A pessimistic token estimate for an attempt with no usable usage block.

        Input comes from whatever usage did arrive when the request got far
        enough to report any, and from the prompt length otherwise — charged
        as uncached input, which is the expensive reading. Output is the
        larger of what was reported and what was actually received, because
        bytes on the wire are proof of generation and a reported zero next to
        received text is a partial count.
        """
        known = self.usage if self.usage is not None else self.snapshot_usage
        got_in = int(getattr(known, "input_tokens", 0) or 0)
        got_out = int(getattr(known, "output_tokens", 0) or 0)
        got_read = int(getattr(known, "cache_read_input_tokens", 0) or 0)
        got_write = int(getattr(known, "cache_creation_input_tokens", 0) or 0)
        if got_in or got_read or got_write:
            tokens_in = got_in
        else:
            tokens_in = math.ceil(self.prompt_chars / _EST_CHARS_PER_TOKEN)
        return {
            "input_tokens": tokens_in,
            "output_tokens": max(got_out, math.ceil(self.received_chars / _EST_CHARS_PER_TOKEN)),
            "cache_read_tokens": got_read,
            "cache_write_tokens": got_write,
        }


def _status_of(exc: BaseException) -> int | None:
    """HTTP status behind an SDK exception, or ``None`` for a transport failure.

    Read by attribute rather than by ``isinstance`` so this module keeps its
    lazy ``anthropic`` import: ``APIStatusError`` carries ``status_code``, the
    connection and timeout errors do not.
    """
    status = getattr(exc, "status_code", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


def _may_have_been_billed(exc: BaseException, meter: _AttemptMeter) -> bool:
    """Whether this failure could have cost money.

    Deliberately asymmetric: a false positive over-states the bill by a few
    cents, a false negative is the bug this whole path exists to fix.
    """
    if meter.received_chars or meter.snapshot_usage is not None:
        return True  # tokens reached us, so they were generated, so they were billed
    status = _status_of(exc)
    if status is None:
        # Transport-level. A read timeout can sit on the far side of a
        # complete generation we simply never received.
        return True
    return status not in _UNBILLED_STATUSES


def _snapshot_usage(stream: Any) -> Any:
    """The usage block off a live stream's accumulating snapshot, or ``None``.

    ``current_message_snapshot`` asserts rather than returning ``None``
    before the first ``message_start``, and this runs in a ``finally`` on the
    failure path, so it swallows everything: losing the estimate is bad,
    replacing the real exception with an ``AssertionError`` from the
    accounting code is worse.

    Unused today — ``complete_structured`` calls ``messages.create``, not
    ``messages.stream``, so there is no live stream to snapshot. Retained
    verbatim for a future streaming path over the same schema-constrained
    call; a mid-stream failure needs exactly this partial-usage read to avoid
    booking a real generation as free.
    """
    try:
        return getattr(stream.current_message_snapshot, "usage", None)
    except Exception:  # noqa: BLE001
        return None


def _without_sdk_retries(client: Any) -> Any:
    """Strip SDK-internal retries from an injected client.

    ``with_options`` returns a copy sharing the same HTTP client, so this is
    cheap and does not disturb a test's ``MockTransport``. A hand-rolled
    double without the method is returned unchanged.
    """
    with_options = getattr(client, "with_options", None)
    if with_options is None:
        return client
    try:
        return with_options(max_retries=0)
    except Exception:  # noqa: BLE001 - a double that has the name but not the kwarg
        log.debug("could not disable SDK retries on the injected client", exc_info=True)
        return client


#: Enumerated failure reasons, and the safe sentence each one shows. These,
#: and never an exception string, are what leaves this module: an
#: ``anthropic.APIStatusError`` renders with the request URL and the
#: organisation id inside it, and a failure reason can travel into a run
#: artifact that is not a safe place for either. The raw detail is logged
#: server-side instead. The code comes first in each string so it stays
#: greppable in a log and in an artifact.
_REASONS: dict[str, str] = {
    "auth_error": "auth_error — the API rejected our credentials",
    "rate_limited": "rate_limited — the API rate limit was reached",
    "invalid_request": "invalid_request — the API rejected the shape of the request",
    "server_error": "server_error — the API returned a server error",
    "transport_error": "transport_error — the request never completed",
    "api_error": "api_error — the API call failed",
}


def _reason_for(exc: BaseException) -> str:
    """One of :data:`_REASONS`, chosen from the HTTP status behind ``exc``.

    Status-driven rather than ``isinstance``-driven for the same reason
    :func:`_status_of` is: it keeps the lazy ``anthropic`` import.
    """
    status = _status_of(exc)
    if status is None:
        return _REASONS["transport_error"]
    if status in (401, 403):
        return _REASONS["auth_error"]
    if status == 429:
        return _REASONS["rate_limited"]
    if status in (400, 404, 413, 422):
        return _REASONS["invalid_request"]
    if 500 <= status < 600:
        return _REASONS["server_error"]
    return _REASONS["api_error"]


def _is_retryable(exc: BaseException, meter: _AttemptMeter) -> bool:
    """Whether another attempt is worth making.

    A partially-received response is **not** retried. Nothing can resume a
    stream, so retrying means paying for a whole second generation to replace
    one that may have been nearly complete — and the SDK's own retries never
    fired mid-body either, so this keeps the cost envelope we already had.
    """
    if meter.received_chars:
        return False
    status = _status_of(exc)
    if status is None:
        return True
    return status in _RETRY_STATUSES


def _tool_for(schema: dict[str, Any]) -> dict[str, Any]:
    """Force structured output by making it the only thing the model can emit."""
    return {
        "name": "emit",
        "description": "Emit the result. This is the only permitted output.",
        "input_schema": schema,
    }


# --------------------------------------------------------------------------- #
# the client                                                                  #
# --------------------------------------------------------------------------- #


class AnthropicClient:
    """One schema-constrained completion at a time, against the Anthropic API.

    ``sdk`` is injectable so tests can pass an ``Anthropic`` built over an
    ``httpx.MockTransport`` and exercise this class for real without a
    network — the same approach ``vsm.mining`` uses for its hermetic tests.
    """

    provider = "anthropic"

    def __init__(
        self,
        *,
        sdk: Any,
        model: str,
        cap_usd: float | None = None,
        retry_backoff_s: float = 0.5,
    ) -> None:
        # An injected sdk must not retry behind our back — see the note on
        # ``max_retries`` in ``get_client``. Tests inject a double built over
        # an ``httpx.MockTransport``, and SDK-internal retries there would
        # hide attempts from the ledger exactly as they do in production.
        self._sdk = _without_sdk_retries(sdk)
        self._model = model
        self._cap_usd_setting = cap_usd
        self._spend = LlmSpend()
        # Base delay for our own retries. Zero is for tests; production waits.
        self._retry_backoff_s = max(0.0, float(retry_backoff_s))
        self._max_attempts = _MAX_ATTEMPTS

    # ------------------------------------------------------------------ ledger
    @property
    def spend(self) -> LlmSpend:
        """The cumulative ledger for this client's whole life.

        Public because callers need the *run* total, not the per-call figure on
        a single StructuredOutcome — INSIGHT makes several calls and records one
        cost. Read it directly; never through `getattr` with a default, because
        a zero from a renamed attribute reads exactly like a run that spent
        nothing.
        """
        return self._spend

    # ------------------------------------------------------------- lifecycle
    def close(self) -> None:
        """Release the HTTP connection pool.

        ``sdk`` is always handed in — either by a caller directly, or by
        :func:`get_client`, which builds one fresh Anthropic client per call
        and hands it over. Either way this instance is the sole owner of its
        connection pool: unlike the vendored parent, there is no
        ``_owns_client`` guard here, so ``close`` always attempts to close
        whatever ``sdk`` was passed in. Handing this class an ``sdk`` you
        still need open elsewhere is a caller error, not something this class
        can detect.
        """
        closer = getattr(self._sdk, "close", None)
        if closer is None:  # pragma: no cover - every real client has one
            return
        try:
            closer()
        except Exception:  # noqa: BLE001 - a failed close must not fail a run
            log.debug("closing the Anthropic client raised; continuing", exc_info=True)

    def __enter__(self) -> AnthropicClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # ---------------------------------------------------------------- budget
    def _cap_usd(self) -> float | None:
        """The configured ceiling, or ``None`` for unlimited.

        * ``0``      → spend nothing. A hard zero, honoured as written.
        * negative   → unlimited. The sentinel, because the setting is a
                       float and there is no other value that cannot also be
                       a real budget.
        * ``None``   → unlimited. Unset, same meaning as negative.
        """
        raw = self._cap_usd_setting
        if raw is None:
            return None
        cap = float(raw)
        return None if cap < 0 else cap

    def _check_budget(self, reserve_usd: float = 0.0) -> str | None:
        """Refuse now if the call about to be made could breach the cap.

        ``reserve_usd`` is the worst case for that one call, reserved
        *before* it runs. Testing ``self._spend.usd >= cap`` would only
        fire once spend has already gone over — a tripwire, not a ceiling,
        and one call could overshoot by its own full cost. Reserving instead
        makes the recorded total unable to pass the cap at all, with one
        caveat worth stating plainly: the guarantee is only as good as the
        rate constants at the top of this file. If Anthropic's published
        rates change and these do not, the reserve is wrong by the same
        factor.

        A cap smaller than one call's worst case therefore permits no calls.
        That is the correct reading of the number, and the message says so
        rather than letting a run look mysteriously idle.
        """
        cap = self._cap_usd()
        if cap is None:
            return None
        if cap <= 0:
            return (
                "model spend cap is $0.00 (VSM_RUN_COST_CAP_USD=0): no model call "
                "may be made. Unset it, or set it negative, for no cap."
            )
        if self._spend.usd + reserve_usd > cap:
            return (
                f"model spend cap would be breached: ${self._spend.usd:.4f} spent of "
                f"${cap:.2f} (VSM_RUN_COST_CAP_USD) after {self._spend.calls} call(s), "
                f"and this call reserves up to ${reserve_usd:.4f}"
            )
        return None

    # ----------------------------------------------------------- attempt cost
    def _meter_attempt(
        self, meter: _AttemptMeter, exc: BaseException | None = None
    ) -> tuple[float, bool]:
        """Book one HTTP attempt. Returns ``(usd, was_estimated)``.

        Called on both the success and the failure path, because an attempt
        that finished cleanly but carried no usage block — or with a usage
        block off a truncated stream — is the same accounting hole as one
        that crashed.
        """
        if meter.usage is not None and not meter.truncated:
            return self._spend.record(meter.usage), False
        if exc is not None and not _may_have_been_billed(exc, meter):
            # Rejected before the model ran: $0 is the honest number here,
            # not an under-count. Do not inflate it.
            return 0.0, False
        if exc is not None:
            reason = f"{type(exc).__name__}: {exc}"
        elif meter.truncated:
            reason = "stream ended before its final usage block"
        else:
            reason = "response carried no usage block"
        estimate = meter.estimate()
        usd = self._spend.record_estimate(**estimate)
        log.warning(
            "no usable usage block for this attempt (%s) — recording an ESTIMATE of "
            "$%.4f (~%d in / ~%d out tokens) rather than $0.00",
            reason,
            usd,
            estimate["input_tokens"],
            estimate["output_tokens"],
        )
        return usd, True

    def _sleep_before_retry(self, attempt: int, exc: BaseException) -> None:
        if self._retry_backoff_s <= 0:
            return
        delay = self._retry_backoff_s * (2 ** (attempt - 1))
        after = getattr(getattr(exc, "response", None), "headers", None)
        if after is not None:
            try:
                delay = max(delay, float(after.get("retry-after") or 0))
            except (TypeError, ValueError):
                pass
        time.sleep(min(delay, _MAX_RETRY_AFTER_S))

    # -------------------------------------------------------- structured call
    def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        max_output_tokens: int,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> StructuredOutcome:
        """One schema-constrained completion, under the same retry and
        metering loop the parent uses.

        ``system`` is sent as a cache-controlled block. It **must** be
        byte-identical across runs or the prefix is unique per run and the
        cache never hits — which is why run-specific content belongs in
        ``user``.

        The budget is checked at the top of *every* attempt, not once before
        the loop: a cap that only gated the first attempt let the remaining
        ones spend past it with nothing to stop them. The first attempt still
        raises ``BudgetExceeded`` — the existing pre-flight contract, checked
        before anything has been spent — but a cap that binds *between*
        attempts, after real spend has already happened, returns a failed
        ``StructuredOutcome`` instead: a run already in flight reports why it
        stopped rather than raising out from under whatever called it.
        """
        prompt_chars = len(system) + len(user)
        reserve = worst_case_usd(prompt_chars=prompt_chars, max_output_tokens=max_output_tokens)

        last_reason = ""
        for attempt in range(1, self._max_attempts + 1):
            blocked = self._check_budget(reserve_usd=reserve)
            if blocked:
                if attempt == 1:
                    raise BudgetExceeded(blocked, rule="G3")
                return StructuredOutcome(False, None, self._spend, blocked)
            meter = _AttemptMeter(prompt_chars=prompt_chars)
            try:
                message = self._sdk.messages.create(
                    model=self._model,
                    max_tokens=max_output_tokens,
                    system=[
                        {
                            "type": "text",
                            "text": system,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    messages=[{"role": "user", "content": user}],
                    tools=[_tool_for(schema)],
                    tool_choice={"type": "tool", "name": "emit"},
                )
            except Exception as exc:  # noqa: BLE001 - reported, never raised through
                self._meter_attempt(meter, exc)
                last_reason = _reason_for(exc)
                if not _is_retryable(exc, meter) or attempt == self._max_attempts:
                    return StructuredOutcome(False, None, self._spend, last_reason)
                self._sleep_before_retry(attempt, exc)
                continue

            # Meter through the same fall-through as every other attempt: a
            # response with no usage block must book a flagged estimate, not
            # nothing. Recording ``usage`` directly with ``LlmSpend.record``
            # would have silently booked $0.00 for a generation that may well
            # have been billed.
            meter.usage = getattr(message, "usage", None)
            self._meter_attempt(meter)
            for block in getattr(message, "content", []) or []:
                if getattr(block, "type", "") == "tool_use":
                    data = dict(getattr(block, "input", {}) or {})
                    if on_progress:
                        try:
                            on_progress({"event": "structured_done", "keys": sorted(data)})
                        except Exception:  # noqa: BLE001 - progress must never break a call
                            log.debug("progress callback raised; continuing", exc_info=True)
                    return StructuredOutcome(True, data, self._spend)
            last_reason = "model returned no tool_use block"
            if attempt == self._max_attempts:
                return StructuredOutcome(False, None, self._spend, last_reason)
            self._sleep_before_retry(attempt, RuntimeError(last_reason))
        return StructuredOutcome(False, None, self._spend, last_reason)


# --------------------------------------------------------------------------- #
# the seam                                                                    #
# --------------------------------------------------------------------------- #


def get_client(settings: Settings | None = None) -> AnthropicClient | None:
    """The client, or ``None`` when generation is off.

    ``VSM_DRAFTER=llm`` without a key **raises**. It does not fall back: a
    run that quietly stopped generating and returned nothing looks exactly
    like one that generated nothing worth returning.
    """
    s = settings or get_settings()
    mode = s.effective_drafter_mode()
    if mode == "off":
        if s.drafter_mode == "llm" and not s.offline:
            raise ConfigError(
                "VSM_DRAFTER=llm but ANTHROPIC_API_KEY is unset", rule="llm"
            )
        return None
    if not s.anthropic_api_key:
        raise ConfigError("VSM_DRAFTER=llm but ANTHROPIC_API_KEY is unset", rule="llm")
    import anthropic  # imported at call time, not module scope

    return AnthropicClient(
        sdk=_without_sdk_retries(anthropic.Anthropic(api_key=s.anthropic_api_key)),
        model=s.llm_model,
        cap_usd=s.run_cost_cap_usd,
    )
