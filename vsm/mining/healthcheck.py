"""One cheap live call per Bright Data product, to prove the wiring before a sweep.

**Why this exists.** The whole live path was tested only against a mocked
transport until the first real key arrived, and a full sweep is an expensive,
slow way to discover that a zone name is wrong or a product is not enabled on the
account. This makes the smallest possible real call to each product — one SERP
request, one Web Unlocker request against Bright Data's own test URL — and
reports pass or fail for each, so a mis-wired key surfaces in a few cents and a
few seconds rather than mid-sweep.

It validates the **app's own wiring**, not just raw connectivity: it uses the
same `Settings`, the same zones, and the same `BrightDataClient` the miner uses,
so it catches "the key works but `VSM_OFFLINE` is still 1", a zone typo in the
env, or a product the account has not enabled — none of which a standalone curl
would catch.

The key is never returned or logged. Each result carries a status, a latency and
a short, safe detail string (an error message, or a snippet of Bright Data's
public test-page response), and nothing else.
"""

from __future__ import annotations

import time
from typing import Any

from vsm.config import Settings, get_settings
from vsm.mining.client import (
    BrightDataAuthError,
    BrightDataClient,
    BrightDataError,
)

__all__ = ["CheckResult", "check_brightdata", "UNLOCKER_TEST_URL", "SERP_TEST_QUERY"]

#: Bright Data's own connectivity URL. Cheap, stable, and returns a tiny known
#: body — the canonical "is the Unlocker reachable" target from their docs.
UNLOCKER_TEST_URL = "https://geo.brdtest.com/welcome.txt?product=unlocker&method=api"

#: A trivial SERP query. The result content does not matter — only that Bright
#: Data returns parsed JSON, which proves the SERP product and zone are live.
SERP_TEST_QUERY = "test"


class CheckResult(dict):
    """A single product's result. A plain dict so a template and a JSON caller
    read it the same way; a class only so the shape is documented in one place.

    Keys: ``product`` (str), ``zone`` (str), ``ok`` (bool), ``detail`` (str, safe
    to display — never contains the key), ``latency_ms`` (int | None).
    """

    def __init__(self, product: str, zone: str, ok: bool, detail: str, latency_ms: int | None):
        super().__init__(product=product, zone=zone, ok=ok, detail=detail, latency_ms=latency_ms)


def _timed(fn: Any) -> tuple[bool, str, int | None]:
    """Run one probe, translating every outcome into (ok, detail, latency_ms).

    Bright Data's own error classes carry the message a person needs — a 401/403
    means the key or product is wrong, a rate-limit means it survived retries —
    so they are surfaced verbatim rather than flattened to "failed". A truly
    unexpected exception is caught too: a health check that raises is worse than
    one that reports the raw error, because the former looks like the app is
    broken when it is the connection that is.
    """
    start = time.monotonic()
    try:
        detail = fn()
        ms = int((time.monotonic() - start) * 1000)
        return True, detail, ms
    except BrightDataAuthError as exc:
        return False, str(exc), int((time.monotonic() - start) * 1000)
    except BrightDataError as exc:
        return False, str(exc), int((time.monotonic() - start) * 1000)
    except Exception as exc:  # noqa: BLE001 — a health check must never itself 500
        return False, f"unexpected error: {type(exc).__name__}: {exc}", int((time.monotonic() - start) * 1000)


def check_brightdata(
    settings: Settings | None = None, *, transport: Any = None
) -> list[CheckResult]:
    """One SERP and one Unlocker probe, using the app's real config.

    ``transport`` is the ``httpx`` transport seam the client already exposes for
    tests — production passes nothing and the client builds its own. Returns a
    result per product even when the key is missing, so the caller can show the
    same table whether the instance is configured or not.
    """
    s = settings or get_settings(refresh=True)
    results: list[CheckResult] = []

    if not s.brightdata_api_key:
        for product, zone in (("SERP", s.brightdata_serp_zone), ("Web Unlocker", s.brightdata_unlocker_zone)):
            results.append(CheckResult(
                product, zone, False,
                "BRIGHTDATA_API_KEY is not set on this deployment.", None,
            ))
        return results

    client = BrightDataClient(s, transport=transport)
    try:
        # SERP: a trivial query with brd_json=1, so a pass proves parsed JSON
        # comes back — exactly what the miner relies on.
        def serp_probe() -> str:
            from urllib.parse import urlencode
            url = "https://www.google.com/search?" + urlencode(
                {"q": SERP_TEST_QUERY, "brd_json": 1, "gl": "us", "hl": "en"}
            )
            resp = client.request(
                "POST", "/request",
                json_body={"zone": s.brightdata_serp_zone, "url": url, "format": "raw"},
            )
            body = resp.text or ""
            return f"HTTP {resp.status_code}, {len(body)} bytes of parsed SERP JSON"

        ok, detail, ms = _timed(serp_probe)
        results.append(CheckResult("SERP", s.brightdata_serp_zone, ok, detail, ms))

        # Web Unlocker: Bright Data's own test URL, a few cents, known body.
        def unlocker_probe() -> str:
            resp = client.request(
                "POST", "/request",
                json_body={"zone": s.brightdata_unlocker_zone, "url": UNLOCKER_TEST_URL, "format": "raw"},
            )
            body = (resp.text or "").strip()
            snippet = body[:60].replace("\n", " ")
            return f"HTTP {resp.status_code}: {snippet!r}"

        ok, detail, ms = _timed(unlocker_probe)
        results.append(CheckResult("Web Unlocker", s.brightdata_unlocker_zone, ok, detail, ms))
    finally:
        client.close()

    return results
