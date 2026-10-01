"""The Bright Data pre-flight check.

A full sweep is an expensive, slow way to discover a wrong zone, a throttled
product or a speed that cannot fit the time limit. This endpoint rehearses a
sweep's calls — three sweep-shaped searches together, one sweep-shaped page fetch
— and reports pass/fail and latency. The tests below pin that shape without a real
key or network, using the client's injected-transport seam.
"""

from __future__ import annotations

import httpx
import pytest
from starlette.testclient import TestClient

from vsm.config import Settings
from vsm.mining.healthcheck import CheckResult, check_brightdata, wide_sweep_fit
from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore
from vsm.ui.app import create_app


def _live_settings(tmp_path):
    return Settings(offline=False, brightdata_api_key="bd-test-key",
                    brightdata_serp_zone="dataweb_serp_api1",
                    brightdata_unlocker_zone="dataweb", var_dir=tmp_path)


def test_both_products_pass_when_bright_data_answers(tmp_path):
    def handler(request):
        return httpx.Response(200, text='{"organic":[]}')
    results = check_brightdata(_live_settings(tmp_path),
                               transport=httpx.MockTransport(handler))
    assert [r["product"] for r in results] == ["SERP", "SERP", "SERP", "Web Unlocker"]
    assert all(r["ok"] for r in results)
    assert all(r["latency_ms"] is not None for r in results)


def test_an_auth_failure_is_reported_not_raised(tmp_path):
    """A 401 is the commonest real failure — wrong key, or a product the account
    has not enabled. It must come back as a failed row with a useful message,
    never as a 500."""
    def handler(request):
        return httpx.Response(401, text="Unauthorized")
    results = check_brightdata(_live_settings(tmp_path),
                               transport=httpx.MockTransport(handler))
    assert all(not r["ok"] for r in results)
    assert any("BRIGHTDATA_API_KEY" in r["detail"] or "401" in r["detail"] for r in results)


