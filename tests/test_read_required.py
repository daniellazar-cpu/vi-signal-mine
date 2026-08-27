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


def test_the_default_budget_leaves_room_for_a_whole_report():
    """`run_report` reads eight artifacts it cannot proceed without, so the
    per-read waits compound. At six attempts (7.75s each) a genuinely absent
    artifact pushed the operation past the 60s serverless ceiling — a timeout
    instead of a clean 400, which is worse than the error being absorbed.
    """
    import inspect

    sig = inspect.signature(read_required)
    attempts = sig.parameters["attempts"].default
    base = sig.parameters["base_delay"].default
    per_read = sum(base * (2 ** i) for i in range(attempts - 1))
    assert per_read * 8 < 30, (
        f"{attempts} attempts x {base}s = {per_read:.2f}s per read; "
        f"{per_read * 8:.1f}s for a report's eight reads is too close to the "
        f"60s function ceiling"
    )
    assert attempts >= 3, "too few attempts to absorb any real lag"
