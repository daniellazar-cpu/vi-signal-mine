"""`read_required` — reading through a transient absence, and only there.

On the Vercel Blob backend a blob is not readable from every edge the instant
its write returns. Measured on production: the report step failed roughly half
the time with "No snapshot to report on", while the very artifacts it could not
read returned 200 to an external check made immediately afterwards, from a
different region than the one the function ran in. The write had landed; it was
not visible yet where the reader stood. The read was correct; the conclusion
drawn from it — "your snapshot is gone, mine another" — was not.
"""

from __future__ import annotations

import pytest

from vsm.storage import read_required


class _Store:
    """Fails the first `fail_times` reads, then succeeds."""

    reads_may_lag = True

    def __init__(self, fail_times: int, value="the artifact") -> None:
        self.fail_times = fail_times
        self.value = value
        self.attempts = 0

    def read_artifact(self, run_id, name):
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise FileNotFoundError(f"{name} not visible yet")
        return self.value


class _ConsistentStore(_Store):
    """A backend that reads its own writes — declares nothing."""

    reads_may_lag = False


def test_a_read_that_becomes_visible_succeeds():
    s = _Store(fail_times=3)
    assert read_required(s, "min-abc", "signals.json", base_delay=0.001) == "the artifact"
    assert s.attempts == 4


def test_a_genuine_absence_still_raises():
    s = _Store(fail_times=99)
    with pytest.raises(FileNotFoundError):
        read_required(s, "min-abc", "signals.json", attempts=3, base_delay=0.001)
    assert s.attempts == 3


def test_a_present_artifact_costs_exactly_one_attempt():
    s = _Store(fail_times=0)
    assert read_required(s, "min-abc", "signals.json", base_delay=999) == "the artifact"
    assert s.attempts == 1, "a successful read must not wait for anything"


def test_a_consistent_backend_never_retries():
    """The whole point of the opt-in. On a store that reads its own writes a
    failed read means genuinely absent, and retrying would only slow that
    conclusion — and every test that deletes an artifact on purpose."""
    s = _ConsistentStore(fail_times=1)
    with pytest.raises(FileNotFoundError):
        read_required(s, "min-abc", "signals.json", base_delay=999)
    assert s.attempts == 1, f"retried on a consistent backend ({s.attempts} attempts)"


def test_a_store_that_says_nothing_is_treated_as_consistent():
    """Absent attribute must not mean "retry" — that would reintroduce the cost
    on every backend that has not been taught about this."""

    class _Silent:
        def __init__(self):
            self.attempts = 0

        def read_artifact(self, run_id, name):
            self.attempts += 1
            raise FileNotFoundError("gone")

    s = _Silent()
    with pytest.raises(FileNotFoundError):
        read_required(s, "min-abc", "x.json", base_delay=999)
    assert s.attempts == 1


def test_only_the_vercel_blob_backend_opts_in():
    """Pins the classification. `vsm/backends/blob.py` is a Postgres *table*
    despite its name, so it reads its own writes."""
    from vsm.backends.vercel_blob import BlobRunStore, BlobTopicStore
    from vsm.runs.store import RunStore

    for cls in (BlobRunStore, BlobTopicStore):
        assert getattr(cls, "reads_may_lag", False) is True, cls.__name__
    assert getattr(RunStore, "reads_may_lag", False) is False


def test_the_expected_absence_paths_do_not_use_it():
    """`_existing_artifact` decides whether a resumed run may skip a pass, and
    the momentum loop tolerates a missing snapshot. Retrying either would add
    seconds per call for no gain, so they must stay plain reads."""
    import inspect

    from vsm.modes import insight

    src = inspect.getsource(insight._existing_artifact)
    assert "read_required" not in src, "_existing_artifact must not retry"
    assert "read_artifact" in src

    loop = inspect.getsource(insight)
    i = loop.index("earlier = series[:position]")
    assert "read_required" not in loop[i:i + 400], "the momentum loop must not retry"


def test_a_retry_is_not_served_the_memoised_miss():
    """The interaction that made the first version of this a no-op.

    The blob backend memoises a 404 for the life of a request as deliberately
    as it memoises a hit — the fan-out probes absent artifacts just as
    repeatedly as present ones. So a retry inside the same request was served
    the first attempt's miss out of memory and never reached the network.
    Production stayed at 2/10 successful report runs with the retry in place,
    because it was retrying against a cache.
    """

    class _Memoising:
        """A store whose reads are cached until `begin_request` clears it."""

        reads_may_lag = True

        def __init__(self):
            self.network_calls = 0
            self.visible = False
            self._memo = {}

        def begin_request(self):
            self._memo.clear()

        def read_artifact(self, run_id, name):
            if name in self._memo:
                raise FileNotFoundError(name)      # the memoised miss
            self.network_calls += 1
            if not self.visible:
                self.visible = True                # visible from the 2nd call on
                self._memo[name] = True
                raise FileNotFoundError(name)
            return "the artifact"

    s = _Memoising()
    assert read_required(s, "min-abc", "signals.json", base_delay=0.001) == "the artifact"
    assert s.network_calls == 2, (
        f"{s.network_calls} network call(s) — the retry was served from the memo"
    )