def test_no_key_reports_cleanly_without_a_call(tmp_path):
    s = Settings(offline=False, brightdata_api_key=None, var_dir=tmp_path)
    results = check_brightdata(s, transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    assert all(not r["ok"] for r in results)
    assert all("not set" in r["detail"].lower() for r in results)


def test_the_key_is_never_in_any_result(tmp_path):
    """The result is rendered into a page and could be logged. It must never
    carry the secret."""
    def handler(request):
        return httpx.Response(200, text="ok")
    results = check_brightdata(_live_settings(tmp_path),
                               transport=httpx.MockTransport(handler))
    blob = repr(results)
    assert "bd-test-key" not in blob


# ------------------------------------------------------------------ routes --

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("BLOB_READ_WRITE_TOKEN", raising=False)
    monkeypatch.delenv("VSM_ACCESS_KEY", raising=False)
    monkeypatch.setenv("VSM_OFFLINE", "1")
    ts = TopicStore(tmp_path / "db"); rs = RunStore(tmp_path / "db", tmp_path / "var")
    return TestClient(create_app(topic_store=ts, run_store=rs))


def test_the_get_page_spends_nothing_and_shows_config(client):
    """A crawler or prefetch hitting the page must not make a billed call."""
    r = client.get("/healthz/brightdata")
    assert r.status_code == 200
    assert "Bright Data connection" in r.text
    # Offline in this fixture, so it must say so and offer no run button that spends.
    assert "offline" in r.text.lower()


def test_the_post_refuses_to_probe_while_offline(client):
    """Offline is the default and safe state; a probe then would only produce a
    confusing failure, so the POST declines to make one."""
    r = client.post("/healthz/brightdata")
    assert r.status_code == 200
    # No results table rendered because no probe ran.
    assert "Reachable" not in r.text and "Failed" not in r.text


# --------------------------------------------------------------------------- #
# it has to be ONE call, and it has to actually parse the answer              #
# --------------------------------------------------------------------------- #


def test_a_serp_zone_answering_html_is_reported_failed_not_reachable(tmp_path):
    """The precise wiring failure this probe exists to catch.

    The SERP probe built its detail string from the status code and
    ``len(body)`` — "HTTP 200, 4213 bytes of parsed SERP JSON" — without ever
    parsing anything. A zone that is enabled but mis-scoped answers 200 with an
    HTML block page or a login redirect, and that was reported **Reachable**: the
    page said the wiring was good and the first real sweep would then fail on
    exactly the case ``serp.py`` guards against downstream.
    """
    def handler(request):
        body = request.read().decode()
        if "google.com/search" in body:
            return httpx.Response(200, text="<html><body>Sign in to continue</body></html>")
        return httpx.Response(200, text="OK - welcome.txt")

    results = check_brightdata(_live_settings(tmp_path), transport=httpx.MockTransport(handler))
    serp = next(r for r in results if r["product"] == "SERP")
    unlocker = next(r for r in results if r["product"] == "Web Unlocker")

    assert serp["ok"] is False, "an HTML body was reported as parsed SERP JSON"
    assert "expected JSON" in serp["detail"]
    # And the failure is scoped to the product that failed.
    assert unlocker["ok"] is True


def test_the_preflight_makes_exactly_one_call_per_probe_even_when_throttled(tmp_path):
    """"One call per probe" has to be true of the failure path too.

    ``BrightDataClient`` defaults to ``max_retries=2``, so a 429 turned each probe
    into three billed calls plus its backoff sleeps — three times the cost the page
    quotes, and several seconds of real waiting. Retrying past a rate limit also
    reports the wrong thing: "this zone is throttled right now" is what the person
    running a pre-flight needs to see.
    """
    calls: list[str] = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(429, text="Too Many Requests")

    results = check_brightdata(_live_settings(tmp_path), transport=httpx.MockTransport(handler))

    assert all(not r["ok"] for r in results)
    assert len(calls) == 4, f"expected one call per probe, made {len(calls)}"


def test_a_json_array_is_not_accepted_as_a_serp_payload(tmp_path):
    """``json_of`` rejects a non-object too. A bare array parses as JSON and is
    still not the shape the miner reads, so it must not pass."""
    def handler(request):
        body = request.read().decode()
        if "google.com/search" in body:
            return httpx.Response(200, text="[]")
        return httpx.Response(200, text="OK")

    results = check_brightdata(_live_settings(tmp_path), transport=httpx.MockTransport(handler))
    serp = next(r for r in results if r["product"] == "SERP")
    assert serp["ok"] is False
    assert "JSON object" in serp["detail"]


# --------------------------------------------------------------------------- #
# it rehearses a sweep, not a test page                                        #
# --------------------------------------------------------------------------- #


def test_the_searches_are_the_site_scoped_queries_a_sweep_sends(tmp_path):
    bodies: list[str] = []

    def handler(request):
        bodies.append(request.read().decode())
        return httpx.Response(200, json={"organic": []})

    check_brightdata(_live_settings(tmp_path), transport=httpx.MockTransport(handler))
    searches = [b for b in bodies if "google.com/search" in b]
    assert len(searches) == 3
    assert all("site%3A" in b for b in searches)


def test_the_page_fetch_targets_a_result_a_sweep_would_fetch(tmp_path):
    page = "https://www.medpagetoday.com/endocrinology/diabetes/1"
    targets: list[str] = []

    def handler(request):
        body = request.read().decode()
        if "google.com/search" in body:
            return httpx.Response(200, json={"organic": [
                {"rank": 1, "title": "t", "description": "d", "link": "https://www.reddit.com/r/medicine/1"},
                {"rank": 2, "title": "t", "description": "d", "link": page},
            ]})
        targets.append(body)
        return httpx.Response(200, text="page body")

    results = check_brightdata(_live_settings(tmp_path), transport=httpx.MockTransport(handler))
    unlocker = results[-1]
    assert unlocker["ok"] is True
    assert page in unlocker["detail"]
    assert len(targets) == 1 and "medpagetoday.com" in targets[0]


def test_with_no_fetchable_result_the_fetch_falls_back_and_says_so(tmp_path):
    def handler(request):
        return httpx.Response(200, json={"organic": []})

    results = check_brightdata(_live_settings(tmp_path), transport=httpx.MockTransport(handler))
    assert "test page" in results[-1]["detail"]


def _rows(search_ms, page_ms, *, ok=True):
    return [CheckResult("SERP", "z", ok, "", ms) for ms in search_ms] + [CheckResult("Web Unlocker", "z", True, "", page_ms)]


def test_the_fit_is_paced_by_the_slowest_calls():
    fit = wide_sweep_fit(_rows([20_000, 60_000, 40_000], 10_000), limit_s=540)
    assert fit == {"search_s": 60, "fetch_s": 60, "full_groups": 4, "limit_s": 540,
                   "failed_searches": 0, "searches": 3}


def test_a_failed_search_still_paces_the_fit_and_is_counted():
    rows = _rows([20_000, 30_000], 10_000) + [CheckResult("SERP", "z", False, "empty body", 52_000)]
    fit = wide_sweep_fit(rows, limit_s=540)
    assert fit["search_s"] == 52
    assert (fit["failed_searches"], fit["searches"]) == (1, 3)


def test_no_fit_without_timings():
    assert wide_sweep_fit([CheckResult("SERP", "z", False, "not set", None),
                           CheckResult("Web Unlocker", "z", False, "not set", None)], limit_s=540) is None


def test_a_failed_page_fetch_names_the_page(tmp_path):
    page = "https://www.medpagetoday.com/endocrinology/diabetes/1"

    def handler(request):
        if "google.com/search" in request.read().decode():
            return httpx.Response(200, json={"organic": [
                {"rank": 1, "title": "t", "description": "d", "link": page}]})
        return httpx.Response(200, text="")

    unlocker = check_brightdata(_live_settings(tmp_path), transport=httpx.MockTransport(handler))[-1]
    assert unlocker["ok"] is False
    assert page in unlocker["detail"]
