"""The one HTTP surface every Bright Data product here shares.

Auth and endpoints per the vendor docs bundled with the ``brightdata-plugin``
skill (``bright-data-best-practices``, ``discover-api``), July 2026:

* ``POST https://api.brightdata.com/request`` — Web Unlocker **and** SERP API.
  Body ``{"zone", "url", "format", …}``.
* ``POST/GET https://api.brightdata.com/discover`` — Discover API
  (trigger → ``task_id`` → poll until ``status == "done"``).
* Header ``Authorization: Bearer <BRIGHTDATA_API_KEY>`` on all of them.

Documented error codes handled below: ``400`` bad body, ``401`` bad key, ``403``
product not enabled on the account, ``404`` expired ``task_id``, ``429`` rate or
concurrency limit, ``5xx`` service. ``429``/``5xx`` retry with linear backoff, and
so does a ``200`` with an empty body or a "recently failed, try again after N
seconds" text body, both of which SERP returns intermittently (seen live, September
2026), the latter after the N seconds it names; everything else raises immediately, because retrying a ``401``
just burns time.

Offline posture matches the parent's analogous ``engine.measurement.oec.HttpClaimsOutcomeSource``:
a client refuses to build a real transport while ``VSM_OFFLINE=1``, but an
injected ``transport`` (``httpx.MockTransport``) is always allowed — that is how
the package is tested with zero network.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any, Callable, Mapping

from vsm.config import Settings, get_settings
from vsm.errors import ConfigError, VsmError

__all__ = [
    "BRIGHTDATA_BASE_URL",
    "BrightDataError",
    "BrightDataAuthError",
    "BrightDataRateLimited",
    "BrightDataClient",
]

BRIGHTDATA_BASE_URL = "https://api.brightdata.com"

#: Identify ourselves honestly. No anti-detect anything (PRD §9.1 "explicitly not built").
USER_AGENT = "AttendingHealthForumEngine/1.0 (+stage-2 signal mining; contact: ops@attendinghealth.example)"


class BrightDataError(VsmError):
    """A Bright Data call failed. Carries the HTTP status when there was one."""

    default_message = "Bright Data request failed"

    def __init__(self, message: str = "", *, status: int | None = None, **context: Any) -> None:
        super().__init__(message or self.default_message, **context)
        self.status = status


class BrightDataAuthError(BrightDataError):
    """401/403 — the key is missing, wrong, or the product is not enabled."""

    default_message = "Bright Data rejected the credentials (401/403)"


class BrightDataRateLimited(BrightDataError):
    """429 — rate or concurrency limit, after the retry budget is spent."""

    default_message = "Bright Data rate limit (429) survived the retry budget"


_RETRY_AFTER = re.compile(rb"recently failed.{0,200}?minimum of (\d+) seconds", re.S)


def _retry_after_from_body(response: Any) -> float | None:
    """Seconds a 2xx "this query recently failed" body asks us to wait, else None."""
    m = _RETRY_AFTER.search(response.content[:400])
    return float(m.group(1)) if m else None


_THROTTLED = re.compile(rb"auto-throttled.{0,200}?request rate to (\d+)\s*/\s*min", re.S)


def _throttle_rate_from_body(response: Any) -> int | None:
    """Requests per minute a 2xx "auto-throttled" body asks for, else None."""
    m = _THROTTLED.search(response.content[:400])
    return int(m.group(1)) or None if m else None

class BrightDataClient:
    """Thin auth + retry wrapper. One instance is shared by the three products.

    Parameters
    ----------
    settings_obj
        Source of ``brightdata_api_key``. **No secret is ever hard-coded**; the key is
        read from :mod:`vsm.config` and never logged or echoed into an artifact.
    transport
        ``httpx.BaseTransport`` — inject ``httpx.MockTransport`` in tests. When it
        is set, the offline guard is skipped (nothing leaves the process).
    sleep
        Injected so backoff costs no wall-clock time in tests.
    """

    def __init__(
        self,
        settings_obj: Settings | None = None,
        *,
        base_url: str = BRIGHTDATA_BASE_URL,
        transport: Any = None,
        timeout: float = 60.0,
        max_retries: int = 2,
        backoff_seconds: float = 1.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings_obj or get_settings()
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.timeout = float(timeout)
        self.max_retries = int(max_retries)
        self.backoff_seconds = float(backoff_seconds)
        self._sleep = sleep
        self._client: Any = None
        #: seconds between sends, per zone, once Bright Data has throttled that zone
        self._pace: dict[str | None, float] = {}
        self._next_send: dict[str | None, float] = {}
        self._pace_lock = threading.Lock()
        self._client_lock = threading.Lock()
        #: ``time.monotonic()`` after which no retry starts and no wait runs past
        self.stop_at: float | None = None

    # ------------------------------------------------------------------ wiring
    @property
    def api_key(self) -> str:
        key = (self.settings.brightdata_api_key or "").strip()
        if not key:
            raise BrightDataAuthError(
                "BRIGHTDATA_API_KEY is not set — export it (Bright Data control panel → "
                "Account settings → API keys) or run with VSM_OFFLINE=1 to use the "
                "deterministic miner",
                status=401,
            )
        return key

    def _ensure_client(self) -> Any:
        with self._client_lock:
            return self._build_client()

    def _build_client(self) -> Any:
        if self._client is not None:
            return self._client
        import httpx  # local import keeps this module importable with no network

        if self.transport is None and self.settings.offline:
            # vsm.config.Settings has no require_network() (that was engine.config's
            # method) — same guard, inlined: refuse a real transport while
            # VSM_OFFLINE=1, exactly as the parent's require_network did.
            raise ConfigError(
                "Bright Data mining (SERP / Discover / Web Unlocker) attempted while "
                "VSM_OFFLINE=1 — use the deterministic fake",
                rule="VSM_OFFLINE",
            )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        self._client = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=self.timeout,
            transport=self.transport,
        )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> BrightDataClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---------------------------------------------------------------- requests
    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        """Perform one call, retrying 429/5xx. Returns the ``httpx.Response``."""
        import httpx

        client = self._ensure_client()
        zone = (json_body or {}).get("zone")
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            if attempt and self._time_left() == 0.0:
                break
            self._wait_turn(zone)
            try:
                response = client.request(
                    method, path, json=dict(json_body) if json_body is not None else None,
                    params=dict(params) if params else None,
                )
            except httpx.HTTPError as exc:  # transport-level: timeout, connect, read
                last_error = BrightDataError(f"{method} {path} failed: {exc}")
                self._backoff(attempt)
                continue

            status = response.status_code
            rate = _throttle_rate_from_body(response) if status < 400 and response.content else None
            if rate:
                with self._pace_lock:
                    self._pace[zone] = max(self._pace.get(zone, 0.0), 60.0 / rate)
                    self._next_send[zone] = max(
                        self._next_send.get(zone, 0.0), time.monotonic() + self._pace[zone]
                    )
                last_error = BrightDataRateLimited(
                    f"{method} {path} → {status}: auto-throttled to {rate}/min", status=status
                )
                continue
            if status < 400 and response.content:
                wait = _retry_after_from_body(response)
                if wait is None:
                    return response
                last_error = BrightDataRateLimited(
                    f"{method} {path} → {status}: {response.text[:160]}", status=status
                )
                self._backoff(attempt, at_least=wait)
                continue
            if status < 400:
                last_error = BrightDataError(
                    f"{method} {path} → {status} with an empty body", status=status
                )
                self._backoff(attempt)
                continue
            if status in (401, 403):
                raise BrightDataAuthError(
                    f"{method} {path} → {status}. Check BRIGHTDATA_API_KEY and that the product "
                    "(SERP / Discover / Web Unlocker) is enabled for this account.",
                    status=status,
                )
            if status == 429 or status >= 500:
                last_error = (
                    BrightDataRateLimited(f"{method} {path} → 429", status=429)
                    if status == 429
                    else BrightDataError(f"{method} {path} → {status}", status=status)
                )
                self._backoff(attempt)
                continue
            raise BrightDataError(
                f"{method} {path} → {status}: {response.text[:300]}", status=status
            )
        raise last_error or BrightDataError(f"{method} {path} exhausted retries")

    def _wait_turn(self, zone: str | None) -> None:
        """Hold this send until the zone's throttled rate allows it, across threads."""
        with self._pace_lock:
            interval = self._pace.get(zone)
            if not interval:
                return
            now = time.monotonic()
            send_at = max(now, self._next_send.get(zone, now))
            left = self._time_left()
            if left is not None and send_at - now > left:
                raise BrightDataRateLimited(
                    f"zone {zone} is throttled and has no free slot before the sweep's time limit"
                )
            self._next_send[zone] = send_at + interval
        if send_at > now:
            self._sleep(send_at - now)

    def _time_left(self) -> float | None:
        """Seconds until :attr:`stop_at`, never negative; ``None`` with no stop time."""
        return None if self.stop_at is None else max(self.stop_at - time.monotonic(), 0.0)

    def _backoff(self, attempt: int, at_least: float = 0.0) -> None:
        if attempt < self.max_retries:
            wait = max(at_least, self.backoff_seconds * (attempt + 1))
            left = self._time_left()
            self._sleep(wait if left is None else min(wait, left))

    @staticmethod
    def json_of(response: Any) -> dict[str, Any]:
        """Parse a JSON body, turning a non-JSON payload into a clear error."""
        try:
            payload = response.json()
        except Exception as exc:
            raise BrightDataError(
                f"expected JSON, got {response.text[:200]!r}", status=response.status_code
            ) from exc
        if not isinstance(payload, dict):
            raise BrightDataError(f"expected a JSON object, got {type(payload).__name__}")
        return payload