def test_the_invalidation_is_optional():
    """A store without `begin_request` must still retry, not crash."""

    class _NoMemo:
        reads_may_lag = True

        def __init__(self):
            self.attempts = 0

        def read_artifact(self, run_id, name):
            self.attempts += 1
            if self.attempts < 3:
                raise FileNotFoundError(name)
            return "ok"

    s = _NoMemo()
    assert read_required(s, "r", "n.json", base_delay=0.001) == "ok"
    assert s.attempts == 3


def test_one_operation_s_waiting_is_bounded_by_its_deadline_not_by_its_read_count():
    """The bug this class exists for.

    `run_report` needs seven artifacts. With a per-read budget, a genuinely
    absent artifact multiplied the wait by seven and pushed the operation past
    the 60-second function ceiling — a timeout instead of a clean 400, worse
    than the error being absorbed. Shrinking the per-read budget instead traded
    that for the opposite failure: too little patience to absorb the lag it
    exists for.
    """
    from vsm.storage import ReadDeadline

    class _AlwaysMissing:
        reads_may_lag = True

        def __init__(self):
            self.attempts = 0

        def read_artifact(self, run_id, name):
            self.attempts += 1
            raise FileNotFoundError(name)

    budget = 0.05
    deadline = ReadDeadline(budget)
    s = _AlwaysMissing()
    import time as _t

    started = _t.perf_counter()
    for name in ("signals.json", "findings.json", "themes.json", "momentum.json",
                 "anomaly.json", "duallens.json", "stance.json"):
        with pytest.raises(FileNotFoundError):
            read_required(s, "min-abc", name, deadline=deadline, base_delay=0.01)
    elapsed = _t.perf_counter() - started

    assert deadline.remaining == 0, "the budget was not fully consumed"
    assert elapsed < budget * 3, (
        f"seven failing reads waited {elapsed:.3f}s against a {budget}s "
        f"operation budget — the deadline is not shared"
    )


def test_the_first_read_may_spend_the_whole_budget():
    """The realistic case: once one artifact from a run is visible the rest
    are, so the first read should be allowed to wait properly rather than
    getting a seventh of the patience."""
    from vsm.storage import ReadDeadline

    deadline = ReadDeadline(10.0)
    s = _Store(fail_times=3)
    assert read_required(s, "r", "n.json", deadline=deadline, base_delay=0.001) == "the artifact"
    assert s.attempts == 4
    assert deadline.remaining < 10.0, "nothing was drawn from the shared budget"


def test_a_spent_deadline_stops_retrying_immediately():
    from vsm.storage import ReadDeadline

    deadline = ReadDeadline(0.0)
    s = _Store(fail_times=99)
    with pytest.raises(FileNotFoundError):
        read_required(s, "r", "n.json", deadline=deadline, base_delay=999)
    assert s.attempts == 1, f"kept retrying with no budget left ({s.attempts})"


def test_the_report_shares_one_deadline_across_every_required_read():
    """Structural, because the cost of getting this wrong is a timeout in
    production rather than a test failure."""
    import inspect

    from vsm.modes import report

    src = inspect.getsource(report.run_report)
    n_reads = src.count("read_required(")
    assert n_reads >= 7, f"only {n_reads} required reads found — did they move?"
    assert src.count("deadline=deadline") == n_reads, (
        "some required read does not draw on the shared budget"
    )
    assert src.count("ReadDeadline(") == 1, "more than one budget per operation"


def test_a_configured_database_with_no_driver_falls_back_instead_of_500ing(monkeypatch, tmp_path, caplog):
    """The outage this nearly shipped.

    Pointing the app at Postgres set a database URL, and `open_stores` then
    imported a backend whose driver was an optional extra the host never
    installs — a `ModuleNotFoundError` on every single request. A missing
    driver is a deployment mistake; serving nothing is not the right response
    to it, and the log has to say which so it is fixable.
    """
    import builtins
    import logging

    from vsm.config import Settings
    from vsm.storage import open_stores

    real_import = builtins.__import__

    def no_psycopg(name, *args, **kwargs):
        if name == "psycopg" or name.startswith("psycopg."):
            raise ModuleNotFoundError("No module named 'psycopg'", name="psycopg")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_psycopg)
    monkeypatch.delitem(__import__("sys").modules, "vsm.backends.postgres", raising=False)

    env = {
        "POSTGRES_URL_NON_POOLING": "postgres://u:p@h/db",
        "BLOB_READ_WRITE_TOKEN": "",
        "VSM_VAR_DIR": str(tmp_path),
    }
    with caplog.at_level(logging.ERROR):
        topics, runs = open_stores(Settings(var_dir=tmp_path), env=env)

    assert topics is not None and runs is not None, "served nothing at all"
    assert any("driver is missing" in r.message or "driver is missing" in r.getMessage()
               for r in caplog.records), [r.getMessage() for r in caplog.records]
