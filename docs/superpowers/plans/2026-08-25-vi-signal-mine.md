# Vi Signal Mine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-first pulse instrument that mines what is being said about a healthcare brand or product online, turns it into corroborated findings with stance and movement, and packages a client-deliverable report.

**Architecture:** A FastAPI + Jinja app over three chainable modes — MINE, INSIGHT, REPORT — run against a persistent **topic** whose MINE runs are dated **snapshots**. The Bright Data mining package is vendored verbatim from the parent engine; the `analysis/` package that transforms signals into findings is new and is where the value sits. Model output is prose and classification only; every count, delta, tier and threshold is arithmetic.

**Tech Stack:** Python 3.14 · FastAPI · Jinja2 (StrictUndefined) · Pydantic · httpx · stdlib `sqlite3` · Anthropic SDK (Claude Opus 5) · Bright Data SERP/Discover/Unlocker · pytest

**Spec:** `docs/superpowers/specs/2026-08-25-vi-signal-mine-design.md` — read it before Task 1. The plan argues from the spec; where they disagree, the spec wins and the plan is wrong.

**Research:** `docs/research/2026-08-25-social-intelligence-landscape.md` — why the `analysis/` package exists at all.

**Parent repo:** `~/Documents/forum-engine` (`daniellazar-cpu/attending-health-engine`). Read-only. Never modify it.

## Global Constraints

Every task's requirements implicitly include this section.

- **Python 3.14.** The parent runs 3.14.5; match it.
- **Allowed dependencies, and no others:** `fastapi`, `uvicorn`, `pydantic`, `jinja2`, `httpx`, `python-multipart`, `pyyaml`, `anthropic`, `pytest`. Persistence is **stdlib `sqlite3`** — no SQLAlchemy. Adding a dependency requires the owner's say-so.
- **No CDN, no external font, no build step.** The UI renders with zero network.
- **Jinja uses `StrictUndefined`.** `{% if foo %}` on an undefined name 500s the page. Write `{% if foo is defined and foo %}`.
- **`VSM_OFFLINE=1` is the master switch** and wins over `VSM_MINER` and `VSM_DRAFTER`. With it set, no outbound call is attempted anywhere, even with both keys present in the environment.
- **Live-without-a-key raises, never falls back.** A run that quietly stopped collecting looks identical to one that collected.
- **The model may not author trust state.** Counts, deltas, confidence tiers, momentum and anomaly thresholds are arithmetic. The model reads text, names themes, classifies stance and writes prose. Nothing else.
- **Nothing invents a number.** Absent data is `None` plus a stated reason, never a plausible default. This is the parent's rule and it is the reason this tool can be handed to a client.
- **Tests are hermetic.** `httpx.MockTransport` for the three Bright Data surfaces; an injected client for Anthropic. No test makes a network call.
- **Commit after every task.** Conventional-commit subject, imperative mood, no trailing period.
- **Two storage backends, one contract** (spec D16). `TopicStore`/`RunStore` are the local SQLite+filesystem implementations. `vsm/storage.py` declares the Protocol both they and the later Postgres/blob pair satisfy. **The SQL is duplicated between backends on purpose** — for a 5-column and a 9-column table, two clear implementations beat one dialect shim, and a shim that papers over `?` vs `%s` is where the subtle bugs live.
- **Never write to a path that is not the configured var dir.** On Vercel only `/tmp` is writable and it belongs to *one invocation*. Anything that must survive a request goes through a store, never through an ad-hoc `open()`.
- **Author class values are exactly** `hcp` · `patient` · `institutional` · `unknown` — derived from the six venue kinds in the registry and nothing else. Do not invent a `press` class; the registry has no such kind.

## File Structure

| Path | Responsibility |
|---|---|
| `vsm/config.py` | `Settings` from env; mode switches; offline master switch |
| `vsm/errors.py` | `VsmError` and its subclasses — one place, so callers can catch a family |
| `vsm/app.py` | Composition root: mounts the UI, wires stores |
| `vsm/mining/*` | **Vendored** from `engine/mining`. Import prefix rewritten; three behavioural changes (spec §3.1) and nothing else |
| `vsm/llm/client.py` | Vendored `AnthropicDrafter`, generalised to `complete_structured` |
| `vsm/llm/prompts.py` | System prompts — byte-identical across runs, or the cache is lost |
| `vsm/llm/schema.py` | One JSON schema per analysis pass |
| `vsm/topics/model.py` | `Topic`, `SpendBand`, the three band presets |
| `vsm/topics/store.py` | Topic CRUD + a topic's snapshot series, over `sqlite3` |
| `vsm/runs/model.py` | `Run`, `RunMode`, `RunStatus` |
| `vsm/runs/store.py` | Run metadata in SQLite; artifacts on disk under `var/runs/<run_id>/` |
| `vsm/analysis/authorclass.py` | **The v2 seam.** The only place any pass learns who is speaking |
| `vsm/analysis/resolve.py` | Mention → entity against the topic lexicon |
| `vsm/analysis/corroborate.py` | Independence test, confidence tier |
| `vsm/analysis/cluster.py` | Themes, theme naming, venue mix |
| `vsm/analysis/stance.py` | Stance per theme **per author class** — no blended field exists |
| `vsm/analysis/duallens.py` | HCP view vs patient view, ranked by divergence |
| `vsm/analysis/momentum.py` | Snapshot deltas; `None` with a reason at N=1 |
| `vsm/analysis/anomaly.py` | This snapshot vs the median of the previous three |
| `vsm/modes/mine.py` | Lexicon → plan → sweep → artifacts |
| `vsm/modes/insight.py` | Orders the seven passes, writes seven artifacts |
| `vsm/modes/report.py` | Four report artifacts, all guards applied |
| `vsm/guards/cost.py` | G3 — estimate before spend, cap, clean stop |
| `vsm/guards/citations.py` | G1 — claims bind to ledger rows or the report blocks |
| `vsm/guards/advisory.py` | G2 — suggestions, never decisions |
| `vsm/guards/terms.py` | G4 — optional per-run never-say list |
| `vsm/guards/claims.py` | G5 — no forecast or accuracy language |
| `vsm/guards/corroboration.py` | G6 — uncorroborated findings cannot reach the report body |
| `vsm/ui/app.py` + `templates/` + `static/` | The eight screens |

**Boundary that matters:** `analysis/` modules are pure functions over lists of signal dicts. They take no store, open no file, and make no network call. That is what makes them testable with hand-built fixtures and exact expected outputs, and it is the difference between a transformation layer you can trust and one you can only demo.

---

## Task 1: Repository skeleton, config, errors

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `Makefile`, `README.md`
- Create: `vsm/__init__.py`, `vsm/config.py`, `vsm/errors.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing
- Produces: `Settings` (`.offline: bool`, `.miner_mode: str`, `.drafter_mode: str`, `.anthropic_api_key: str | None`, `.brightdata_api_key: str | None`, `.brightdata_serp_zone: str`, `.brightdata_unlocker_zone: str`, `.llm_model: str`, `.run_cost_cap_usd: float`, `.var_dir: Path`, `.db_path: Path` (a property)); `get_settings(refresh=False) -> Settings`; errors `VsmError`, `ConfigError`, `BudgetExceeded`, `GuardViolation`, `NoSuchTopic`, `NoSuchRun`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import pytest
from vsm.config import Settings


def test_offline_defaults_to_true():
    s = Settings.from_env({})
    assert s.offline is True


def test_offline_wins_over_miner_and_drafter():
    """The master switch exists so a stray key in a shell cannot point the
    suite at a live API. If this ever returns 'live', delete the release."""
    s = Settings.from_env(
        {
            "VSM_OFFLINE": "1",
            "VSM_MINER": "live",
            "VSM_DRAFTER": "llm",
            "ANTHROPIC_API_KEY": "sk-real",
            "BRIGHTDATA_API_KEY": "bd-real",
        }
    )
    assert s.effective_miner_mode() == "fake"
    assert s.effective_drafter_mode() == "off"


def test_live_modes_available_when_offline_is_zero():
    s = Settings.from_env(
        {"VSM_OFFLINE": "0", "VSM_MINER": "live", "VSM_DRAFTER": "llm",
         "ANTHROPIC_API_KEY": "sk-real", "BRIGHTDATA_API_KEY": "bd-real"}
    )
    assert s.effective_miner_mode() == "live"
    assert s.effective_drafter_mode() == "llm"


def test_auto_resolves_on_key_presence():
    on = Settings.from_env({"VSM_OFFLINE": "0", "ANTHROPIC_API_KEY": "sk-x"})
    off = Settings.from_env({"VSM_OFFLINE": "0"})
    assert on.effective_drafter_mode() == "llm"
    assert off.effective_drafter_mode() == "off"


def test_unknown_mode_is_rejected_loudly():
    from vsm.errors import ConfigError

    with pytest.raises(ConfigError, match="VSM_MINER"):
        Settings.from_env({"VSM_MINER": "sometimes"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vsm'`

- [ ] **Step 3: Write `vsm/errors.py`**

```python
"""One error family, so a caller can catch the whole tool's failures.

Every error carries a ``rule`` naming the decision it enforces. When one of
these reaches a log, the reader should not have to open the source to find
out which rule fired.
"""

from __future__ import annotations

__all__ = [
    "VsmError",
    "ConfigError",
    "BudgetExceeded",
    "GuardViolation",
    "NoSuchTopic",
    "NoSuchRun",
]


class VsmError(Exception):
    """Base for everything this tool raises deliberately."""

    def __init__(self, message: str, *, rule: str = "") -> None:
        super().__init__(message)
        self.rule = rule


class ConfigError(VsmError):
    """The environment says something we cannot act on."""


class BudgetExceeded(VsmError):
    """A cap bound. Callers stop cleanly; they do not let this escape a run."""


class GuardViolation(VsmError):
    """A guard refused output. Never caught and softened — it blocks."""


class NoSuchTopic(VsmError):
    pass


class NoSuchRun(VsmError):
    pass
```

- [ ] **Step 4: Write `vsm/config.py`**

```python
"""Settings, and the one switch that keeps the test suite honest.

``VSM_OFFLINE`` defaults to ``1`` and **wins over** ``VSM_MINER`` and
``VSM_DRAFTER``. Without that precedence, an ``ANTHROPIC_API_KEY`` sitting in
a developer's shell would quietly point the whole suite at a live API — which
is exactly the failure the parent engine documents having hit.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from vsm.errors import ConfigError

__all__ = ["Settings", "get_settings"]

_MINER_MODES = ("auto", "fake", "live")
_DRAFTER_MODES = ("auto", "llm")
_TRUE = ("1", "true", "yes", "on")


def _flag(env: Mapping[str, str], key: str, default: str) -> bool:
    return str(env.get(key, default)).strip().lower() in _TRUE


def _choice(env: Mapping[str, str], key: str, allowed: tuple[str, ...], default: str) -> str:
    value = str(env.get(key, default)).strip().lower()
    if value not in allowed:
        raise ConfigError(
            f"{key}={value!r} is not one of {allowed}", rule="config"
        )
    return value


@dataclass(frozen=True)
class Settings:
    offline: bool = True
    miner_mode: str = "auto"
    drafter_mode: str = "auto"
    anthropic_api_key: str | None = None
    brightdata_api_key: str | None = None
    brightdata_serp_zone: str = "dataweb_serp_api1"
    brightdata_unlocker_zone: str = "dataweb"
    llm_model: str = "claude-opus-5"
    run_cost_cap_usd: float = 5.0
    var_dir: Path = Path("var")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        return cls(
            offline=_flag(env, "VSM_OFFLINE", "1"),
            miner_mode=_choice(env, "VSM_MINER", _MINER_MODES, "auto"),
            drafter_mode=_choice(env, "VSM_DRAFTER", _DRAFTER_MODES, "auto"),
            anthropic_api_key=(env.get("ANTHROPIC_API_KEY") or "").strip() or None,
            brightdata_api_key=(env.get("BRIGHTDATA_API_KEY") or "").strip() or None,
            brightdata_serp_zone=env.get("BRIGHTDATA_SERP_ZONE", "dataweb_serp_api1"),
            brightdata_unlocker_zone=env.get("BRIGHTDATA_UNLOCKER_ZONE", "dataweb"),
            llm_model=env.get("VSM_LLM_MODEL", "claude-opus-5"),
            run_cost_cap_usd=float(env.get("VSM_RUN_COST_CAP_USD", "5.0")),
            var_dir=Path(env.get("VSM_VAR_DIR", "var")),
        )

    @property
    def db_path(self) -> Path:
        return self.var_dir / "vsm.db"

    def effective_miner_mode(self) -> str:
        """``fake`` | ``live``. Offline forces ``fake``; ``auto`` needs a key."""
        if self.offline:
            return "fake"
        if self.miner_mode == "auto":
            return "live" if self.brightdata_api_key else "fake"
        return self.miner_mode

    def effective_drafter_mode(self) -> str:
        """``llm`` | ``off``. Offline forces ``off``; ``auto`` needs a key.

        ``llm`` without a key is *not* resolved here — it stays ``llm`` and the
        client raises at call time. A silent downgrade to ``off`` would make a
        run that generated nothing look like one that did.
        """
        if self.offline:
            return "off"
        if self.drafter_mode == "auto":
            return "llm" if self.anthropic_api_key else "off"
        return "llm"


_CACHED: Settings | None = None


def get_settings(refresh: bool = False) -> Settings:
    global _CACHED
    if _CACHED is None or refresh:
        _CACHED = Settings.from_env()
    return _CACHED
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: 5 passed

- [ ] **Step 6: Write the supporting files**

`pyproject.toml`:

```toml
[project]
name = "vi-signal-mine"
version = "0.1.0"
description = "A pulse instrument: what is being said about a brand or product online, and what changed"
requires-python = ">=3.14"
dependencies = [
    "fastapi",
    "uvicorn",
    "pydantic",
    "jinja2",
    "httpx",
    "python-multipart",
    "pyyaml",
    "anthropic",
]

[project.optional-dependencies]
dev = ["pytest"]

[tool.pytest.ini_options]
testpaths = ["tests"]
filterwarnings = ["error"]

[tool.setuptools.packages.find]
include = ["vsm*"]
```

`.gitignore`:

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
var/
.env
.DS_Store
```

`.env.example`:

```bash
# Copy to .env. Never commit .env.
# Nothing here is needed to run the tests: they are hermetic and VSM_OFFLINE
# defaults to 1, which is the master switch that keeps them that way.

# ── the offline master switch ────────────────────────────────────────────────
# 1 = no outbound calls anywhere. Wins over VSM_MINER and VSM_DRAFTER.
VSM_OFFLINE=1

# ── generation ───────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY=
VSM_LLM_MODEL=claude-opus-5
# auto (model when a key is set) | llm (force; raises without a key)
VSM_DRAFTER=auto

# ── mining ───────────────────────────────────────────────────────────────────
# Same Bright Data account as Attending Health. Zone names are that account's
# actual zones, not Bright Data's auto-provisioned defaults — a wrong zone name
# 400s on the first call.
BRIGHTDATA_API_KEY=
BRIGHTDATA_SERP_ZONE=dataweb_serp_api1
BRIGHTDATA_UNLOCKER_ZONE=dataweb
# auto | fake (deterministic even when online) | live
VSM_MINER=auto

# ── cost ─────────────────────────────────────────────────────────────────────
# The Bright Data account is SHARED with other Vi projects, so this is tight on
# purpose. Raise per run, knowingly; never by editing this default upward.
VSM_RUN_COST_CAP_USD=5.0

# ── state ────────────────────────────────────────────────────────────────────
VSM_VAR_DIR=var
```

`Makefile`:

```make
.PHONY: install test run

install:
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"

test:
	.venv/bin/python -m pytest -q

run:
	.venv/bin/python -m uvicorn vsm.app:app --port 8811
```

`README.md`: a short orientation — what the tool is (one paragraph from the spec's §1), the three modes, `make install && make test && make run`, and a pointer to the spec and the research doc. Include the sentence: *"Momentum needs a baseline, so run MINE on a topic more than once before expecting INSIGHT to tell you what changed."*

- [ ] **Step 7: Verify the package installs and tests pass from a clean venv**

Run: `make install && make test`
Expected: 5 passed

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Add the skeleton, and make offline the switch that outranks the others"
```

---

## Task 2: Vendor the mining package, and prove it did not change

**Files:**
- Create: `vsm/mining/*` (copied from `~/Documents/forum-engine/engine/mining/`)
- Test: `tests/test_mining_parity.py`, `tests/conftest.py`

**Interfaces:**
- Consumes: `vsm.errors`
- Produces: the whole vendored surface. The names later tasks use: `build_row`, `dedupe_rows`, `Hit`, `plan_queries`, `PlannedQuery`, `expand_queries`, `LiveSignalMining`, `MiningConfig`, `MiningOutcome`, `Budget`, `FetchCall`, `Venue`, `GOLD_VENUES`, `venues_for`, `kind_of`, `is_gold`, `areas_for_cluster`, `domain_of`, `registrable_domain`, `partition`, `deny_reason`, `window_for`, `RobotsCache`

**Context for the implementer:** this is a copy, not a rewrite. The parent's `engine/mining/` is self-contained by design — its own docstring records that the local query-shape fallback exists *"only so this package never has to import the orchestrator."* Three behavioural changes are specified below (spec D5, §3.1) and **nothing else may change**. If you find yourself improving something, stop: the parity test exists to catch exactly that.

- [ ] **Step 1: Copy the package and rewrite the import prefix**

```bash
mkdir -p vsm/mining
cp ~/Documents/forum-engine/engine/mining/*.py vsm/mining/
find vsm/mining -name '*.py' -exec sed -i '' 's/from engine\.mining/from vsm.mining/g; s/import engine\.mining/import vsm.mining/g' {} +
grep -rn "engine\." vsm/mining/ || echo "no parent imports remain"
```

Expected: `no parent imports remain`. If anything prints, it is an import of `engine.errors` or `engine.config` — replace with the `vsm` equivalent and note it in the commit.

- [ ] **Step 2: Write the parity test**

```python
# tests/test_mining_parity.py
"""The vendored copy must plan the same sweep as the parent.

This is the only test that reaches outside the repo. It imports the parent's
mining package directly from its checkout and asserts the two planners agree
query-for-query. If the parent is not present the test skips — it is a guard
against silent divergence during the fork, not a permanent dependency.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

PARENT = Path.home() / "Documents" / "forum-engine"

pytestmark = pytest.mark.skipif(
    not (PARENT / "engine" / "mining" / "queries.py").exists(),
    reason="parent checkout not present",
)


@pytest.fixture(scope="module")
def parent_queries():
    if str(PARENT) not in sys.path:
        sys.path.insert(0, str(PARENT))
    import engine.mining.queries as pq  # noqa: PLC0415

    return pq


CLUSTER = {
    "cluster_id": "c1",
    "label": "opioid-induced constipation management",
    "terms": ["opioid-induced constipation", "OIC", "naldemedine"],
    "areas": ["gastroenterology"],
}


def test_planned_queries_match_the_parent_exactly(parent_queries):
    from vsm.mining.queries import plan_queries

    ours = plan_queries(CLUSTER, queries_per_cluster=4)
    theirs = parent_queries.plan_queries(CLUSTER, queries_per_cluster=4)

    assert [q.query for q in ours] == [q.query for q in theirs]
    assert [q.kind for q in ours] == [q.kind for q in theirs]


def test_gold_registry_is_byte_identical():
    """The gold list was hand-verified on 2026-08-02 with a real robots.txt GET
    per domain, and three unreachable candidates were dropped rather than listed
    on faith. It must never be regenerated from memory."""
    import engine.mining.venues as theirs  # noqa: PLC0415

    from vsm.mining.venues import GOLD_VENUES, VERIFIED_AT

    assert VERIFIED_AT == theirs.VERIFIED_AT
    assert {v.domain for v in GOLD_VENUES} == {v.domain for v in theirs.GOLD_VENUES}
    assert {(v.domain, v.kind, v.collection_tier) for v in GOLD_VENUES} == {
        (v.domain, v.kind, v.collection_tier) for v in theirs.GOLD_VENUES
    }
```

- [ ] **Step 3: Run the parity test**

Run: `pytest tests/test_mining_parity.py -v`
Expected: 2 passed. A failure here means the copy diverged — fix the copy, never the test.

- [ ] **Step 4: Apply the three specified changes (spec D5, §3.1)**

In `vsm/mining/tiers.py`, `assert_collectable` no longer raises. Replace its body so it returns a record instead:

```python
def assert_collectable(url: str) -> dict[str, str]:
    """Record the tier and let the caller proceed.

    The parent raises ``TierCRefused`` here. This fork does not (spec D5): the
    owner decided the tool collects from whatever search returns. The tier is
    still computed and recorded on every row, so the decision stays visible in
    the ledger rather than becoming invisible.

    ``VSM_ENFORCE_TIER_C=1`` restores the parent's refusal. It is off by
    default and exists so reversing D5 is a flag, not an excavation.
    """
    import os

    tier = tier_for(url)
    if tier == "C" and os.environ.get("VSM_ENFORCE_TIER_C", "0") == "1":
        raise TierCRefused(f"tier C domain refused: {domain_of(url)}")
    return {"domain": domain_of(url), "tier": tier}
```

In `vsm/mining/robots.py`, `RobotsCache.allows` keeps fetching and keeps its return value, but add a docstring line recording that callers report rather than gate:

```python
    # D5: callers in this fork RECORD this answer into coverage.json rather
    # than letting it veto a fetch. The method is unchanged; its authority is.
```

In `vsm/mining/signals.py`, extend `build_row` with two keyword-only arguments, defaulted so every existing call site and the parent's fixtures still pass:

```python
def build_row(
    *,
    campaign_id: str,
    cluster: Mapping[str, Any],
    hit: Hit,
    captured_at: datetime,
    brand_terms: Mapping[str, str] | None = None,
    topic_id: str | None = None,
    snapshot_at: str | None = None,
) -> dict[str, Any]:
```

and immediately before `return _strip_author_identifiers(row)`:

```python
    # Snapshot identity. Defaulted so the parent's fixtures still validate:
    # every pre-existing key keeps its exact meaning and position.
    if topic_id is not None:
        row["topic_id"] = topic_id
    if snapshot_at is not None:
        row["snapshot_at"] = snapshot_at
```

- [ ] **Step 5: Write tests for the three changes**

```python
# tests/test_mining_changes.py
from datetime import datetime, timezone

from vsm.mining.signals import Hit, build_row
from vsm.mining.tiers import assert_collectable

CLUSTER = {"cluster_id": "c1", "label": "oic", "terms": ["OIC"]}


def test_tier_c_is_recorded_not_refused():
    """Spec D5. The tier still lands on the row; it just no longer vetoes."""
    got = assert_collectable("https://www.doximity.com/some/post")
    assert got["tier"] == "C"


def test_tier_c_refusal_is_restorable_by_flag(monkeypatch):
    from vsm.mining.tiers import TierCRefused
    import pytest

    monkeypatch.setenv("VSM_ENFORCE_TIER_C", "1")
    with pytest.raises(TierCRefused):
        assert_collectable("https://www.doximity.com/some/post")


def test_snapshot_keys_are_absent_unless_asked_for():
    row = build_row(
        campaign_id="t1",
        cluster=CLUSTER,
        hit=Hit(url="https://example.org/a", title="A"),
        captured_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
    )
    assert "topic_id" not in row and "snapshot_at" not in row


def test_snapshot_keys_land_when_given():
    row = build_row(
        campaign_id="t1",
        cluster=CLUSTER,
        hit=Hit(url="https://example.org/a", title="A"),
        captured_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        topic_id="t1",
        snapshot_at="2026-08-25T00:00:00+00:00",
    )
    assert row["topic_id"] == "t1"
    assert row["snapshot_at"] == "2026-08-25T00:00:00+00:00"


def test_sentiment_is_still_none_on_a_fresh_row():
    """No classifier ran at collection time. The stance pass writes its own
    artifact; it must never back-fill this field, because a signal row says
    only what collection witnessed."""
    row = build_row(
        campaign_id="t1",
        cluster=CLUSTER,
        hit=Hit(url="https://example.org/a", title="A"),
        captured_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
    )
    assert row["sentiment"] is None
```

- [ ] **Step 6: Run the full suite**

Run: `pytest -q`
Expected: all pass, including the two parity tests still green after the edits.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Vendor the mining package, and pin it against the parent"
```

---

## Task 3: Topic model, spend bands, topic store

**Files:**
- Create: `vsm/topics/__init__.py`, `vsm/topics/model.py`, `vsm/topics/store.py`
- Test: `tests/test_topics.py`

**Interfaces:**
- Consumes: `vsm.config.Settings`, `vsm.errors.NoSuchTopic`
- Produces: `Topic` (frozen dataclass: `topic_id`, `name`, `brand`, `molecule`, `therapeutic_area`, `competitors: tuple[str, ...]`, `questions: tuple[str, ...]`, `spend_band: str`, `never_say: tuple[str, ...]`, `created_at: str`); `SpendBand` (frozen: `name`, `queries_per_cluster`, `serp_results_per_query`, `discover_results_per_cluster`, `page_fetches_per_cluster`); `BANDS: dict[str, SpendBand]`; `band_for(name) -> SpendBand`; `TopicStore(db_path)` with `.create(**kwargs) -> Topic`, `.get(topic_id) -> Topic`, `.list() -> list[Topic]`, `.update(topic_id, **fields) -> Topic`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_topics.py
import pytest

from vsm.errors import NoSuchTopic
from vsm.topics.model import BANDS, band_for
from vsm.topics.store import TopicStore


@pytest.fixture
def store(tmp_path):
    return TopicStore(tmp_path / "t.db")


def test_the_three_bands_exist_and_escalate():
    """A preset rather than a dollar figure, because the four knobs interact
    and a dollar target gives no guidance on which one to move."""
    assert set(BANDS) == {"probe", "standard", "deep"}
    widths = [BANDS[n].queries_per_cluster for n in ("probe", "standard", "deep")]
    assert widths == sorted(widths) and len(set(widths)) == 3


def test_probe_buys_no_page_fetches():
    """An Unlocker fetch is 20x a SERP call. A probe is for finding out whether
    a topic has any conversation at all; it should not pay to read pages."""
    assert BANDS["probe"].page_fetches_per_cluster == 0


def test_band_for_rejects_an_unknown_name():
    with pytest.raises(KeyError):
        band_for("enormous")


def test_create_and_read_back(store):
    t = store.create(
        name="OIC pulse",
        brand="Symproic",
        molecule="naldemedine",
        therapeutic_area="gastroenterology",
        competitors=("Relistor", "Movantik"),
        questions=("what do prescribers say about tolerability?",),
        spend_band="standard",
        never_say=("Symproic",),
    )
    again = store.get(t.topic_id)
    assert again == t
    assert again.competitors == ("Relistor", "Movantik")


def test_get_unknown_raises(store):
    with pytest.raises(NoSuchTopic):
        store.get("nope")


def test_list_is_newest_first(store):
    a = store.create(name="A", therapeutic_area="gi", spend_band="probe")
    b = store.create(name="B", therapeutic_area="gi", spend_band="probe")
    assert [t.topic_id for t in store.list()][:2] == [b.topic_id, a.topic_id]


def test_update_returns_the_new_state(store):
    t = store.create(name="A", therapeutic_area="gi", spend_band="probe")
    t2 = store.update(t.topic_id, spend_band="deep")
    assert t2.spend_band == "deep"
    assert store.get(t.topic_id).spend_band == "deep"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_topics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vsm.topics'`

- [ ] **Step 3: Write `vsm/topics/model.py`**

```python
"""What a topic is, and how much a sweep of it is allowed to buy.

A topic persists across runs. That is not a convenience — momentum and anomaly
are deltas, and a delta needs a baseline, so the unit that carries history has
to outlive a single run.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Topic", "SpendBand", "BANDS", "band_for"]


@dataclass(frozen=True)
class SpendBand:
    """One preset of the four knobs that decide what a sweep costs.

    A preset rather than a dollar target: the knobs interact, and "spend $2"
    gives an operator no guidance on which of the four to move. Each band shows
    its estimated cost on the form instead.
    """

    name: str
    queries_per_cluster: int
    serp_results_per_query: int
    discover_results_per_cluster: int
    #: Web Unlocker page fetches. A fetch is $0.03 against a SERP call's
    #: $0.0015 — twenty times more — so this is the knob that decides the bill.
    page_fetches_per_cluster: int


BANDS: dict[str, SpendBand] = {
    # Is there any conversation here at all? Search metadata only, no page reads.
    "probe": SpendBand("probe", 2, 10, 5, 0),
    "standard": SpendBand("standard", 4, 10, 10, 3),
    "deep": SpendBand("deep", 8, 20, 20, 6),
}


def band_for(name: str) -> SpendBand:
    return BANDS[name]


@dataclass(frozen=True)
class Topic:
    """A thing we watch. Its MINE runs are dated snapshots of it."""

    topic_id: str
    name: str
    therapeutic_area: str
    spend_band: str
    created_at: str
    brand: str | None = None
    molecule: str | None = None
    competitors: tuple[str, ...] = ()
    questions: tuple[str, ...] = ()
    #: G4. Terms the report may never contain. Empty is a no-op.
    never_say: tuple[str, ...] = ()

    def band(self) -> SpendBand:
        return band_for(self.spend_band)
```

- [ ] **Step 4: Write `vsm/topics/store.py`**

```python
"""Topics in SQLite. Tuple fields are stored as JSON arrays.

stdlib ``sqlite3`` on purpose: an ORM would be the tenth dependency for a
five-column table, and the schema here is small enough to read in one sitting.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vsm.errors import NoSuchTopic
from vsm.topics.model import BANDS, Topic

__all__ = ["TopicStore"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
    topic_id         TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    therapeutic_area TEXT NOT NULL,
    spend_band       TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    brand            TEXT,
    molecule         TEXT,
    competitors      TEXT NOT NULL DEFAULT '[]',
    questions        TEXT NOT NULL DEFAULT '[]',
    never_say        TEXT NOT NULL DEFAULT '[]',
    -- NOT NULL: a later task orders snapshots by this column.
    seq              INTEGER NOT NULL
);
"""

_TUPLE_FIELDS = ("competitors", "questions", "never_say")


class TopicStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self) -> closing[sqlite3.Connection]:
        """A connection that is committed **and closed**.

        ``sqlite3.Connection.__exit__`` commits or rolls back; it does not
        close. ``with self._conn() as c`` on a bare connection therefore leaks
        one per call, which surfaces as a ``ResourceWarning`` at finalisation —
        evidence, not noise. ``closing`` is the fix; silencing the warning is
        not.

        Note the shape this produces: ``closing`` yields the connection but
        does not commit, so every write path must commit explicitly.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return closing(conn)

    @staticmethod
    def _row_to_topic(row: sqlite3.Row) -> Topic:
        data: dict[str, Any] = dict(row)
        data.pop("seq", None)
        for field in _TUPLE_FIELDS:
            data[field] = tuple(json.loads(data[field]))
        return Topic(**data)

    def create(self, **kwargs: Any) -> Topic:
        if kwargs.get("spend_band") not in BANDS:
            raise KeyError(f"unknown spend band: {kwargs.get('spend_band')!r}")
        topic = Topic(
            topic_id=kwargs.pop("topic_id", None) or f"top-{uuid.uuid4().hex[:10]}",
            created_at=kwargs.pop(
                "created_at", datetime.now(timezone.utc).isoformat()
            ),
            **kwargs,
        )
        with self._conn() as c:
            c.execute(
                "INSERT INTO topics (topic_id,name,therapeutic_area,spend_band,"
                "created_at,brand,molecule,competitors,questions,never_say,seq) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,"
                "(SELECT COALESCE(MAX(seq),0)+1 FROM topics))",
                (
                    topic.topic_id,
                    topic.name,
                    topic.therapeutic_area,
                    topic.spend_band,
                    topic.created_at,
                    topic.brand,
                    topic.molecule,
                    json.dumps(list(topic.competitors)),
                    json.dumps(list(topic.questions)),
                    json.dumps(list(topic.never_say)),
                ),
            )
        return topic

    def get(self, topic_id: str) -> Topic:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM topics WHERE topic_id=?", (topic_id,)
            ).fetchone()
        if row is None:
            raise NoSuchTopic(topic_id, rule="topics")
        return self._row_to_topic(row)

    def list(self) -> list[Topic]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM topics ORDER BY seq DESC").fetchall()
        return [self._row_to_topic(r) for r in rows]

    #: Columns `update` may write. `topic_id` is the primary key and `seq` is
    #: the ordering a later task's history slicing depends on; neither is a
    #: field a caller has any business setting, and interpolating raw kwarg
    #: names into `SET {key}=?` without this would let them.
    UPDATABLE = frozenset({
        "name", "therapeutic_area", "spend_band", "brand", "molecule",
        "competitors", "questions", "never_say",
    })

    def update(self, topic_id: str, **fields: Any) -> Topic:
        current = self.get(topic_id)
        if "spend_band" in fields and fields["spend_band"] not in BANDS:
            raise KeyError(f"unknown spend band: {fields['spend_band']!r}")
        rejected = sorted(set(fields) - self.UPDATABLE)
        if rejected:
            raise KeyError(f"not updatable: {', '.join(rejected)}")
        sets, values = [], []
        for key, value in fields.items():
            sets.append(f"{key}=?")
            values.append(
                json.dumps(list(value)) if key in _TUPLE_FIELDS else value
            )
        if not sets:
            return current
        values.append(topic_id)
        with self._conn() as c:
            c.execute(f"UPDATE topics SET {','.join(sets)} WHERE topic_id=?", values)
        return self.get(topic_id)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_topics.py -v`
Expected: 7 passed

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add topics, and the three spend bands a sweep is bought in"
```

---

## Task 4: Run model, artifact store, and the storage contract

**Files:**
- Create: `vsm/runs/__init__.py`, `vsm/runs/model.py`, `vsm/runs/store.py`
- Create: `vsm/storage.py` — the Protocol both backends satisfy (spec D16)
- Test: `tests/test_runs.py`, `tests/test_storage_contract.py`

**Interfaces:**
- Consumes: `vsm.errors.NoSuchRun`
- Produces: `RunMode = Literal["mine","insight","report"]`; `RunStatus = Literal["pending","running","complete","failed","stopped_on_budget"]`; `Run` (frozen: `run_id`, `topic_id`, `mode`, `status`, `started_at`, `finished_at: str | None`, `cost_usd: float`, `parent_run_id: str | None`, `note: str`); `RunStore(db_path, var_dir)` with `.start(topic_id, mode, parent_run_id=None) -> Run`, `.finish(run_id, status, cost_usd, note="") -> Run`, `.get(run_id) -> Run`, `.for_topic(topic_id, mode=None) -> list[Run]` (oldest first), `.snapshots(topic_id) -> list[Run]` (completed MINE runs, oldest first), `.artifacts_dir(run_id) -> Path`, `.write_artifact(run_id, name, payload) -> Path`, `.read_artifact(run_id, name) -> Any`

**Why snapshots are oldest-first:** every delta pass walks history forward. Returning newest-first would make each caller reverse it, and one of them would forget.

**The storage contract (spec D16).** `vsm/storage.py` declares two `Protocol`s —
`TopicStoreLike` and `RunStoreLike` — whose members are exactly the public methods
listed above, plus `open_stores(settings) -> tuple[TopicStoreLike, RunStoreLike]`
which returns the SQLite+filesystem pair today. Task 24 adds a Postgres+blob pair
behind the same names.

Declaring the Protocol now costs about forty lines and buys one thing: the later
backend has a contract to satisfy that is checked by a shared test, rather than a
resemblance to whatever the first implementation happened to do. Write
`tests/test_storage_contract.py` as a **parametrised suite over a store factory**,
so Task 24 registers its backend and inherits every case unchanged — that shared
suite is the deliverable here, not the Protocol declaration.

Do not build a SQL dialect shim. The two backends will each write their own SQL.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_runs.py
import pytest

from vsm.errors import NoSuchRun
from vsm.runs.store import RunStore


@pytest.fixture
def store(tmp_path):
    return RunStore(tmp_path / "r.db", tmp_path / "var")


def test_start_then_finish(store):
    r = store.start("top-1", "mine")
    assert r.status == "running" and r.finished_at is None
    done = store.finish(r.run_id, "complete", cost_usd=0.0315)
    assert done.status == "complete"
    assert done.finished_at is not None
    assert done.cost_usd == pytest.approx(0.0315)


def test_get_unknown_raises(store):
    with pytest.raises(NoSuchRun):
        store.get("nope")


def test_snapshots_are_completed_mine_runs_oldest_first(store):
    """Every delta pass walks history forward, so the store hands it over in
    that order rather than making each caller remember to reverse it."""
    a = store.start("top-1", "mine")
    store.finish(a.run_id, "complete", cost_usd=0.01)
    b = store.start("top-1", "mine")
    store.finish(b.run_id, "complete", cost_usd=0.01)
    running = store.start("top-1", "mine")
    insight = store.start("top-1", "insight")
    store.finish(insight.run_id, "complete", cost_usd=0.0)

    ids = [r.run_id for r in store.snapshots("top-1")]
    assert ids == [a.run_id, b.run_id]
    assert running.run_id not in ids


def test_a_budget_stop_is_not_a_failure(store):
    """A cap breach is a clean stop with partial rows, not an error. It has its
    own status so a later reader can tell 'we stopped paying' from 'it broke'."""
    r = store.start("top-1", "mine")
    done = store.finish(r.run_id, "stopped_on_budget", cost_usd=5.0, note="cap bound at 5.0")
    assert done.status == "stopped_on_budget"
    assert "cap bound" in done.note


def test_artifacts_round_trip(store):
    r = store.start("top-1", "mine")
    path = store.write_artifact(r.run_id, "signals.json", [{"signal_id": "sig-1"}])
    assert path.exists()
    assert store.read_artifact(r.run_id, "signals.json") == [{"signal_id": "sig-1"}]


def test_artifact_name_cannot_escape_the_run_directory(store):
    r = store.start("top-1", "mine")
    with pytest.raises(ValueError):
        store.write_artifact(r.run_id, "../../etc/passwd", {})


def test_snapshot_order_follows_seq_not_the_timestamp(store):
    """Ordering is by the monotonic `seq` column, never by wall-clock time.

    Creating five runs in a loop does NOT test this: wall-clock advances on its
    own, so `ORDER BY started_at` would pass too. The timestamps are scrambled
    afterwards so that the two orderings genuinely disagree — that is the only
    version of this test that can fail against the bug it is written for.
    """
    import sqlite3 as _sqlite3

    ids = []
    for _ in range(5):
        r = store.start("top-1", "mine")
        store.finish(r.run_id, "complete", cost_usd=0.0)
        ids.append(r.run_id)

    # Reverse the timestamps against insertion order.
    stamps = [f"2026-08-{25 - i:02d}T00:00:00+00:00" for i in range(5)]
    with _sqlite3.connect(store.db_path) as conn:
        for run_id, stamp in zip(ids, stamps):
            conn.execute("UPDATE runs SET started_at=? WHERE run_id=?", (stamp, run_id))
        conn.commit()

    assert [r.run_id for r in store.snapshots("top-1")] == ids


def test_parent_run_is_recorded(store):
    mine = store.start("top-1", "mine")
    store.finish(mine.run_id, "complete", cost_usd=0.0)
    ins = store.start("top-1", "insight", parent_run_id=mine.run_id)
    assert store.get(ins.run_id).parent_run_id == mine.run_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_runs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vsm.runs'`

- [ ] **Step 3: Write `vsm/runs/model.py`**

```python
"""A run, and the five states it can end in.

``stopped_on_budget`` is a distinct terminal state, not a flavour of failure. A
cap breach produces partial rows and a recorded deferral by design; conflating
it with ``failed`` would lose the difference between "we stopped paying" and
"it broke", which is the first question anyone asks of a short run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["Run", "RunMode", "RunStatus", "RUN_MODES"]

RunMode = Literal["mine", "insight", "report"]
RunStatus = Literal["pending", "running", "complete", "failed", "stopped_on_budget"]

RUN_MODES: tuple[str, ...] = ("mine", "insight", "report")


@dataclass(frozen=True)
class Run:
    run_id: str
    topic_id: str
    mode: RunMode
    status: RunStatus
    started_at: str
    finished_at: str | None = None
    cost_usd: float = 0.0
    #: the run this one consumed — an INSIGHT's snapshot, a REPORT's insight
    parent_run_id: str | None = None
    note: str = ""
```

- [ ] **Step 4: Write `vsm/runs/store.py`**

```python
"""Run metadata in SQLite; run artifacts as files under ``var/runs/<run_id>/``.

Artifacts are files rather than blobs because they are the deliverable — an
operator hands someone `provenance_appendix.md`, and a path is easier to hand
over than a row.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vsm.errors import NoSuchRun
from vsm.runs.model import Run

__all__ = ["RunStore"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    topic_id      TEXT NOT NULL,
    mode          TEXT NOT NULL,
    status        TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    cost_usd      REAL NOT NULL DEFAULT 0.0,
    parent_run_id TEXT,
    note          TEXT NOT NULL DEFAULT '',
    -- NOT NULL because snapshot ordering depends on it: history is a slice of a
    -- seq-ordered list, and a NULL here would sort unpredictably and silently
    -- drop a baseline.
    seq           INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_topic ON runs (topic_id, mode, seq);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunStore:
    def __init__(self, db_path: Path, var_dir: Path) -> None:
        self.db_path = Path(db_path)
        self.var_dir = Path(var_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        (self.var_dir / "runs").mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(_SCHEMA)
            c.commit()

    def _conn(self) -> closing[sqlite3.Connection]:
        """A connection that is committed **and closed**.

        ``sqlite3.Connection.__exit__`` commits or rolls back; it does not
        close. ``with self._conn() as c`` on a bare connection therefore leaks
        one per call, which surfaces as a ``ResourceWarning`` at finalisation —
        evidence, not noise. ``closing`` is the fix; silencing the warning is
        not.

        Note the shape this produces: ``closing`` yields the connection but
        does not commit, so every write path must commit explicitly.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return closing(conn)

    @staticmethod
    def _to_run(row: sqlite3.Row) -> Run:
        data = dict(row)
        data.pop("seq", None)
        return Run(**data)

    def start(self, topic_id: str, mode: str, parent_run_id: str | None = None) -> Run:
        run = Run(
            run_id=f"{mode[:3]}-{uuid.uuid4().hex[:10]}",
            topic_id=topic_id,
            mode=mode,  # type: ignore[arg-type]
            status="running",
            started_at=_now(),
            parent_run_id=parent_run_id,
        )
        with self._conn() as c:
            c.execute(
                "INSERT INTO runs (run_id,topic_id,mode,status,started_at,"
                "finished_at,cost_usd,parent_run_id,note,seq) VALUES "
                "(?,?,?,?,?,NULL,0.0,?,'',"
                "(SELECT COALESCE(MAX(seq),0)+1 FROM runs))",
                (run.run_id, topic_id, mode, "running", run.started_at, parent_run_id),
            )
            # `closing` does not commit. A missed commit here loses the run
            # silently, which is worse than the leak `closing` fixes.
            c.commit()
        self.artifacts_dir(run.run_id).mkdir(parents=True, exist_ok=True)
        return run

    def finish(self, run_id: str, status: str, cost_usd: float, note: str = "") -> Run:
        with self._conn() as c:
            c.execute(
                "UPDATE runs SET status=?, finished_at=?, cost_usd=?, note=? "
                "WHERE run_id=?",
                (status, _now(), float(cost_usd), note, run_id),
            )
            c.commit()
        return self.get(run_id)

    def get(self, run_id: str) -> Run:
        with self._conn() as c:
            row = c.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise NoSuchRun(run_id, rule="runs")
        return self._to_run(row)

    def for_topic(self, topic_id: str, mode: str | None = None) -> list[Run]:
        sql = "SELECT * FROM runs WHERE topic_id=?"
        args: list[Any] = [topic_id]
        if mode:
            sql += " AND mode=?"
            args.append(mode)
        sql += " ORDER BY seq ASC"
        with self._conn() as c:
            return [self._to_run(r) for r in c.execute(sql, args).fetchall()]

    def snapshots(self, topic_id: str) -> list[Run]:
        """Completed MINE runs, **oldest first** — every delta walks forward.

        Ordered by the monotonic ``seq`` column, not by ``started_at``. Callers
        establish "before" by position in this list; comparing timestamps would
        tie whenever two runs land in the same microsecond.
        """
        return [
            r for r in self.for_topic(topic_id, "mine") if r.status == "complete"
        ]

    def artifacts_dir(self, run_id: str) -> Path:
        return self.var_dir / "runs" / run_id

    def _artifact_path(self, run_id: str, name: str) -> Path:
        base = self.artifacts_dir(run_id).resolve()
        path = (base / name).resolve()
        if base != path.parent:
            raise ValueError(f"artifact name escapes the run directory: {name!r}")
        return path

    def write_artifact(self, run_id: str, name: str, payload: Any) -> Path:
        path = self._artifact_path(run_id, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, str):
            path.write_text(payload, encoding="utf-8")
        else:
            path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def read_artifact(self, run_id: str, name: str) -> Any:
        path = self._artifact_path(run_id, name)
        text = path.read_text(encoding="utf-8")
        return json.loads(text) if path.suffix == ".json" else text
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_runs.py -v`
Expected: 8 passed

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Add runs, and make a budget stop a state of its own"
```

---

## Task 5: Vendor the LLM client, generalised to one structured-completion call

**Files:**
- Create: `vsm/llm/__init__.py`, `vsm/llm/client.py` (vendored), `vsm/llm/progress.py` (vendored), `vsm/llm/prompts.py`, `vsm/llm/schema.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Consumes: `vsm.config.Settings`, `vsm.errors.BudgetExceeded`
- Produces: `AnthropicClient` with `.complete_structured(*, system: str, user: str, schema: dict, max_output_tokens: int, on_progress=None) -> StructuredOutcome`; `StructuredOutcome` (`.ok: bool`, `.data: dict | None`, `.spend: LlmSpend`, `.reason: str`); `LlmSpend`; `get_client(settings=None) -> AnthropicClient | None`; `worst_case_usd(*, prompt_chars, max_output_tokens) -> float`; `prefix_is_cacheable(model, prompt) -> bool | None`; `progress.sink_for(run_id)`, `progress.publish(run_id, event)`

**Context for the implementer:** most of the parent's `engine/llm/client.py` is machinery worth keeping verbatim — the hand-rolled retry loop, per-attempt metering, budget re-check between attempts, spend accounting, streaming, the prompt-cache prefix check. It exists because the SDK's own `max_retries=2` billed retried-away attempts invisibly, so three generations could log as one, or as $0.00 on the failure paths. **Do not replace it with the SDK's retry.**

What changes: the parent hard-codes two output schemas (`_article_schema`, `_query_plan_schema`) and two entry points (`draft`, `plan_queries`). This fork needs one call per analysis pass, so the schema and prompts are injected instead.

- [ ] **Step 1: Copy the two modules and rewrite imports**

```bash
mkdir -p vsm/llm
cp ~/Documents/forum-engine/engine/llm/client.py ~/Documents/forum-engine/engine/llm/progress.py vsm/llm/
find vsm/llm -name '*.py' -exec sed -i '' 's/from engine\.llm/from vsm.llm/g; s/from engine\.config/from vsm.config/g; s/from engine\.errors/from vsm.errors/g' {} +
grep -rn "from engine\.\|import engine\." vsm/llm/ || echo "no parent imports remain"
```

Any remaining `engine.` import is a call into the parent's orchestrator or models — delete the code that needs it; it is article-specific and is being removed anyway.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_llm.py
import pytest

from vsm.config import Settings
from vsm.llm.client import AnthropicClient, get_client, prefix_is_cacheable

SCHEMA = {
    "type": "object",
    "properties": {"themes": {"type": "array", "items": {"type": "string"}}},
    "required": ["themes"],
}


class _FakeMessages:
    def __init__(self, payload, recorder):
        self._payload = payload
        self._recorder = recorder

    def create(self, **kwargs):
        self._recorder.append(kwargs)

        class _Block:
            type = "tool_use"
            input = self._payload

        class _Usage:
            input_tokens = 1000
            output_tokens = 200
            cache_read_input_tokens = 0
            cache_creation_input_tokens = 0

        class _Msg:
            content = [_Block()]
            usage = _Usage()

        return _Msg()


class _FakeAnthropic:
    def __init__(self, payload, recorder):
        self.messages = _FakeMessages(payload, recorder)


def test_complete_structured_returns_validated_data():
    calls = []
    client = AnthropicClient(
        sdk=_FakeAnthropic({"themes": ["tolerability", "cost"]}, calls),
        model="claude-opus-5",
        cap_usd=5.0,
    )
    out = client.complete_structured(
        system="SYS", user="USR", schema=SCHEMA, max_output_tokens=512
    )
    assert out.ok is True
    assert out.data == {"themes": ["tolerability", "cost"]}
    assert out.spend.usd() > 0


def test_the_system_prompt_is_sent_as_a_cacheable_prefix():
    """drafting-style prompts are byte-identical across runs, which is the only
    reason the cache ever hits. Interpolating a topic into the system prompt
    would make the prefix unique per run and throw that away."""
    calls = []
    client = AnthropicClient(
        sdk=_FakeAnthropic({"themes": []}, calls), model="claude-opus-5", cap_usd=5.0
    )
    client.complete_structured(system="SYS", user="USR", schema=SCHEMA, max_output_tokens=64)
    system = calls[0]["system"]
    assert isinstance(system, list)
    assert system[0]["cache_control"] == {"type": "ephemeral"}


def test_cap_blocks_before_the_call_is_made():
    from vsm.errors import BudgetExceeded

    calls = []
    client = AnthropicClient(
        sdk=_FakeAnthropic({"themes": []}, calls), model="claude-opus-5", cap_usd=0.0
    )
    with pytest.raises(BudgetExceeded):
        client.complete_structured(
            system="SYS", user="USR", schema=SCHEMA, max_output_tokens=4096
        )
    assert calls == [], "the cap must bind before spending, not after"


def test_offline_yields_no_client():
    assert get_client(Settings.from_env({"VSM_OFFLINE": "1", "ANTHROPIC_API_KEY": "sk-x"})) is None


def test_forced_llm_without_a_key_raises():
    """A run that quietly stopped generating looks identical to one that
    generated. It must fail loudly instead."""
    from vsm.errors import ConfigError

    with pytest.raises(ConfigError):
        get_client(Settings.from_env({"VSM_OFFLINE": "0", "VSM_DRAFTER": "llm"}))


def test_prefix_cacheability_is_reported_not_assumed():
    assert prefix_is_cacheable("claude-opus-5", "x" * 10) is False
    assert prefix_is_cacheable("claude-opus-5", "x" * 40_000) is True
```

- [ ] **Step 3: Reshape the client**

In `vsm/llm/client.py`:

1. **Delete** `draft`, `_stream_article`, `plan_queries`, `_article_schema`, `_query_plan_schema`, `DraftOutcome`, `_partial_str`, `_partial_headings`, and `get_drafter`. They are article-shaped and nothing here drafts an article.
2. **Rename** `AnthropicDrafter` → `AnthropicClient`.
3. **Keep verbatim:** `LlmSpend`, `UsageLike`, `_AttemptMeter`, `_status_of`, `_may_have_been_billed`, `_snapshot_usage`, `_without_sdk_retries`, `_reason_for`, `_is_retryable`, `_sleep_before_retry`, `_cap_usd`, `_check_budget`, `_meter_attempt`, `worst_case_usd`, `cache_floor_for`, `prefix_is_cacheable`, `__enter__`/`__exit__`/`close`.
4. **Rename and check the constructor.** `AnthropicClient.__init__` must accept `sdk`, `model` and `cap_usd` as keyword arguments — the tests construct it that way. The `complete_structured` body below reads `self._sdk`, `self._model`, `self._spend` and `self._max_attempts`; **verify those are the names the vendored `__init__` actually sets** and adjust either the constructor or the method so they agree. Do not guess — open the copy and look.

5. **Add** `StructuredOutcome` and `complete_structured`:

```python
@dataclass
class StructuredOutcome:
    """One structured completion, and what it cost whether or not it worked."""

    ok: bool
    data: dict[str, Any] | None
    spend: LlmSpend
    reason: str = ""


def _tool_for(schema: dict[str, Any]) -> dict[str, Any]:
    """Force structured output by making it the only thing the model can emit."""
    return {
        "name": "emit",
        "description": "Emit the result. This is the only permitted output.",
        "input_schema": schema,
    }
```

and on `AnthropicClient`:

```python
    def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        max_output_tokens: int,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> StructuredOutcome:
        """One schema-constrained completion, under the same retry and metering
        loop the parent uses.

        ``system`` is sent as a cache-controlled block. It **must** be
        byte-identical across runs or the prefix is unique per run and the cache
        never hits — which is why run-specific content belongs in ``user``.
        """
        reserve = worst_case_usd(
            prompt_chars=len(system) + len(user), max_output_tokens=max_output_tokens
        )
        blocked = self._check_budget(reserve_usd=reserve)
        if blocked:
            raise BudgetExceeded(blocked, rule="G3")

        last_reason = ""
        for attempt in range(self._max_attempts):
            meter = _AttemptMeter()
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
            except BaseException as exc:  # noqa: BLE001 — re-raised below if fatal
                self._meter_attempt(meter, exc)
                last_reason = _reason_for(exc)
                if not _is_retryable(exc, meter) or attempt == self._max_attempts - 1:
                    return StructuredOutcome(False, None, self._spend, last_reason)
                self._sleep_before_retry(attempt, exc)
                if (blocked := self._check_budget(reserve_usd=reserve)):
                    return StructuredOutcome(False, None, self._spend, blocked)
                continue

            self._spend.record(getattr(message, "usage", None))
            for block in getattr(message, "content", []) or []:
                if getattr(block, "type", "") == "tool_use":
                    data = dict(getattr(block, "input", {}) or {})
                    if on_progress:
                        on_progress({"event": "structured_done", "keys": sorted(data)})
                    return StructuredOutcome(True, data, self._spend)
            last_reason = "model returned no tool_use block"
        return StructuredOutcome(False, None, self._spend, last_reason)
```

6. **Add** `get_client`, replacing `get_drafter`:

```python
def get_client(settings_obj: Settings | None = None) -> AnthropicClient | None:
    """The client, or ``None`` when generation is off.

    ``VSM_DRAFTER=llm`` without a key **raises**. It does not fall back: a run
    that quietly stopped generating and returned nothing looks exactly like one
    that generated nothing worth returning.
    """
    s = settings_obj or get_settings()
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
```

Note `effective_drafter_mode()` returns `"llm"` for a forced mode even with no key, so the `mode == "off"` branch above only fires for `auto`-without-key or offline. Both `ConfigError` raises are needed: the first covers `VSM_DRAFTER=llm` reaching here at all, the second is the belt-and-braces.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_llm.py -v`
Expected: 6 passed

- [ ] **Step 5: Write `vsm/llm/prompts.py`**

One byte-stable system prompt per pass. Every prompt ends with the same closing paragraph:

```python
"""System prompts. Each one is a **constant** and must stay byte-identical.

The cache prefix is the system block. Interpolating a topic, a brand or a term
list into one of these makes the prefix unique per run and throws the cache
away — and the cache is most of the cost argument. Run-specific content goes in
the user message, always.
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
```

- [ ] **Step 6: Write `vsm/llm/schema.py`**

One JSON schema per pass, each `additionalProperties: False`. Schemas needed: `LEXICON_SCHEMA` (`clusters[]` of `{cluster_id, label, terms[], areas[], queries[]}`), `THEMES_SCHEMA` (`themes[]` of `{theme_id, name, signal_ids[]}`), `STANCE_SCHEMA` (`items[]` of `{signal_id, stance, rationale}` where `stance` is an enum of the five values), `ANOMALY_NARRATION_SCHEMA` (`notes[]` of `{anomaly_id, note}`), `REPORT_SCHEMA` (`sections[]` of `{heading, body, signal_ids[]}` plus `considerations[]` of `{text, signal_ids[]}`).

Each schema must set `"additionalProperties": false` and list every property in `"required"`. A schema that permits extra keys lets the model invent a field, and the first thing it invents is a confidence score.

- [ ] **Step 7: Write the prompt/guard equality test**

```python
# append to tests/test_llm.py
def test_the_two_banned_lists_are_equal():
    """If these drift, the model is told a different rule than the one that
    rejects its output."""
    from vsm.guards.advisory import BANNED_DIRECTIVES as guard
    from vsm.llm.prompts import BANNED_DIRECTIVES as prompt

    assert set(guard) == set(prompt)


def test_every_schema_forbids_extra_properties():
    """A schema that permits extra keys lets the model invent a field, and the
    first thing it invents is a confidence score."""
    import vsm.llm.schema as s

    schemas = [v for k, v in vars(s).items() if k.endswith("_SCHEMA")]
    assert schemas
    for schema in schemas:
        assert schema.get("additionalProperties") is False
```

This test imports `vsm.guards.advisory`, which does not exist until Task 16. Mark it `@pytest.mark.xfail(reason="guards land in Task 16", strict=False)` now and remove the marker in Task 16.

- [ ] **Step 8: Run the suite and commit**

Run: `pytest -q`
Expected: all pass (one xfail)

```bash
git add -A
git commit -m "Vendor the model client, and give it one call instead of two"
```

---

## Task 6: MINE — lexicon, plan, sweep, and the cost guard

**Files:**
- Create: `vsm/guards/__init__.py`, `vsm/guards/cost.py`, `vsm/modes/__init__.py`, `vsm/modes/mine.py`
- Test: `tests/test_cost.py`, `tests/test_mine.py`

**Interfaces:**
- Consumes: `Topic`, `SpendBand`, `RunStore`, `AnthropicClient`, `vsm.mining.*`
- Produces: `config_for(band) -> MiningConfig`; `estimate_run_usd(band, *, cluster_count) -> CostEstimate`; `CostEstimate` (`.serp_usd`, `.discover_usd`, `.unlocker_usd`, `.model_usd`, `.total_usd`, `.breakdown: list[dict]`); `CostCap(cap_usd)` with `.spend(amount) -> None` (raises `BudgetExceeded`) and `.remaining()`; `run_mine(topic, store, *, client=None, miner=None, cluster_count=None, cap_usd=None) -> Run`
- MINE writes exactly these artifacts: `signals.json`, `provenance.json`, `coverage.json`, `cost.json`, `plan.json`

- [ ] **Step 1: Write the cost test**

```python
# tests/test_cost.py
import pytest

from vsm.errors import BudgetExceeded
from vsm.guards.cost import SERP_USD, UNLOCKER_USD, CostCap, estimate_run_usd
from vsm.topics.model import band_for


def test_unlocker_is_twenty_times_a_serp_call():
    """The whole argument for querying the gold list first."""
    assert UNLOCKER_USD == pytest.approx(SERP_USD * 20)


def test_probe_costs_less_than_standard_costs_less_than_deep():
    totals = [
        estimate_run_usd(band_for(n), cluster_count=3).total_usd
        for n in ("probe", "standard", "deep")
    ]
    assert totals == sorted(totals) and len(set(totals)) == 3


def test_a_probe_buys_no_page_fetches_so_costs_nothing_for_them():
    est = estimate_run_usd(band_for("probe"), cluster_count=3)
    assert est.unlocker_usd == 0.0


def test_the_breakdown_names_every_line():
    est = estimate_run_usd(band_for("standard"), cluster_count=2)
    assert {line["item"] for line in est.breakdown} == {
        "serp", "discover", "unlocker", "model"
    }
    assert est.total_usd == pytest.approx(sum(line["usd"] for line in est.breakdown))


def test_the_cap_binds_and_reports_what_was_left():
    cap = CostCap(0.10)
    cap.spend(0.06)
    assert cap.remaining() == pytest.approx(0.04)
    with pytest.raises(BudgetExceeded, match="0.10"):
        cap.spend(0.09)


def test_spend_that_breaches_is_not_recorded():
    """A clean stop leaves the ledger truthful — we did not spend what we
    refused to spend."""
    cap = CostCap(0.10)
    cap.spend(0.06)
    with pytest.raises(BudgetExceeded):
        cap.spend(0.09)
    assert cap.spent() == pytest.approx(0.06)
```

- [ ] **Step 2: Run it, watch it fail**

Run: `pytest tests/test_cost.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vsm.guards'`

- [ ] **Step 3: Write `vsm/guards/cost.py`**

```python
"""G3 — the estimate, and the cap that binds before anything is bought.

Prices are the parent engine's verified figures. A SERP request is $0.0015 and
a successful Web Unlocker page fetch is $0.03 — twenty times more. That ratio is
the entire cost argument for querying a curated venue list before the open web,
and it is why ``page_fetches_per_cluster`` is the knob that decides the bill.

The Bright Data account is shared with other Vi projects, so the cap is tight on
purpose. Raise it per run, knowingly; never by editing the default upward.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from vsm.errors import BudgetExceeded
from vsm.topics.model import SpendBand

__all__ = [
    "SERP_USD",
    "DISCOVER_USD",
    "UNLOCKER_USD",
    "MODEL_USD_PER_CLUSTER",
    "CostEstimate",
    "CostCap",
    "estimate_run_usd",
]

SERP_USD = 0.0015
DISCOVER_USD = 0.0015
UNLOCKER_USD = 0.03
#: Rough, and labelled as rough. A parent campaign ran ~$1 of model across far
#: more generation than a MINE lexicon call; this is deliberately generous so
#: the estimate shown to an operator is never an underestimate.
MODEL_USD_PER_CLUSTER = 0.05


@dataclass(frozen=True)
class CostEstimate:
    serp_usd: float
    discover_usd: float
    unlocker_usd: float
    model_usd: float
    breakdown: list[dict[str, Any]]

    @property
    def total_usd(self) -> float:
        return round(
            self.serp_usd + self.discover_usd + self.unlocker_usd + self.model_usd, 4
        )


def estimate_run_usd(band: SpendBand, *, cluster_count: int) -> CostEstimate:
    serp = band.queries_per_cluster * cluster_count * SERP_USD
    discover = band.discover_results_per_cluster * cluster_count * DISCOVER_USD
    unlocker = band.page_fetches_per_cluster * cluster_count * UNLOCKER_USD
    model = cluster_count * MODEL_USD_PER_CLUSTER
    return CostEstimate(
        serp_usd=round(serp, 4),
        discover_usd=round(discover, 4),
        unlocker_usd=round(unlocker, 4),
        model_usd=round(model, 4),
        breakdown=[
            {"item": "serp", "usd": round(serp, 4),
             "note": f"{band.queries_per_cluster} queries x {cluster_count} clusters"},
            {"item": "discover", "usd": round(discover, 4),
             "note": f"{band.discover_results_per_cluster} results x {cluster_count} clusters"},
            {"item": "unlocker", "usd": round(unlocker, 4),
             "note": f"{band.page_fetches_per_cluster} fetches x {cluster_count} clusters"},
            {"item": "model", "usd": round(model, 4), "note": "lexicon + naming, approximate"},
        ],
    )


@dataclass
class CostCap:
    """Refuses the spend that would breach, and stays truthful about the rest.

    A refused spend is **not** recorded. The ledger should say what was bought,
    and we did not buy the thing we declined to pay for.
    """

    cap_usd: float
    _spent: float = field(default=0.0, init=False)

    def spent(self) -> float:
        return round(self._spent, 6)

    def remaining(self) -> float:
        return round(max(0.0, self.cap_usd - self._spent), 6)

    def would_breach(self, amount: float) -> bool:
        return (self._spent + amount) > self.cap_usd + 1e-9

    def spend(self, amount: float) -> None:
        if self.would_breach(amount):
            raise BudgetExceeded(
                f"spending {amount:.4f} would pass the cap of {self.cap_usd:.2f} "
                f"(spent {self.spent():.4f})",
                rule="G3",
            )
        self._spent += amount
```

- [ ] **Step 4: Run the cost test**

Run: `pytest tests/test_cost.py -v`
Expected: 6 passed

- [ ] **Step 5: Write the MINE test**

```python
# tests/test_mine.py
import pytest

from vsm.modes.mine import run_mine
from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore


class _FakeMiner:
    """Stands in for LiveSignalMining. Returns two rows on distinct domains."""

    def __init__(self, rows=None, cost=0.0315):
        self.rows = rows if rows is not None else [
            {"signal_id": "sig-a", "venue": "agajournals.org",
             "url": "https://agajournals.org/a", "theme": "tolerability",
             "collection_tier": "B", "collection_method": "serp_result",
             "captured_at": "2026-08-25T00:00:00+00:00", "sentiment": None},
            {"signal_id": "sig-b", "venue": "reddit.com",
             "url": "https://reddit.com/r/x/b", "theme": "cost",
             "collection_tier": "B", "collection_method": "serp_result",
             "captured_at": "2026-08-25T00:00:00+00:00", "sentiment": None},
        ]
        self.cost = cost

    def run(self, *, campaign_id, clusters, queries_per_cluster=None):
        # Matches LiveSignalMining.run exactly: keyword-only, campaign_id
        # required, and the config lives on the constructor, not here.
        class _Outcome:
            rows = self.rows
            cost_usd = self.cost
            queries_run = ["q1", "q2"]
            venues_attempted = ["agajournals.org", "reddit.com"]
            venues_collected = ["agajournals.org", "reddit.com"]
            venues_restricted = []
            denied = []
            deferrals = []
            notes = []
            calls = []
            plan = [{"query": "q1", "kind": "gold"}]
            provenance = {"provider": "fake"}

        return _Outcome()


@pytest.fixture
def stores(tmp_path):
    return TopicStore(tmp_path / "db"), RunStore(tmp_path / "db", tmp_path / "var")


def _topic(ts, band="standard"):
    return ts.create(name="OIC", therapeutic_area="gastroenterology", spend_band=band,
                     molecule="naldemedine")


def test_mine_writes_its_five_artifacts(stores):
    ts, rs = stores
    topic = _topic(ts)
    run = run_mine(topic, rs, miner=_FakeMiner(), cluster_count=1)
    for name in ("signals.json", "provenance.json", "coverage.json", "cost.json", "plan.json"):
        assert (rs.artifacts_dir(run.run_id) / name).exists(), name


def test_mine_stamps_every_row_with_the_topic_and_snapshot(stores):
    """Without these a row cannot be placed in a series, and momentum has
    nothing to compare against."""
    ts, rs = stores
    topic = _topic(ts)
    run = run_mine(topic, rs, miner=_FakeMiner(), cluster_count=1)
    rows = rs.read_artifact(run.run_id, "signals.json")
    assert rows and all(r["topic_id"] == topic.topic_id for r in rows)
    assert all(r["snapshot_at"] == run.started_at for r in rows)


def test_mine_completes_and_records_its_cost(stores):
    ts, rs = stores
    run = run_mine(_topic(ts), rs, miner=_FakeMiner(cost=0.0315), cluster_count=1)
    assert run.status == "complete"
    assert run.cost_usd == pytest.approx(0.0315)


def test_a_cap_breach_stops_cleanly_with_partial_rows(stores):
    """Not an exception at the pipeline: partial rows, a recorded deferral, and
    a status that says we stopped paying rather than that it broke."""
    ts, rs = stores
    topic = ts.create(name="OIC", therapeutic_area="gi", spend_band="deep")
    run = run_mine(topic, rs, miner=_FakeMiner(cost=99.0), cluster_count=1, cap_usd=0.05)
    assert run.status == "stopped_on_budget"
    assert rs.read_artifact(run.run_id, "signals.json") == []
    cost = rs.read_artifact(run.run_id, "cost.json")
    assert cost["stopped"] is True
    assert "cap" in cost["reason"].lower()


def test_coverage_records_venues_that_answered_and_that_did_not(stores):
    """A silent filter is indistinguishable from finding nothing."""
    ts, rs = stores
    run = run_mine(_topic(ts), rs, miner=_FakeMiner(), cluster_count=1)
    coverage = rs.read_artifact(run.run_id, "coverage.json")
    assert set(coverage["venues_attempted"]) >= set(coverage["venues_collected"])
    assert "venues_empty" in coverage
```

- [ ] **Step 6: Run it, watch it fail**

Run: `pytest tests/test_mine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vsm.modes'`

- [ ] **Step 7: Write `vsm/modes/mine.py`**

```python
"""MINE — one dated snapshot of a topic.

Order of operations, and why:

1. **Lexicon.** The model turns the topic into clusters and query strings. It
   contributes *strings only* — gold routing, ``site:`` scoping, band widths and
   the recency split all stay deterministic, which is what makes an offline dry
   run rehearse the live sweep query-for-query.
2. **Estimate, then cap.** The estimate is computed before a single call, and
   the cap is checked against it. A cap that binds after the spend is not a cap.
3. **Sweep.** Gold-scoped SERP first, Discover per cluster, open web only as a
   tail if the gold list under-delivers, page fetches last and fewest.
4. **Stamp and write.** Every row carries ``topic_id`` and ``snapshot_at`` so it
   can be placed in a series.

A cap breach ends the run at ``stopped_on_budget`` with whatever rows exist. It
does not raise past this function: overspending is the failure, stopping is not.
"""

from __future__ import annotations

from typing import Any

from vsm.errors import BudgetExceeded
from vsm.guards.cost import CostCap, estimate_run_usd
from vsm.llm.prompts import LEXICON_SYSTEM
from vsm.llm.schema import LEXICON_SCHEMA
from vsm.mining.miner import MiningConfig
from vsm.runs.model import Run
from vsm.runs.store import RunStore
from vsm.topics.model import SpendBand, Topic

__all__ = ["run_mine", "build_clusters", "config_for"]


def config_for(band: SpendBand) -> MiningConfig:
    """A spend band → the vendored miner's config.

    Handed to ``LiveSignalMining(config=...)`` at construction. It is not a
    ``run()`` argument — the parent's ``run()`` takes only ``campaign_id``,
    ``clusters`` and an optional per-cluster query override.
    """
    return MiningConfig(
        queries_per_cluster=band.queries_per_cluster,
        serp_results_per_query=band.serp_results_per_query,
        discover_results_per_cluster=band.discover_results_per_cluster,
        page_fetches_per_cluster=band.page_fetches_per_cluster,
        fetch_pages=band.page_fetches_per_cluster > 0,
    )


def build_clusters(topic: Topic, client: Any | None) -> list[dict[str, Any]]:
    """Topic → clusters. Falls back to a deterministic single cluster offline.

    The fallback is not a degraded model call; it is the honest offline shape,
    and it is what ``VSM_MINER=fake`` demonstrations run on.
    """
    if client is None:
        terms = [t for t in (topic.brand, topic.molecule, *topic.competitors) if t]
        return [
            {
                "cluster_id": "c1",
                "label": topic.name,
                "terms": terms or [topic.name],
                "areas": [topic.therapeutic_area],
            }
        ]
    user = (
        f"Topic: {topic.name}\n"
        f"Therapeutic area: {topic.therapeutic_area}\n"
        f"Brand: {topic.brand or '(none)'}\n"
        f"Molecule (INN): {topic.molecule or '(none)'}\n"
        f"Competitors: {', '.join(topic.competitors) or '(none)'}\n"
        f"Questions we care about:\n"
        + "\n".join(f"- {q}" for q in topic.questions)
    )
    out = client.complete_structured(
        system=LEXICON_SYSTEM, user=user, schema=LEXICON_SCHEMA, max_output_tokens=2048
    )
    if not out.ok or not out.data:
        raise RuntimeError(f"lexicon pass failed: {out.reason}")
    return list(out.data.get("clusters", []))


def run_mine(
    topic: Topic,
    store: RunStore,
    *,
    client: Any | None = None,
    miner: Any | None = None,
    cluster_count: int | None = None,
    cap_usd: float | None = None,
) -> Run:
    band = topic.band()
    run = store.start(topic.topic_id, "mine")

    clusters = build_clusters(topic, client)
    n = cluster_count if cluster_count is not None else len(clusters)
    estimate = estimate_run_usd(band, cluster_count=n)
    cap = CostCap(cap_usd if cap_usd is not None else 5.0)

    # MiningConfig is CONSTRUCTOR state on LiveSignalMining, not a run()
    # argument. A caller that wants a configured live miner builds it with
    # `LiveSignalMining(serp=..., config=config_for(band))` and passes it in;
    # `run_mine` only decides the shape, so a test can inject a fake.
    stopped, reason, outcome = False, "", None
    try:
        cap.spend(estimate.total_usd)
    except BudgetExceeded as exc:
        stopped, reason = True, str(exc)

    if not stopped and miner is not None:
        # `campaign_id` is the vendored miner's name for what this fork calls a
        # topic. They are the same value; both land on the row (see below).
        outcome = miner.run(campaign_id=topic.topic_id, clusters=clusters)
        try:
            cap.spend(max(0.0, outcome.cost_usd - estimate.total_usd))
        except BudgetExceeded as exc:
            stopped, reason = True, str(exc)

    rows: list[dict[str, Any]] = []
    if outcome is not None and not stopped:
        for row in outcome.rows:
            enriched = dict(row)
            # `campaign_id` is already on the row — the vendored `build_row`
            # puts it there, and the parity fixtures assert on it, so it stays.
            # `topic_id` is this fork's name for the same value and is what
            # every analysis pass reads. Equal by construction, and the spec
            # (§3.1) names `topic_id` as the key build_row gains.
            enriched["topic_id"] = topic.topic_id
            enriched["snapshot_at"] = run.started_at
            rows.append(enriched)

    store.write_artifact(run.run_id, "signals.json", rows)
    store.write_artifact(
        run.run_id,
        "provenance.json",
        {
            "provider": getattr(outcome, "provenance", {}) if outcome else {},
            "queries_run": list(getattr(outcome, "queries_run", [])) if outcome else [],
            "calls": list(getattr(outcome, "calls", [])) if outcome else [],
            "denied": list(getattr(outcome, "denied", [])) if outcome else [],
            "deferrals": list(getattr(outcome, "deferrals", [])) if outcome else [],
        },
    )
    attempted = list(getattr(outcome, "venues_attempted", [])) if outcome else []
    collected = list(getattr(outcome, "venues_collected", [])) if outcome else []
    store.write_artifact(
        run.run_id,
        "coverage.json",
        {
            "venues_attempted": attempted,
            "venues_collected": collected,
            # Named explicitly: a venue that answered with nothing is a finding,
            # and a silent filter is indistinguishable from finding nothing.
            "venues_empty": sorted(set(attempted) - set(collected)),
            "venues_restricted": list(getattr(outcome, "venues_restricted", [])) if outcome else [],
            "notes": list(getattr(outcome, "notes", [])) if outcome else [],
        },
    )
    store.write_artifact(
        run.run_id,
        "cost.json",
        {
            "estimate_usd": estimate.total_usd,
            "breakdown": estimate.breakdown,
            "actual_usd": round(getattr(outcome, "cost_usd", 0.0), 6) if outcome and not stopped else 0.0,
            "cap_usd": cap.cap_usd,
            "spent_usd": cap.spent(),
            "stopped": stopped,
            "reason": reason,
        },
    )
    store.write_artifact(
        run.run_id, "plan.json",
        {"clusters": clusters, "plan": list(getattr(outcome, "plan", [])) if outcome else []},
    )

    return store.finish(
        run.run_id,
        "stopped_on_budget" if stopped else "complete",
        cost_usd=cap.spent() if stopped else round(getattr(outcome, "cost_usd", 0.0), 6),
        note=reason,
    )
```

- [ ] **Step 8: Run the suite**

Run: `pytest -q`
Expected: all pass (one xfail from Task 5)

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Add MINE, and make the cap bind before the first call"
```

---

## Task 7: The author-resolution seam

**Files:**
- Create: `vsm/analysis/__init__.py`, `vsm/analysis/authorclass.py`
- Test: `tests/test_authorclass.py`

**Interfaces:**
- Consumes: `vsm.mining.venues.kind_of`
- Produces: `AuthorClassValue = Literal["hcp","patient","institutional","unknown"]`; `AuthorClass` (frozen: `value`, `basis: Literal["venue","identity"]`, `confidence: float | None`, `rationale: str`, `npi: str | None = None`); `VenueResolver` with `.resolve(signal) -> AuthorClass`; `Resolver` protocol; `KIND_TO_CLASS: dict[str, AuthorClassValue]`

**Why this exists (spec §3.3):** O2 is answered — the social-handle → NPI join is permitted — but it is a data-engineering problem against Provider360 and the Pipl bridge, not a feature of this UI. This module is the seam it drops into. `stance.py` and `duallens.py` take an `AuthorClass`, never a venue, so swapping the resolver changes no code downstream. And the **basis travels**: "HCP" inferred from a venue and "HCP" proven from an NPI are different claims, and a report that prints them identically lies about the stronger one.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_authorclass.py
from vsm.analysis.authorclass import AuthorClass, VenueResolver


def sig(venue, **kw):
    return {"signal_id": "sig-1", "venue": venue, "url": f"https://{venue}/x", **kw}


def test_hcp_discussion_venue_yields_hcp_on_a_venue_basis():
    got = VenueResolver().resolve(sig("studentdoctor.net"))
    assert got.value == "hcp"
    assert got.basis == "venue"
    assert got.npi is None


def test_patient_community_yields_patient():
    got = VenueResolver().resolve(sig("patient.info"))
    assert got.value == "patient"


def test_guideline_and_evidence_venues_are_institutional():
    """A journal is not a person. Counting it as clinician sentiment would be
    the same error as counting a press release as a customer review."""
    for venue in ("gastro.org", "pubmed.ncbi.nlm.nih.gov"):
        assert VenueResolver().resolve(sig(venue)).value == "institutional"


def test_an_unregistered_venue_is_unknown_not_guessed():
    got = VenueResolver().resolve(sig("some-random-blog.example"))
    assert got.value == "unknown"
    assert "not in the registry" in got.rationale


def test_the_rationale_always_says_the_basis_out_loud():
    got = VenueResolver().resolve(sig("studentdoctor.net"))
    assert "venue" in got.rationale.lower()


def test_venue_basis_never_carries_an_npi():
    """The seam's whole point: a venue-derived class cannot assert identity."""
    got = VenueResolver().resolve(sig("studentdoctor.net"))
    assert got.npi is None and got.basis == "venue"


def test_an_identity_resolver_satisfies_the_same_protocol():
    """Proves §3.3 is a seam and not a comment. This stub is what the v2
    Provider360 resolver will replace."""

    class StubIdentityResolver:
        def resolve(self, signal):
            return AuthorClass(
                value="hcp", basis="identity", confidence=0.97,
                rationale="handle matched NPI 1234567890 via the provider graph",
                npi="1234567890",
            )

    got = StubIdentityResolver().resolve(sig("x.com"))
    assert got.basis == "identity" and got.npi == "1234567890"
```

- [ ] **Step 2: Run it, watch it fail**

Run: `pytest tests/test_authorclass.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vsm.analysis'`

- [ ] **Step 3: Write `vsm/analysis/authorclass.py`**

```python
"""Who is speaking — the only place any pass is allowed to ask.

**v1 answers from the venue.** The gold-list registry already classifies every
domain by ``kind``, so "this came from an HCP-discussion venue" is computable
without resolving anybody's identity. That is a weaker claim than "a clinician
wrote this", and the difference is recorded rather than smoothed over.

**v2 will answer from identity.** The social-handle → NPI join against
Provider360 and the Pipl bridge is permitted (spec O2, answered 2026-08-25) and
is scoped as its own piece of work. When it lands it implements ``Resolver`` and
nothing downstream changes — asserted by a test that runs the consuming passes
against a stub identity resolver.

Two rules make the seam worth having:

* Consumers take an :class:`AuthorClass`, never a venue. ``stance`` and
  ``duallens`` must not be able to tell which resolver ran.
* ``basis`` travels into the report, always. "HCP" from a venue and "HCP" from
  an NPI are different claims, and printing them identically would overstate
  the weaker one — the same category of error as asserting a trust state you
  have not earned.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Protocol

from vsm.mining.venues import kind_of

__all__ = [
    "AuthorClass",
    "AuthorClassValue",
    "Resolver",
    "VenueResolver",
    "KIND_TO_CLASS",
]

AuthorClassValue = Literal["hcp", "patient", "institutional", "unknown"]

#: The registry has exactly six kinds. There is no ``press`` class because there
#: is no press kind — inventing one would mean inventing the venues to fill it.
KIND_TO_CLASS: dict[str, AuthorClassValue] = {
    "hcp_discussion": "hcp",
    "patient_community": "patient",
    "evidence": "institutional",
    "guideline_body": "institutional",
    "regulatory": "institutional",
    "drug_reference": "institutional",
}


@dataclass(frozen=True)
class AuthorClass:
    value: AuthorClassValue
    basis: Literal["venue", "identity"]
    confidence: float | None
    rationale: str
    #: Only ever set on an identity basis. A venue can never supply one.
    npi: str | None = None


class Resolver(Protocol):
    def resolve(self, signal: Mapping[str, Any]) -> AuthorClass: ...


class VenueResolver:
    """v1. Reads the registry's ``kind`` and says so."""

    basis = "venue"

    def resolve(self, signal: Mapping[str, Any]) -> AuthorClass:
        venue = str(signal.get("venue") or "")
        kind = kind_of(venue)
        value = KIND_TO_CLASS.get(kind)
        if value is None:
            return AuthorClass(
                value="unknown",
                basis="venue",
                confidence=None,
                rationale=(
                    f"{venue!r} is not in the registry, so its author class is "
                    "unknown; nothing is inferred from the URL or a username"
                ),
            )
        return AuthorClass(
            value=value,
            basis="venue",
            confidence=None,
            rationale=(
                f"venue {venue!r} is registered as {kind!r}; the class is derived "
                "from the venue, not from the identity of any author"
            ),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_authorclass.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add the author-resolution seam, and make the basis travel with the class"
```

---

## Task 8: Entity resolution

**Files:**
- Create: `vsm/analysis/resolve.py`
- Test: `tests/test_resolve.py`

**Interfaces:**
- Consumes: `Topic`
- Produces: `Entity` (frozen: `entity_id`, `canonical`, `role: Literal["ours","competitor","class","unmapped"]`, `aliases: tuple[str, ...]`); `build_lexicon(topic) -> list[Entity]`; `resolve_signals(signals, entities) -> dict[str, Any]` returning `{"entities": [...], "by_signal": {signal_id: [entity_id, ...]}, "unmapped_mentions": [...]}`

**Rung 2.** Collapses "Symproic", "naldemedine" and "that OIC drug" onto one node so a count means something. Matching is case-insensitive whole-word against title, description, theme and excerpt.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_resolve.py
from vsm.analysis.resolve import build_lexicon, resolve_signals
from vsm.topics.model import Topic

TOPIC = Topic(
    topic_id="t1", name="OIC pulse", therapeutic_area="gastroenterology",
    spend_band="standard", created_at="2026-08-25T00:00:00+00:00",
    brand="Symproic", molecule="naldemedine", competitors=("Relistor", "Movantik"),
)


def sig(sid, text):
    return {"signal_id": sid, "venue": "example.org", "theme": text,
            "excerpt": text, "url": f"https://example.org/{sid}"}


def test_brand_and_molecule_collapse_to_one_entity():
    ents = build_lexicon(TOPIC)
    ours = [e for e in ents if e.role == "ours"]
    assert len(ours) == 1
    assert set(ours[0].aliases) >= {"symproic", "naldemedine"}


def test_each_competitor_is_its_own_entity():
    ents = build_lexicon(TOPIC)
    assert {e.canonical for e in ents if e.role == "competitor"} == {"Relistor", "Movantik"}


def test_two_names_for_our_product_resolve_to_the_same_node():
    ents = build_lexicon(TOPIC)
    out = resolve_signals([sig("s1", "Symproic tolerability"), sig("s2", "naldemedine dosing")], ents)
    assert out["by_signal"]["s1"] == out["by_signal"]["s2"]


def test_matching_is_whole_word_not_substring():
    """'Movantik' must not match inside 'Movantikular'. Substring matching is
    how a brand monitor ends up reporting on an unrelated product."""
    ents = build_lexicon(TOPIC)
    out = resolve_signals([sig("s1", "the Movantikular approach")], ents)
    assert out["by_signal"]["s1"] == []


def test_matching_is_case_insensitive():
    ents = build_lexicon(TOPIC)
    out = resolve_signals([sig("s1", "RELISTOR was discussed")], ents)
    assert len(out["by_signal"]["s1"]) == 1


def test_a_signal_matching_nothing_is_recorded_not_dropped():
    ents = build_lexicon(TOPIC)
    out = resolve_signals([sig("s1", "unrelated chatter")], ents)
    assert out["by_signal"]["s1"] == []
    assert "s1" in out["unmapped_mentions"]
```

- [ ] **Step 2: Run it, watch it fail**

Run: `pytest tests/test_resolve.py -v`
Expected: FAIL — no module `vsm.analysis.resolve`

- [ ] **Step 3: Write `vsm/analysis/resolve.py`**

```python
"""Rung 2 — mention to entity, so a count means something.

"Symproic", "naldemedine" and a bare mention of the molecule are one node, not
three. Without this a volume figure is a word-frequency table wearing a product
name, which is the failure mode the research file describes as rung 0.

Matching is **whole-word and case-insensitive**. Substring matching is how a
brand monitor starts reporting on an unrelated product that happens to contain
the brand's letters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping, Sequence

from vsm.topics.model import Topic

__all__ = ["Entity", "build_lexicon", "resolve_signals"]

Role = Literal["ours", "competitor", "class", "unmapped"]

_SEARCHED_FIELDS = ("theme", "excerpt", "title", "description")


@dataclass(frozen=True)
class Entity:
    entity_id: str
    canonical: str
    role: Role
    #: lower-cased; every string that means this entity
    aliases: tuple[str, ...]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def build_lexicon(topic: Topic) -> list[Entity]:
    """Topic → the entities worth resolving against.

    The brand and the molecule are **one** entity: they name the same product,
    and splitting them would halve every count about it.
    """
    entities: list[Entity] = []
    ours = [t for t in (topic.brand, topic.molecule) if t]
    if ours:
        entities.append(
            Entity(
                entity_id=f"ent-{_slug(ours[0])}",
                canonical=ours[0],
                role="ours",
                aliases=tuple(sorted({t.lower() for t in ours})),
            )
        )
    for competitor in topic.competitors:
        entities.append(
            Entity(
                entity_id=f"ent-{_slug(competitor)}",
                canonical=competitor,
                role="competitor",
                aliases=(competitor.lower(),),
            )
        )
    return entities


def _haystack(signal: Mapping[str, Any]) -> str:
    parts = [str(signal.get(f) or "") for f in _SEARCHED_FIELDS]
    return " ".join(parts).lower()


def _matches(haystack: str, alias: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", haystack) is not None


def resolve_signals(
    signals: Sequence[Mapping[str, Any]], entities: Iterable[Entity]
) -> dict[str, Any]:
    entities = list(entities)
    by_signal: dict[str, list[str]] = {}
    unmapped: list[str] = []
    for signal in signals:
        sid = str(signal["signal_id"])
        haystack = _haystack(signal)
        hits = [
            e.entity_id
            for e in entities
            if any(_matches(haystack, alias) for alias in e.aliases)
        ]
        by_signal[sid] = hits
        if not hits:
            # Recorded, never dropped: a signal that matched nothing is a fact
            # about our lexicon as much as about the signal.
            unmapped.append(sid)
    return {
        "entities": [
            {"entity_id": e.entity_id, "canonical": e.canonical,
             "role": e.role, "aliases": list(e.aliases)}
            for e in entities
        ],
        "by_signal": by_signal,
        "unmapped_mentions": unmapped,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_resolve.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Resolve mentions to entities, matching whole words only"
```

---

## Task 9: Corroboration, independence, and the G6 gate

**Files:**
- Create: `vsm/analysis/corroborate.py`, `vsm/guards/corroboration.py`
- Test: `tests/test_corroborate.py`

**Interfaces:**
- Consumes: `vsm.mining.tiers.registrable_domain`
- Produces: `Tier = Literal["corroborated","emerging","single_source"]`; `Finding` (frozen: `finding_id`, `statement`, `signal_ids: tuple[str, ...]`, `independent_sources: int`, `tier`); `independent_source_count(signals) -> int`; `tier_for_count(n) -> Tier`; `corroborate(claims, signals_by_id) -> list[Finding]`; guard `assert_body_is_corroborated(findings) -> None` raising `GuardViolation`

**The rule, and where it comes from.** Tastewise's published discipline is that three independent sources must align before a finding is high-confidence. We adopt it with our own definition of independence: two signals are **not** independent if they share a registrable domain **or** share a normalised title. The second clause is what makes five syndicated copies of one press release count once — the case that would otherwise manufacture confidence out of a single PR.

Independence is therefore a connected-components count: link signals that share a domain or a title, and count the components.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_corroborate.py
import pytest

from vsm.analysis.corroborate import (
    Finding, corroborate, independent_source_count, tier_for_count,
)
from vsm.errors import GuardViolation
from vsm.guards.corroboration import assert_body_is_corroborated


def sig(sid, venue, title):
    return {"signal_id": sid, "venue": venue, "title": title,
            "url": f"https://{venue}/{sid}"}


def test_three_distinct_domains_are_three_sources():
    rows = [sig("a", "gastro.org", "AGA updates OIC guidance"),
            sig("b", "reddit.com", "anyone using naldemedine?"),
            sig("c", "medscape.com", "OIC management review")]
    assert independent_source_count(rows) == 3


def test_subdomains_of_one_host_are_one_source():
    rows = [sig("a", "op-med.doximity.com", "one"), sig("b", "www.doximity.com", "two")]
    assert independent_source_count(rows) == 1


def test_five_syndicated_copies_of_one_release_count_once():
    """The case that would otherwise manufacture confidence out of a single PR."""
    title = "Company announces positive topline results"
    rows = [sig(str(i), f"outlet{i}.com", title) for i in range(5)]
    assert independent_source_count(rows) == 1


def test_syndication_plus_one_genuine_source_is_two():
    title = "Company announces positive topline results"
    rows = [sig(str(i), f"outlet{i}.com", title) for i in range(4)]
    rows.append(sig("real", "reddit.com", "what do people make of this?"))
    assert independent_source_count(rows) == 2


def test_titles_differing_only_in_case_and_space_are_the_same():
    rows = [sig("a", "x.com", "OIC Guidance  Updated"),
            sig("b", "y.com", "oic guidance updated")]
    assert independent_source_count(rows) == 1


def test_the_three_tiers():
    assert tier_for_count(3) == "corroborated"
    assert tier_for_count(5) == "corroborated"
    assert tier_for_count(2) == "emerging"
    assert tier_for_count(1) == "single_source"
    assert tier_for_count(0) == "single_source"


def test_corroborate_assembles_findings_with_their_tier():
    by_id = {r["signal_id"]: r for r in [
        sig("a", "gastro.org", "one"), sig("b", "reddit.com", "two"),
        sig("c", "medscape.com", "three"), sig("d", "gastro.org", "four"),
    ]}
    findings = corroborate(
        [{"statement": "Tolerability is the dominant concern",
          "signal_ids": ["a", "b", "c"]},
         {"statement": "Cost comes up occasionally", "signal_ids": ["d"]}],
        by_id,
    )
    assert findings[0].tier == "corroborated"
    assert findings[0].independent_sources == 3
    assert findings[1].tier == "single_source"


def test_g6_blocks_an_uncorroborated_finding_in_the_body():
    weak = Finding("f1", "x", ("a",), 1, "single_source")
    with pytest.raises(GuardViolation, match="single_source"):
        assert_body_is_corroborated([weak])


def test_g6_passes_a_corroborated_body():
    ok = Finding("f1", "x", ("a", "b", "c"), 3, "corroborated")
    assert_body_is_corroborated([ok]) is None
```

- [ ] **Step 2: Run it, watch it fail**

Run: `pytest tests/test_corroborate.py -v`
Expected: FAIL — no module `vsm.analysis.corroborate`

- [ ] **Step 3: Write `vsm/analysis/corroborate.py`**

```python
"""Rung 4 — how many *independent* sources say this, and what that earns.

Tastewise publishes the rule: three independent sources must align before a
finding is high-confidence. The rule is only as good as the definition of
independent, so here is ours.

Two signals are **not** independent when they share a registrable domain, or
when they share a normalised title. The first clause collapses subdomains of one
publisher. The second collapses syndication — five outlets carrying the same
press release are one source, and counting them as five is how a single PR gets
promoted into a corroborated finding.

That makes independence a connected-components count: link signals that share a
domain or a title, then count the components.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from vsm.mining.tiers import registrable_domain

__all__ = [
    "Finding",
    "Tier",
    "CORROBORATED_AT",
    "independent_source_count",
    "tier_for_count",
    "corroborate",
]

Tier = Literal["corroborated", "emerging", "single_source"]

#: Tastewise's published threshold, adopted deliberately rather than invented.
CORROBORATED_AT = 3

_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Finding:
    finding_id: str
    statement: str
    signal_ids: tuple[str, ...]
    independent_sources: int
    tier: Tier


def _norm_title(signal: Mapping[str, Any]) -> str:
    return _WS.sub(" ", str(signal.get("title") or "")).strip().lower()


class _Union:
    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def find(self, key: str) -> str:
        self._parent.setdefault(key, key)
        while self._parent[key] != key:
            self._parent[key] = self._parent[self._parent[key]]
            key = self._parent[key]
        return key

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra


def independent_source_count(signals: Sequence[Mapping[str, Any]]) -> int:
    """Connected components under "same domain OR same title"."""
    if not signals:
        return 0
    uf = _Union()
    by_domain: dict[str, str] = {}
    by_title: dict[str, str] = {}
    for signal in signals:
        sid = str(signal["signal_id"])
        uf.find(sid)
        domain = registrable_domain(str(signal.get("venue") or ""))
        if domain:
            if domain in by_domain:
                uf.union(by_domain[domain], sid)
            else:
                by_domain[domain] = sid
        title = _norm_title(signal)
        if title:
            if title in by_title:
                uf.union(by_title[title], sid)
            else:
                by_title[title] = sid
    return len({uf.find(str(s["signal_id"])) for s in signals})


def tier_for_count(n: int) -> Tier:
    if n >= CORROBORATED_AT:
        return "corroborated"
    if n == 2:
        return "emerging"
    return "single_source"


def corroborate(
    claims: Sequence[Mapping[str, Any]], signals_by_id: Mapping[str, Mapping[str, Any]]
) -> list[Finding]:
    findings: list[Finding] = []
    for index, claim in enumerate(claims, start=1):
        ids = tuple(str(s) for s in claim.get("signal_ids", []))
        rows = [signals_by_id[i] for i in ids if i in signals_by_id]
        count = independent_source_count(rows)
        findings.append(
            Finding(
                finding_id=f"fin-{index:03d}",
                statement=str(claim.get("statement", "")),
                signal_ids=ids,
                independent_sources=count,
                tier=tier_for_count(count),
            )
        )
    return findings
```

- [ ] **Step 4: Write `vsm/guards/corroboration.py`**

```python
"""G6 — an uncorroborated finding may not reach the report's main body.

``emerging`` findings are publishable in a separately labelled section, because
two independent sources is a real if provisional observation. ``single_source``
never leaves the ledger: one source is an anecdote, and an anecdote printed in a
client report is indistinguishable from a finding.

Enforced here rather than in a prompt, because a rule stated only in a prompt is
an optimisation and never a control.
"""

from __future__ import annotations

from typing import Iterable

from vsm.errors import GuardViolation

__all__ = ["assert_body_is_corroborated", "BODY_TIERS"]

BODY_TIERS = frozenset({"corroborated"})


def assert_body_is_corroborated(findings: Iterable[object]) -> None:
    bad = [f for f in findings if getattr(f, "tier", None) not in BODY_TIERS]
    if bad:
        detail = ", ".join(
            f"{getattr(f, 'finding_id', '?')}={getattr(f, 'tier', '?')}" for f in bad
        )
        raise GuardViolation(
            f"findings below 'corroborated' cannot appear in the report body: {detail}",
            rule="G6",
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_corroborate.py -v`
Expected: 9 passed

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Count independent sources, and make syndication count once"
```

---

## Task 10: Theme clustering

**Files:**
- Create: `vsm/analysis/cluster.py`
- Test: `tests/test_cluster.py`

**Interfaces:**
- Consumes: `vsm.mining.venues.kind_of`, `AnthropicClient`, `THEMES_SCHEMA`, `CLUSTER_SYSTEM`
- Produces: `Theme` (frozen: `theme_id`, `name`, `signal_ids: tuple[str, ...]`, `volume: int`, `venue_mix: dict[str, int]`, `kind_mix: dict[str, int]`); `cluster_themes(signals, *, client=None) -> list[Theme]`; `venue_mix_for(signals) -> dict[str, int]`; `kind_mix_for(signals) -> dict[str, int]`

**Rung 5.** The model proposes groupings and names them; every number attached to a theme — volume, venue mix, kind mix — is counted here, not asked for. Offline, themes fall back to grouping on the `theme` field the miner already derived, which keeps the pass demonstrable with `VSM_MINER=fake`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cluster.py
from vsm.analysis.cluster import cluster_themes, kind_mix_for, venue_mix_for


def sig(sid, venue, theme):
    return {"signal_id": sid, "venue": venue, "theme": theme,
            "url": f"https://{venue}/{sid}", "title": theme}


ROWS = [
    sig("a", "studentdoctor.net", "tolerability"),
    sig("b", "studentdoctor.net", "tolerability"),
    sig("c", "patient.info", "cost"),
]


def test_offline_clustering_groups_on_the_derived_theme():
    themes = cluster_themes(ROWS, client=None)
    assert {t.name for t in themes} == {"tolerability", "cost"}


def test_volume_is_counted_not_asked_for():
    themes = {t.name: t for t in cluster_themes(ROWS, client=None)}
    assert themes["tolerability"].volume == 2
    assert themes["cost"].volume == 1


def test_venue_mix_counts_signals_per_venue():
    assert venue_mix_for(ROWS) == {"studentdoctor.net": 2, "patient.info": 1}


def test_kind_mix_uses_the_registry():
    mix = kind_mix_for(ROWS)
    assert mix.get("hcp_discussion") == 2
    assert mix.get("patient_community") == 1


def test_a_model_supplied_volume_is_ignored():
    """The model names themes. It does not count them: a number a model
    produced is a number nobody can reproduce."""

    class _Client:
        def complete_structured(self, **kw):
            class _Out:
                ok = True
                data = {"themes": [
                    {"theme_id": "th-1", "name": "tolerability",
                     "signal_ids": ["a", "b"], "volume": 9999}
                ]}
                reason = ""
            return _Out()

    themes = cluster_themes(ROWS[:2], client=_Client())
    assert themes[0].volume == 2


def test_an_unknown_signal_id_from_the_model_is_dropped():
    """The model may hallucinate an id. It cannot conjure a signal into the
    ledger by naming one."""

    class _Client:
        def complete_structured(self, **kw):
            class _Out:
                ok = True
                data = {"themes": [
                    {"theme_id": "th-1", "name": "tolerability",
                     "signal_ids": ["a", "does-not-exist"]}
                ]}
                reason = ""
            return _Out()

    themes = cluster_themes(ROWS[:1], client=_Client())
    assert themes[0].signal_ids == ("a",)
    assert themes[0].volume == 1
```

- [ ] **Step 2: Run it, watch it fail**

Run: `pytest tests/test_cluster.py -v`
Expected: FAIL — no module `vsm.analysis.cluster`

- [ ] **Step 3: Write `vsm/analysis/cluster.py`**

```python
"""Rung 5 — what is being discussed, grouped and named.

The model proposes the grouping and writes the names, because that is a reading
task. Every *number* on a theme is counted here from the signal rows: volume,
venue mix, kind mix. A model-supplied count is discarded even when it is right,
because a number nobody can reproduce cannot go in a client report.

Offline the pass groups on the ``theme`` field the miner already derived from
each page title, which keeps it demonstrable under ``VSM_MINER=fake``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from vsm.llm.prompts import CLUSTER_SYSTEM
from vsm.llm.schema import THEMES_SCHEMA
from vsm.mining.venues import kind_of

__all__ = ["Theme", "cluster_themes", "venue_mix_for", "kind_mix_for"]


@dataclass(frozen=True)
class Theme:
    theme_id: str
    name: str
    signal_ids: tuple[str, ...]
    volume: int
    venue_mix: dict[str, int]
    kind_mix: dict[str, int]


def venue_mix_for(signals: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(s.get("venue") or "") for s in signals))


def kind_mix_for(signals: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Venue kinds, straight from the registry. An unregistered venue counts as
    ``unknown`` rather than being assigned a plausible kind."""
    return dict(Counter(kind_of(str(s.get("venue") or "")) or "unknown" for s in signals))


def _theme(theme_id: str, name: str, rows: Sequence[Mapping[str, Any]]) -> Theme:
    return Theme(
        theme_id=theme_id,
        name=name,
        signal_ids=tuple(str(r["signal_id"]) for r in rows),
        volume=len(rows),
        venue_mix=venue_mix_for(rows),
        kind_mix=kind_mix_for(rows),
    )


def _offline(signals: Sequence[Mapping[str, Any]]) -> list[Theme]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for signal in signals:
        grouped.setdefault(str(signal.get("theme") or "unlabelled"), []).append(signal)
    return [
        _theme(f"th-{i:03d}", name, rows)
        for i, (name, rows) in enumerate(sorted(grouped.items()), start=1)
    ]


def cluster_themes(
    signals: Sequence[Mapping[str, Any]], *, client: Any | None = None
) -> list[Theme]:
    if client is None or not signals:
        return _offline(signals)

    by_id = {str(s["signal_id"]): s for s in signals}
    listing = "\n".join(
        f"- {sid}: {str(s.get('theme') or s.get('title') or '')[:160]}"
        for sid, s in by_id.items()
    )
    out = client.complete_structured(
        system=CLUSTER_SYSTEM,
        user=f"Group these signals into themes and name each theme.\n\n{listing}",
        schema=THEMES_SCHEMA,
        max_output_tokens=4096,
    )
    if not out.ok or not out.data:
        return _offline(signals)

    themes: list[Theme] = []
    for index, proposed in enumerate(out.data.get("themes", []), start=1):
        # An id the model invented cannot conjure a signal into the ledger.
        rows = [by_id[sid] for sid in proposed.get("signal_ids", []) if sid in by_id]
        if not rows:
            continue
        themes.append(
            _theme(
                str(proposed.get("theme_id") or f"th-{index:03d}"),
                str(proposed.get("name") or "unnamed"),
                rows,
            )
        )
    return themes or _offline(signals)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cluster.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Cluster signals into themes, and count every number ourselves"
```

---

## Task 11: Stance, split by author class and never blended

**Files:**
- Create: `vsm/analysis/stance.py`
- Test: `tests/test_stance.py`

**Interfaces:**
- Consumes: `AuthorClass`, `Resolver`, `Theme`, `AnthropicClient`, `STANCE_SCHEMA`, `STANCE_SYSTEM`
- Produces: `STANCES = ("positive","negative","mixed","neutral","unclear")`; `ThemeStance` (frozen: `theme_id`, `by_class: dict[str, dict[str, int]]`, `basis: str`); `classify_signals(signals, *, client) -> dict[str, str]`; `stance_for_themes(themes, signals, resolver, *, client=None) -> list[ThemeStance]`

**The rule that shapes the type.** Only 2–5% of disease-area conversation comes from clinicians ([CREATION.co](https://creation.co/knowledge/if-you-already-have-a-healthcare-social-listening-tool-why-implement-another-one/)). A blended sentiment number over an unfiltered disease corpus is therefore a patient number wearing a clinical label. `ThemeStance` has **no field** for a blended figure — not "we choose not to blend", but nowhere to put one.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_stance.py
import dataclasses

from vsm.analysis.authorclass import AuthorClass, VenueResolver
from vsm.analysis.cluster import cluster_themes
from vsm.analysis.stance import STANCES, ThemeStance, stance_for_themes


def sig(sid, venue, theme):
    return {"signal_id": sid, "venue": venue, "theme": theme,
            "excerpt": theme, "title": theme, "url": f"https://{venue}/{sid}"}


ROWS = [
    sig("a", "studentdoctor.net", "tolerability"),
    sig("b", "patient.info", "tolerability"),
]


class _Client:
    def __init__(self, mapping):
        self.mapping = mapping

    def complete_structured(self, **kw):
        class _Out:
            ok = True
            data = {"items": [{"signal_id": k, "stance": v, "rationale": "t"}
                              for k, v in self.mapping.items()]}
            reason = ""
        return _Out()


def test_there_is_no_blended_stance_field():
    """Not a policy — there is nowhere to put one."""
    names = {f.name for f in dataclasses.fields(ThemeStance)}
    assert not {"overall", "blended", "sentiment", "score"} & names


def test_stance_is_reported_per_author_class():
    themes = cluster_themes(ROWS, client=None)
    out = stance_for_themes(themes, ROWS, VenueResolver(),
                            client=_Client({"a": "positive", "b": "negative"}))
    by_class = out[0].by_class
    assert by_class["hcp"]["positive"] == 1
    assert by_class["patient"]["negative"] == 1


def test_the_basis_is_recorded_on_the_result():
    """A report must be able to say whether 'hcp' meant a venue or an NPI."""
    themes = cluster_themes(ROWS, client=None)
    out = stance_for_themes(themes, ROWS, VenueResolver(), client=_Client({"a": "positive"}))
    assert out[0].basis == "venue"


def test_an_identity_resolver_changes_the_basis_and_nothing_else():
    """Spec §3.3 — swapping the resolver must not change the shape."""

    class StubIdentity:
        def resolve(self, signal):
            return AuthorClass("hcp", "identity", 0.97, "NPI matched", npi="1234567890")

    themes = cluster_themes(ROWS, client=None)
    venue = stance_for_themes(themes, ROWS, VenueResolver(), client=_Client({"a": "positive", "b": "positive"}))
    ident = stance_for_themes(themes, ROWS, StubIdentity(), client=_Client({"a": "positive", "b": "positive"}))
    assert set(venue[0].by_class) == {"hcp", "patient"}
    assert set(ident[0].by_class) == {"hcp"}
    assert venue[0].basis == "venue" and ident[0].basis == "identity"
    assert type(venue[0]) is type(ident[0])


def test_an_unrecognised_stance_from_the_model_becomes_unclear():
    themes = cluster_themes(ROWS, client=None)
    out = stance_for_themes(themes, ROWS, VenueResolver(),
                            client=_Client({"a": "ecstatic", "b": "neutral"}))
    assert out[0].by_class["hcp"]["unclear"] == 1


def test_without_a_client_every_signal_is_unclear_not_neutral():
    """No classifier ran. 'neutral' would be a finding; 'unclear' is the truth."""
    themes = cluster_themes(ROWS, client=None)
    out = stance_for_themes(themes, ROWS, VenueResolver(), client=None)
    assert out[0].by_class["hcp"] == {"unclear": 1}


def test_the_five_stances_are_fixed():
    assert STANCES == ("positive", "negative", "mixed", "neutral", "unclear")
```

- [ ] **Step 2: Run it, watch it fail**

Run: `pytest tests/test_stance.py -v`
Expected: FAIL — no module `vsm.analysis.stance`

- [ ] **Step 3: Write `vsm/analysis/stance.py`**

```python
"""How each theme is being talked about — split by who is talking.

Only 2-5% of conversation in a disease area comes from clinicians. A single
sentiment number over an unfiltered disease corpus is therefore a *patient*
sentiment number wearing a clinical label, and it is the most common way a
listening report says something untrue while every individual row is correct.

So :class:`ThemeStance` has no field for a blended figure. Not a policy anyone
has to remember — nowhere to put one.

The stance pass writes its own artifact and **never back-fills** the signal
row's ``sentiment``, which the miner deliberately leaves ``None``. A signal row
says what collection witnessed; a classification is a later opinion about it.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from vsm.analysis.authorclass import Resolver
from vsm.llm.prompts import STANCE_SYSTEM
from vsm.llm.schema import STANCE_SCHEMA

__all__ = ["STANCES", "ThemeStance", "classify_signals", "stance_for_themes"]

STANCES: tuple[str, ...] = ("positive", "negative", "mixed", "neutral", "unclear")


@dataclass(frozen=True)
class ThemeStance:
    theme_id: str
    #: author class → stance → count. Never summed across classes.
    by_class: dict[str, dict[str, int]]
    #: ``venue`` or ``identity`` — which resolver produced the classes above
    basis: str


def classify_signals(
    signals: Sequence[Mapping[str, Any]], *, client: Any | None
) -> dict[str, str]:
    """signal_id → stance. Everything is ``unclear`` when no classifier ran.

    ``unclear`` rather than ``neutral``: neutral is a finding about the text,
    and we did not look at the text.
    """
    if client is None or not signals:
        return {str(s["signal_id"]): "unclear" for s in signals}

    by_id = {str(s["signal_id"]): s for s in signals}
    listing = "\n".join(
        f"- {sid}: {str(s.get('excerpt') or s.get('theme') or '')[:400]}"
        for sid, s in by_id.items()
    )
    out = client.complete_structured(
        system=STANCE_SYSTEM,
        user=f"Classify the stance of each passage.\n\n{listing}",
        schema=STANCE_SCHEMA,
        max_output_tokens=4096,
    )
    result = {sid: "unclear" for sid in by_id}
    if not out.ok or not out.data:
        return result
    for item in out.data.get("items", []):
        sid = str(item.get("signal_id", ""))
        if sid in result:
            stance = str(item.get("stance", "")).strip().lower()
            # An unrecognised label is an abstention, not a new category.
            result[sid] = stance if stance in STANCES else "unclear"
    return result


def stance_for_themes(
    themes: Sequence[Any],
    signals: Sequence[Mapping[str, Any]],
    resolver: Resolver,
    *,
    client: Any | None = None,
) -> list[ThemeStance]:
    by_id = {str(s["signal_id"]): s for s in signals}
    stances = classify_signals(signals, client=client)
    classes = {sid: resolver.resolve(row) for sid, row in by_id.items()}
    basis = next((c.basis for c in classes.values()), "venue")

    results: list[ThemeStance] = []
    for theme in themes:
        buckets: dict[str, Counter] = defaultdict(Counter)
        for sid in theme.signal_ids:
            if sid not in by_id:
                continue
            buckets[classes[sid].value][stances.get(sid, "unclear")] += 1
        results.append(
            ThemeStance(
                theme_id=theme.theme_id,
                by_class={k: dict(v) for k, v in buckets.items()},
                basis=basis,
            )
        )
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_stance.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Split stance by author class, and leave nowhere to blend it"
```

---

## Task 12: The dual-lens gap

**Files:**
- Create: `vsm/analysis/duallens.py`
- Test: `tests/test_duallens.py`

**Interfaces:**
- Consumes: `ThemeStance`, `Theme`
- Produces: `LensGap` (frozen: `theme_id`, `theme_name`, `hcp: dict[str,int]`, `patient: dict[str,int]`, `hcp_net: float | None`, `patient_net: float | None`, `divergence: float | None`, `reason: str`); `net_stance(counts) -> float | None`; `dual_lens(themes, stances) -> list[LensGap]` sorted by divergence descending, `None` divergence last

**Why this is the headline.** [Talking Medicines](https://talkingmedicines.com/use_cases/mastering-hcp-engagement-with-tailored-messaging-through-drug-gpt-intelligence/) sells exactly this — two lenses over one corpus, where the delta is the product. A theme clinicians are neutral about and patients are angry about is a different problem from the reverse, and neither is visible in a blended number. Nobody asks for the gap, which is what makes it the clearest instance of the brief's "something the client did not know they wanted".

- [ ] **Step 1: Write the failing test**

```python
# tests/test_duallens.py
import pytest

from vsm.analysis.cluster import Theme
from vsm.analysis.duallens import dual_lens, net_stance
from vsm.analysis.stance import ThemeStance


def theme(tid, name):
    return Theme(tid, name, ("a",), 1, {}, {})


def test_net_stance_runs_from_minus_one_to_one():
    assert net_stance({"positive": 4}) == pytest.approx(1.0)
    assert net_stance({"negative": 4}) == pytest.approx(-1.0)
    assert net_stance({"positive": 2, "negative": 2}) == pytest.approx(0.0)


def test_unclear_and_mixed_do_not_move_the_net_but_do_dilute_it():
    """An abstention is not agreement. It stays in the denominator so a theme
    the model could not read does not look like a confident zero."""
    assert net_stance({"positive": 1, "unclear": 3}) == pytest.approx(0.25)


def test_a_class_with_no_readable_stance_is_none_not_zero():
    assert net_stance({}) is None
    assert net_stance({"unclear": 5}) == pytest.approx(0.0)


def test_divergence_is_the_gap_between_the_two_lenses():
    stances = [ThemeStance("t1", {"hcp": {"positive": 4}, "patient": {"negative": 4}}, "venue")]
    gap = dual_lens([theme("t1", "tolerability")], stances)[0]
    assert gap.hcp_net == pytest.approx(1.0)
    assert gap.patient_net == pytest.approx(-1.0)
    assert gap.divergence == pytest.approx(2.0)


def test_themes_are_ranked_by_divergence():
    themes = [theme("t1", "small"), theme("t2", "large")]
    stances = [
        ThemeStance("t1", {"hcp": {"positive": 1}, "patient": {"positive": 1}}, "venue"),
        ThemeStance("t2", {"hcp": {"positive": 4}, "patient": {"negative": 4}}, "venue"),
    ]
    assert [g.theme_id for g in dual_lens(themes, stances)] == ["t2", "t1"]


def test_a_one_sided_theme_has_no_divergence_and_says_why():
    """Silence from one side is not agreement, and it is not a gap of zero."""
    stances = [ThemeStance("t1", {"hcp": {"positive": 3}}, "venue")]
    gap = dual_lens([theme("t1", "clinical only")], stances)[0]
    assert gap.divergence is None
    assert "patient" in gap.reason.lower()


def test_unmeasurable_themes_sort_last():
    themes = [theme("t1", "one sided"), theme("t2", "both sides")]
    stances = [
        ThemeStance("t1", {"hcp": {"positive": 3}}, "venue"),
        ThemeStance("t2", {"hcp": {"positive": 1}, "patient": {"negative": 1}}, "venue"),
    ]
    assert [g.theme_id for g in dual_lens(themes, stances)] == ["t2", "t1"]
```

- [ ] **Step 2: Run it, watch it fail**

Run: `pytest tests/test_duallens.py -v`
Expected: FAIL — no module `vsm.analysis.duallens`

- [ ] **Step 3: Write `vsm/analysis/duallens.py`**

```python
"""The gap between what clinicians say and what patients say.

Two lenses over the same corpus; the delta is the output. A theme clinicians are
neutral about and patients are angry about is a different commercial problem
from the reverse, and a blended number shows neither.

``net_stance`` maps a stance histogram onto [-1, 1]. ``mixed`` and ``unclear``
contribute nothing to the numerator but stay in the denominator, so a theme the
classifier could not read comes out *near* zero rather than *at* zero — an
abstention dilutes a signal, it does not balance it.

A theme only one side discussed has ``divergence = None`` and a stated reason.
Silence is not agreement, and it is certainly not a gap of zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

__all__ = ["LensGap", "net_stance", "dual_lens"]

_WEIGHTS = {"positive": 1.0, "negative": -1.0, "mixed": 0.0, "neutral": 0.0, "unclear": 0.0}


@dataclass(frozen=True)
class LensGap:
    theme_id: str
    theme_name: str
    hcp: dict[str, int]
    patient: dict[str, int]
    hcp_net: float | None
    patient_net: float | None
    divergence: float | None
    reason: str = ""


def net_stance(counts: Mapping[str, int]) -> float | None:
    """[-1, 1], or ``None`` when nothing was classified at all."""
    total = sum(counts.values())
    if total == 0:
        return None
    numerator = sum(_WEIGHTS.get(stance, 0.0) * n for stance, n in counts.items())
    return round(numerator / total, 4)


def dual_lens(
    themes: Sequence[Any], stances: Sequence[Any]
) -> list[LensGap]:
    by_theme = {s.theme_id: s for s in stances}
    gaps: list[LensGap] = []
    for theme in themes:
        stance = by_theme.get(theme.theme_id)
        hcp = dict(stance.by_class.get("hcp", {})) if stance else {}
        patient = dict(stance.by_class.get("patient", {})) if stance else {}
        hcp_net, patient_net = net_stance(hcp), net_stance(patient)

        if hcp_net is None or patient_net is None:
            missing = "patient" if patient_net is None else "hcp"
            divergence, reason = None, (
                f"no {missing}-class signal for this theme, so the two lenses "
                "cannot be compared; silence is not agreement"
            )
        else:
            divergence, reason = round(abs(hcp_net - patient_net), 4), ""

        gaps.append(
            LensGap(theme.theme_id, theme.name, hcp, patient, hcp_net, patient_net,
                    divergence, reason)
        )

    # Unmeasurable themes sort last rather than being dropped — a theme only one
    # side discusses is itself worth seeing.
    return sorted(gaps, key=lambda g: (g.divergence is None, -(g.divergence or 0.0)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_duallens.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Add the dual-lens gap, and refuse to score a one-sided theme"
```

---

## Task 13: Momentum — measured, never predicted

**Files:**
- Create: `vsm/analysis/momentum.py`
- Test: `tests/test_momentum.py`

**Interfaces:**
- Consumes: `Theme`
- Produces: `ThemeMomentum` (frozen: `theme_name`, `volume_now: int`, `volume_prior: int | None`, `delta: int | None`, `delta_pct: float | None`, `reason: str`); `momentum(current_themes, prior_snapshots) -> list[ThemeMomentum]` where `prior_snapshots` is a list (oldest first) of `list[Theme]`

**The rule.** This reports the delta between dated snapshots. It carries no forecast and no accuracy figure (spec D13, enforced by G5). Black Swan and Spate publish forecast accuracy because they re-check predictions monthly; until Vi backtests, a prediction here would be a number with nothing behind it.

**On a topic's first snapshot** every field is `None` with `reason="no prior snapshot"`. Nothing fabricates a trend.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_momentum.py
import pytest

from vsm.analysis.cluster import Theme
from vsm.analysis.momentum import momentum


def th(name, volume):
    return Theme(f"th-{name}", name, tuple(f"s{i}" for i in range(volume)), volume, {}, {})


def test_first_snapshot_reports_no_baseline_rather_than_a_trend():
    out = momentum([th("tolerability", 5)], prior_snapshots=[])
    assert out[0].volume_now == 5
    assert out[0].volume_prior is None
    assert out[0].delta is None and out[0].delta_pct is None
    assert out[0].reason == "no prior snapshot"


def test_growth_against_the_immediately_prior_snapshot():
    out = momentum([th("tolerability", 12)], prior_snapshots=[[th("tolerability", 8)]])
    assert out[0].volume_prior == 8
    assert out[0].delta == 4
    assert out[0].delta_pct == pytest.approx(50.0)


def test_decline_is_negative():
    out = momentum([th("cost", 3)], prior_snapshots=[[th("cost", 6)]])
    assert out[0].delta == -3
    assert out[0].delta_pct == pytest.approx(-50.0)


def test_the_comparison_is_against_the_latest_prior_not_the_oldest():
    out = momentum([th("x", 10)], prior_snapshots=[[th("x", 1)], [th("x", 9)]])
    assert out[0].volume_prior == 9


def test_a_theme_absent_from_the_prior_snapshot_is_new_not_infinite_growth():
    out = momentum([th("new thing", 4)], prior_snapshots=[[th("other", 4)]])
    assert out[0].volume_prior == 0
    assert out[0].delta == 4
    assert out[0].delta_pct is None
    assert "not present" in out[0].reason


def test_a_theme_that_vanished_is_reported_at_zero():
    """A theme dropping out is a finding. Omitting it would hide the change."""
    out = momentum([th("still here", 2)], prior_snapshots=[[th("gone", 7), th("still here", 2)]])
    names = {m.theme_name: m for m in out}
    assert names["gone"].volume_now == 0
    assert names["gone"].delta == -7


def test_no_field_named_forecast_exists():
    """D13. We describe measured movement; we do not predict."""
    import dataclasses

    from vsm.analysis.momentum import ThemeMomentum

    names = {f.name for f in dataclasses.fields(ThemeMomentum)}
    assert not {"forecast", "predicted", "projection", "trend_value"} & names
```

- [ ] **Step 2: Run it, watch it fail**

Run: `pytest tests/test_momentum.py -v`
Expected: FAIL — no module `vsm.analysis.momentum`

- [ ] **Step 3: Write `vsm/analysis/momentum.py`**

```python
"""Rung 6 — what is moving, measured against the previous snapshot.

**This is a delta, not a forecast** (spec D13). Competitors publish prediction
accuracy because they re-check their predictions every month against what
actually happened. Until Vi does the same, a projection here would be a number
with nothing behind it, and G5 rejects the language that would express one.

On a topic's first snapshot there is no baseline, and every comparison field is
``None`` with the reason stated. That is the parent engine's rule about never
inventing a number, applied to time.

A theme that appeared and a theme that vanished are both reported. Omitting the
vanished one would hide exactly the change worth seeing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

__all__ = ["ThemeMomentum", "momentum"]

NO_BASELINE = "no prior snapshot"


@dataclass(frozen=True)
class ThemeMomentum:
    theme_name: str
    volume_now: int
    volume_prior: int | None
    delta: int | None
    #: ``None`` when the prior volume was zero — percentage growth from nothing
    #: is not a large number, it is an undefined one.
    delta_pct: float | None
    reason: str = ""


def _volumes(themes: Sequence[Any]) -> dict[str, int]:
    return {t.name: t.volume for t in themes}


def momentum(
    current_themes: Sequence[Any], prior_snapshots: Sequence[Sequence[Any]]
) -> list[ThemeMomentum]:
    now = _volumes(current_themes)

    if not prior_snapshots:
        return [
            ThemeMomentum(name, volume, None, None, None, NO_BASELINE)
            for name, volume in sorted(now.items())
        ]

    prior = _volumes(prior_snapshots[-1])  # oldest first, so the last is the latest
    results: list[ThemeMomentum] = []
    for name in sorted(set(now) | set(prior)):
        volume_now = now.get(name, 0)
        volume_prior = prior.get(name, 0)
        delta = volume_now - volume_prior
        if volume_prior == 0:
            results.append(
                ThemeMomentum(
                    name, volume_now, 0, delta, None,
                    "not present in the prior snapshot, so growth has no base",
                )
            )
            continue
        results.append(
            ThemeMomentum(
                name, volume_now, volume_prior, delta,
                round(100.0 * delta / volume_prior, 2), "",
            )
        )
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_momentum.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Measure momentum between snapshots, and refuse to forecast"
```

---

## Task 14: Anomaly — arithmetic detection, model narration

**Files:**
- Create: `vsm/analysis/anomaly.py`
- Test: `tests/test_anomaly.py`

**Interfaces:**
- Consumes: `Theme`, `AnthropicClient`, `ANOMALY_NARRATION_SCHEMA`, `ANOMALY_NARRATION_SYSTEM`
- Produces: `AnomalyKind = Literal["theme_appeared","theme_vanished","volume_spike","volume_collapse"]`; `Anomaly` (frozen: `anomaly_id`, `kind`, `theme_name`, `observed: int`, `baseline: float | None`, `detail: str`, `note: str = ""`); `median(values) -> float | None`; `baseline_for(theme_name, prior_snapshots) -> float | None`; `detect_anomalies(current_themes, prior_snapshots) -> list[Anomaly]`; `narrate(anomalies, *, client=None) -> list[Anomaly]`

**Baseline definition (spec §4.2):** the **median** of the theme's volume across the previous **three** snapshots, or all of them when fewer than three exist. Median rather than mean, so one unusual week does not redefine normal.

**Thresholds:** a `volume_spike` needs `observed > 2 × baseline` **and** `observed >= MIN_VOLUME` (5). The floor exists because doubling from 1 to 2 is noise, and a report full of noise trains its reader to ignore it.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_anomaly.py
import pytest

from vsm.analysis.anomaly import (
    MIN_VOLUME, Anomaly, baseline_for, detect_anomalies, median, narrate,
)
from vsm.analysis.cluster import Theme


def th(name, volume):
    return Theme(f"th-{name}", name, tuple(f"s{i}" for i in range(volume)), volume, {}, {})


def test_median_of_nothing_is_none():
    assert median([]) is None


def test_median_ignores_one_freak_week():
    """Mean would let a single spike redefine normal and then hide the next one."""
    assert median([4, 5, 400]) == 5
    assert median([4, 6]) == 5


def test_baseline_uses_at_most_the_previous_three_snapshots():
    priors = [[th("x", 100)], [th("x", 4)], [th("x", 5)], [th("x", 6)]]
    assert baseline_for("x", priors) == 5


def test_a_theme_appearing_is_an_anomaly():
    out = detect_anomalies([th("new", 6)], [[th("old", 6)]])
    kinds = {(a.kind, a.theme_name) for a in out}
    assert ("theme_appeared", "new") in kinds


def test_a_theme_vanishing_is_an_anomaly():
    out = detect_anomalies([th("kept", 5)], [[th("gone", 8), th("kept", 5)]])
    assert ("theme_vanished", "gone") in {(a.kind, a.theme_name) for a in out}


def test_a_spike_needs_both_a_multiple_and_a_floor():
    """Doubling from 1 to 2 is noise, and a report full of noise teaches its
    reader to skip the section."""
    noise = detect_anomalies([th("x", 2)], [[th("x", 1)], [th("x", 1)]])
    assert not [a for a in noise if a.kind == "volume_spike"]

    real = detect_anomalies([th("x", 20)], [[th("x", 5)], [th("x", 5)]])
    spike = [a for a in real if a.kind == "volume_spike"]
    assert spike and spike[0].observed == 20 and spike[0].baseline == 5


def test_no_baseline_means_no_anomalies_at_all():
    """On a first snapshot everything looks new. Reporting that would be noise
    dressed as insight."""
    assert detect_anomalies([th("x", 50)], []) == []


def test_narration_attaches_notes_without_touching_the_numbers():
    """Detection is reproducible arithmetic; only the prose is model-written."""
    detected = detect_anomalies([th("x", 20)], [[th("x", 5)], [th("x", 5)]])

    class _Client:
        def complete_structured(self, **kw):
            class _Out:
                ok = True
                data = {"notes": [{"anomaly_id": a.anomaly_id, "note": "discussion widened"}
                                  for a in detected]}
                reason = ""
            return _Out()

    narrated = narrate(detected, client=_Client())
    assert narrated[0].note == "discussion widened"
    assert narrated[0].observed == detected[0].observed
    assert narrated[0].baseline == detected[0].baseline


def test_narration_without_a_client_leaves_notes_empty():
    detected = detect_anomalies([th("x", 20)], [[th("x", 5)], [th("x", 5)]])
    assert all(a.note == "" for a in narrate(detected, client=None))
```

- [ ] **Step 2: Run it, watch it fail**

Run: `pytest tests/test_anomaly.py -v`
Expected: FAIL — no module `vsm.analysis.anomaly`

- [ ] **Step 3: Write `vsm/analysis/anomaly.py`**

```python
"""Rung 7 — what changed that nobody asked about.

**Detection is arithmetic. Only the narration is model-written.** A threshold
crossing can be recomputed by anyone with the artifacts; a model's opinion that
something looks unusual cannot. Keeping the two apart is what lets the report
say "this doubled" and mean it.

The baseline is the **median** of a theme's volume across the previous three
snapshots. Median rather than mean because one freak week should not redefine
normal — and if it did, it would also mask the next real spike.

A spike must clear both a multiple and a floor. Doubling from one mention to two
is arithmetically a spike and substantively nothing, and a section full of
those teaches its reader to skip the section.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, replace
from typing import Any, Literal, Sequence

from vsm.llm.prompts import ANOMALY_NARRATION_SYSTEM
from vsm.llm.schema import ANOMALY_NARRATION_SCHEMA

__all__ = [
    "Anomaly", "AnomalyKind", "MIN_VOLUME", "SPIKE_MULTIPLE", "BASELINE_WINDOW",
    "median", "baseline_for", "detect_anomalies", "narrate",
]

AnomalyKind = Literal["theme_appeared", "theme_vanished", "volume_spike", "volume_collapse"]

#: How many prior snapshots define "normal".
BASELINE_WINDOW = 3
#: A spike is more than this multiple of the baseline...
SPIKE_MULTIPLE = 2.0
#: ...and at least this many signals. Below it, a multiple is noise.
MIN_VOLUME = 5


@dataclass(frozen=True)
class Anomaly:
    anomaly_id: str
    kind: AnomalyKind
    theme_name: str
    observed: int
    baseline: float | None
    detail: str
    #: model-written; empty until :func:`narrate` runs
    note: str = ""


def median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def baseline_for(theme_name: str, prior_snapshots: Sequence[Sequence[Any]]) -> float | None:
    window = list(prior_snapshots)[-BASELINE_WINDOW:]
    volumes = [
        next((t.volume for t in snapshot if t.name == theme_name), 0)
        for snapshot in window
    ]
    return median(volumes)


def detect_anomalies(
    current_themes: Sequence[Any], prior_snapshots: Sequence[Sequence[Any]]
) -> list[Anomaly]:
    if not prior_snapshots:
        # On a first snapshot everything is new. Saying so would be noise
        # dressed as insight.
        return []

    now = {t.name: t.volume for t in current_themes}
    seen_before = {t.name for snapshot in prior_snapshots for t in snapshot}
    found: list[Anomaly] = []
    counter = 0

    def _add(kind: AnomalyKind, name: str, observed: int, baseline: float | None, detail: str) -> None:
        nonlocal counter
        counter += 1
        found.append(Anomaly(f"anom-{counter:03d}", kind, name, observed, baseline, detail))

    for name in sorted(set(now) | seen_before):
        observed = now.get(name, 0)
        baseline = baseline_for(name, prior_snapshots)

        if name not in seen_before and observed >= MIN_VOLUME:
            _add("theme_appeared", name, observed, baseline,
                 f"{observed} signals, and the theme is absent from every prior snapshot")
            continue
        if name not in now and baseline and baseline >= MIN_VOLUME:
            _add("theme_vanished", name, 0, baseline,
                 f"baseline was {baseline:g}; this snapshot has none")
            continue
        if baseline and observed > baseline * SPIKE_MULTIPLE and observed >= MIN_VOLUME:
            _add("volume_spike", name, observed, baseline,
                 f"{observed} against a baseline of {baseline:g}")
        elif baseline and baseline >= MIN_VOLUME and observed * SPIKE_MULTIPLE < baseline:
            _add("volume_collapse", name, observed, baseline,
                 f"{observed} against a baseline of {baseline:g}")
    return found


def narrate(anomalies: Sequence[Anomaly], *, client: Any | None = None) -> list[Anomaly]:
    """Attach one sentence of explanation. Numbers are never re-derived here."""
    anomalies = list(anomalies)
    if client is None or not anomalies:
        return anomalies
    listing = "\n".join(
        f"- {a.anomaly_id} [{a.kind}] {a.theme_name}: {a.detail}" for a in anomalies
    )
    out = client.complete_structured(
        system=ANOMALY_NARRATION_SYSTEM,
        user=f"Explain what each detected change appears to mean.\n\n{listing}",
        schema=ANOMALY_NARRATION_SCHEMA,
        max_output_tokens=2048,
    )
    if not out.ok or not out.data:
        return anomalies
    notes = {str(n.get("anomaly_id")): str(n.get("note", "")) for n in out.data.get("notes", [])}
    return [replace(a, note=notes.get(a.anomaly_id, "")) for a in anomalies]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_anomaly.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Detect anomalies arithmetically, and let the model only describe them"
```

---

## Task 15: INSIGHT — order the seven passes

**Files:**
- Create: `vsm/modes/insight.py`
- Test: `tests/test_insight.py`

**Interfaces:**
- Consumes: every `vsm.analysis` module, `RunStore`, `Topic`, `VenueResolver`
- Produces: `run_insight(topic, snapshot_run_id, store, *, client=None, resolver=None) -> Run`
- INSIGHT writes exactly these artifacts: `entities.json`, `findings.json`, `themes.json`, `stance.json`, `duallens.json`, `momentum.json`, `anomaly.json`

**Ordering:** resolve → cluster → stance → dual-lens → momentum → anomaly, with corroborate run over the claims the report will later make. Each artifact is written as soon as its pass completes, so a failure late in the chain still leaves the earlier work on disk.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_insight.py
import pytest

from vsm.modes.insight import run_insight
from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore

ARTIFACTS = ("entities.json", "findings.json", "themes.json", "stance.json",
             "duallens.json", "momentum.json", "anomaly.json")


@pytest.fixture
def env(tmp_path):
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    topic = ts.create(name="OIC", therapeutic_area="gastroenterology",
                      spend_band="standard", brand="Symproic", molecule="naldemedine")
    return ts, rs, topic


def _snapshot(rs, topic, rows):
    run = rs.start(topic.topic_id, "mine")
    rs.write_artifact(run.run_id, "signals.json", rows)
    rs.finish(run.run_id, "complete", cost_usd=0.01)
    return run


def _rows(n_hcp, n_patient, theme="tolerability"):
    rows = [{"signal_id": f"h{i}", "venue": "studentdoctor.net", "theme": theme,
             "title": f"{theme} {i}", "excerpt": theme,
             "url": f"https://studentdoctor.net/{i}"} for i in range(n_hcp)]
    rows += [{"signal_id": f"p{i}", "venue": "patient.info", "theme": theme,
              "title": f"{theme} p{i}", "excerpt": theme,
              "url": f"https://patient.info/{i}"} for i in range(n_patient)]
    return rows


def test_insight_writes_all_seven_artifacts(env):
    ts, rs, topic = env
    snap = _snapshot(rs, topic, _rows(2, 2))
    run = run_insight(topic, snap.run_id, rs)
    for name in ARTIFACTS:
        assert (rs.artifacts_dir(run.run_id) / name).exists(), name


def test_the_insight_run_records_its_snapshot_as_parent(env):
    ts, rs, topic = env
    snap = _snapshot(rs, topic, _rows(1, 1))
    run = run_insight(topic, snap.run_id, rs)
    assert run.parent_run_id == snap.run_id


def test_first_snapshot_momentum_says_no_baseline(env):
    ts, rs, topic = env
    snap = _snapshot(rs, topic, _rows(2, 1))
    run = run_insight(topic, snap.run_id, rs)
    momentum = rs.read_artifact(run.run_id, "momentum.json")
    assert momentum and all(m["reason"] == "no prior snapshot" for m in momentum)
    assert rs.read_artifact(run.run_id, "anomaly.json") == []


def test_second_snapshot_compares_against_the_first(env):
    ts, rs, topic = env
    _snapshot(rs, topic, _rows(2, 0))
    second = _snapshot(rs, topic, _rows(6, 0))
    run = run_insight(topic, second.run_id, rs)
    momentum = {m["theme_name"]: m for m in rs.read_artifact(run.run_id, "momentum.json")}
    assert momentum["tolerability"]["volume_prior"] == 2
    assert momentum["tolerability"]["delta"] == 4


def test_a_prior_snapshot_after_this_one_is_not_used_as_a_baseline(env):
    """History is what came before. Comparing against a later snapshot would
    make the delta depend on when the insight run happened."""
    ts, rs, topic = env
    first = _snapshot(rs, topic, _rows(2, 0))
    _snapshot(rs, topic, _rows(50, 0))
    run = run_insight(topic, first.run_id, rs)
    momentum = rs.read_artifact(run.run_id, "momentum.json")
    assert all(m["reason"] == "no prior snapshot" for m in momentum)


def test_stance_artifact_records_its_basis(env):
    ts, rs, topic = env
    snap = _snapshot(rs, topic, _rows(1, 1))
    run = run_insight(topic, snap.run_id, rs)
    stance = rs.read_artifact(run.run_id, "stance.json")
    assert stance and all(s["basis"] == "venue" for s in stance)
```

- [ ] **Step 2: Run it, watch it fail**

Run: `pytest tests/test_insight.py -v`
Expected: FAIL — no module `vsm.modes.insight`

- [ ] **Step 3: Write `vsm/modes/insight.py`**

```python
"""INSIGHT — one snapshot in, seven artifacts out.

Each pass writes as soon as it finishes, so a failure late in the chain still
leaves the earlier work on disk and re-running is cheap.

**History means what came before.** The baseline is built only from snapshots
earlier in the series than this one; if it included later ones, the same
snapshot would produce different deltas depending on when the insight run
happened, which would make every number in the report a function of the
operator's schedule.

"Earlier" is decided by the store's monotonic sequence, not by comparing
``started_at``. Two snapshots created in the same microsecond compare equal on
a timestamp, and the baseline would silently lose one.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from vsm.analysis.anomaly import detect_anomalies, narrate
from vsm.analysis.authorclass import VenueResolver
from vsm.analysis.cluster import cluster_themes
from vsm.analysis.corroborate import corroborate
from vsm.analysis.duallens import dual_lens
from vsm.analysis.momentum import momentum
from vsm.analysis.resolve import build_lexicon, resolve_signals
from vsm.analysis.stance import stance_for_themes
from vsm.runs.model import Run
from vsm.runs.store import RunStore
from vsm.topics.model import Topic

__all__ = ["run_insight"]


def _prior_snapshot_themes(
    topic: Topic, store: RunStore, snapshot_run_id: str, client: Any | None
) -> list[list[Any]]:
    """Themes from every completed MINE run that started before this one."""
    # Ordered by the store's monotonic sequence, never by wall-clock time:
    # two snapshots created in the same microsecond would otherwise compare
    # equal and silently drop a baseline.
    series = store.snapshots(topic.topic_id)
    try:
        position = [r.run_id for r in series].index(snapshot_run_id)
    except ValueError:
        # This snapshot is not a completed MINE run of this topic, so it has
        # no place in the series and therefore no history.
        return []
    earlier = series[:position]
    out: list[list[Any]] = []
    for run in earlier:
        try:
            rows = store.read_artifact(run.run_id, "signals.json")
        except FileNotFoundError:
            continue
        out.append(cluster_themes(rows, client=client))
    return out


def run_insight(
    topic: Topic,
    snapshot_run_id: str,
    store: RunStore,
    *,
    client: Any | None = None,
    resolver: Any | None = None,
) -> Run:
    resolver = resolver or VenueResolver()
    run = store.start(topic.topic_id, "insight", parent_run_id=snapshot_run_id)
    signals = store.read_artifact(snapshot_run_id, "signals.json")

    entities = build_lexicon(topic)
    store.write_artifact(run.run_id, "entities.json", resolve_signals(signals, entities))

    themes = cluster_themes(signals, client=client)
    store.write_artifact(run.run_id, "themes.json", [asdict(t) for t in themes])

    stances = stance_for_themes(themes, signals, resolver, client=client)
    store.write_artifact(run.run_id, "stance.json", [asdict(s) for s in stances])

    store.write_artifact(
        run.run_id, "duallens.json", [asdict(g) for g in dual_lens(themes, stances)]
    )

    priors = _prior_snapshot_themes(topic, store, snapshot_run_id, client)
    store.write_artifact(
        run.run_id, "momentum.json", [asdict(m) for m in momentum(themes, priors)]
    )

    anomalies = narrate(detect_anomalies(themes, priors), client=client)
    store.write_artifact(run.run_id, "anomaly.json", [asdict(a) for a in anomalies])

    # One claim per theme, for the report to draw on. Corroboration decides
    # which of them is allowed into the body — this pass only counts.
    by_id = {str(s["signal_id"]): s for s in signals}
    findings = corroborate(
        [{"statement": t.name, "signal_ids": list(t.signal_ids)} for t in themes], by_id
    )
    store.write_artifact(run.run_id, "findings.json", [asdict(f) for f in findings])

    spend = getattr(getattr(client, "_spend", None), "usd", lambda: 0.0)()
    return store.finish(run.run_id, "complete", cost_usd=spend)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_insight.py -v`
Expected: 6 passed

- [ ] **Step 5: Run the whole suite**

Run: `pytest -q`
Expected: all pass (one xfail from Task 5)

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Wire INSIGHT, and build the baseline only from what came before"
```

---

## Task 16: The text guards — G2 advisory, G4 never-say, G5 no unmeasured claims

**Files:**
- Create: `vsm/guards/advisory.py`, `vsm/guards/terms.py`, `vsm/guards/claims.py`
- Modify: `tests/test_llm.py` — remove the `xfail` marker added in Task 5
- Test: `tests/test_text_guards.py`

**Interfaces:**
- Consumes: `vsm.errors.GuardViolation`
- Produces: `advisory.BANNED_DIRECTIVES: tuple[str, ...]`, `advisory.assert_advisory(text, *, where="") -> None`; `terms.assert_no_banned_terms(text, terms, *, where="") -> None`; `claims.FORECAST_PATTERNS: tuple[str, ...]`, `claims.assert_no_unmeasured_claims(text, *, where="") -> None`

All three raise `GuardViolation` and none of them are catchable-and-softened anywhere. A guard that a caller can shrug off is documentation.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_text_guards.py
import pytest

from vsm.errors import GuardViolation
from vsm.guards.advisory import assert_advisory
from vsm.guards.claims import assert_no_unmeasured_claims
from vsm.guards.terms import assert_no_banned_terms


# ---------------------------------------------------------------- G2 advisory
@pytest.mark.parametrize("text", [
    "You should increase spend on the guideline venues.",
    "You must respond to the tolerability thread.",
    "We recommend that you brief the field team.",
    "The right move is to publish a correction.",
])
def test_g2_rejects_directives(text):
    with pytest.raises(GuardViolation, match="G2"):
        assert_advisory(text)


@pytest.mark.parametrize("text", [
    "Increasing spend on the guideline venues is worth considering.",
    "One option is to brief the field team.",
    "Teams in this position often respond in the thread; the trade-off is visibility.",
])
def test_g2_accepts_suggestions(text):
    assert assert_advisory(text) is None


def test_g2_is_case_insensitive():
    with pytest.raises(GuardViolation):
        assert_advisory("YOU MUST act on this.")


def test_g2_names_where_it_fired():
    with pytest.raises(GuardViolation, match="worth_considering.md"):
        assert_advisory("You should act.", where="worth_considering.md")


# ------------------------------------------------------------------- G4 terms
def test_g4_is_a_noop_with_no_terms():
    assert assert_no_banned_terms("Symproic is discussed widely", ()) is None


def test_g4_rejects_a_listed_term():
    with pytest.raises(GuardViolation, match="G4"):
        assert_no_banned_terms("Symproic is discussed widely", ("Symproic",))


def test_g4_matches_whole_words_only():
    """A never-say list that fires on substrings makes ordinary prose
    unwritable and gets switched off, which is worse than not having one."""
    assert assert_no_banned_terms("the Symproical approach", ("Symproic",)) is None


def test_g4_is_case_insensitive():
    with pytest.raises(GuardViolation):
        assert_no_banned_terms("SYMPROIC appears here", ("Symproic",))


# ------------------------------------------------------------------ G5 claims
@pytest.mark.parametrize("text", [
    "Discussion will grow through Q4.",
    "Volume is expected to reach 400 mentions.",
    "Projected uptake is 12%.",
    "Our model is 89% accurate.",
    "This predicts a rise in clinician interest.",
    "Mentions are forecast to double.",
])
def test_g5_rejects_forecasts_and_accuracy_claims(text):
    with pytest.raises(GuardViolation, match="G5"):
        assert_no_unmeasured_claims(text)


@pytest.mark.parametrize("text", [
    "Discussion grew 50% between the two snapshots.",
    "Volume reached 400 mentions in this snapshot.",
    "Tolerability was the most-discussed theme, on 3 independent sources.",
])
def test_g5_accepts_measured_statements(text):
    assert assert_no_unmeasured_claims(text) is None


def test_g5_does_not_fire_on_the_word_will_in_a_name():
    """A guard with false positives gets disabled. 'Willis' is not a forecast."""
    assert assert_no_unmeasured_claims("Dr Willis raised the dosing question.") is None
```

- [ ] **Step 2: Run it, watch it fail**

Run: `pytest tests/test_text_guards.py -v`
Expected: FAIL — no module `vsm.guards.advisory`

- [ ] **Step 3: Write `vsm/guards/advisory.py`**

```python
"""G2 — the report suggests. It does not decide.

The reader is a professional making a commercial judgement with context we do
not have. Telling them what to do is both presumptuous and, in a regulated
setting, a claim we are not positioned to make.

``BANNED_DIRECTIVES`` must equal ``vsm.llm.prompts.BANNED_DIRECTIVES``. A test
pins the equality, because a drifted pair means the model is being told a
different rule than the one that rejects its output — and then the rejection
looks like a bug rather than a boundary.
"""

from __future__ import annotations

import re

from vsm.errors import GuardViolation

__all__ = ["BANNED_DIRECTIVES", "assert_advisory"]

BANNED_DIRECTIVES: tuple[str, ...] = (
    "you should",
    "you must",
    "we recommend that you",
    "the right move is",
    "you need to",
    "the best option is",
)

_PATTERN = re.compile(
    "|".join(rf"(?<!\w){re.escape(p)}(?!\w)" for p in BANNED_DIRECTIVES),
    re.IGNORECASE,
)


def assert_advisory(text: str, *, where: str = "") -> None:
    found = sorted({m.group(0).lower() for m in _PATTERN.finditer(text or "")})
    if found:
        place = f" in {where}" if where else ""
        raise GuardViolation(
            f"directive language{place}: {', '.join(found)}. "
            "This report suggests; it does not decide.",
            rule="G2",
        )
```

- [ ] **Step 4: Write `vsm/guards/terms.py`**

```python
"""G4 — an optional per-run list of terms the output may never contain.

Empty by default and a no-op when empty: this is not a required guardrail, it
is a convenience for an operator who has a reason to keep a name out of a
document.

Whole-word matching only. A never-say list that fires on substrings makes
ordinary prose unwritable, and a guard people switch off protects nothing.
"""

from __future__ import annotations

import re
from typing import Sequence

from vsm.errors import GuardViolation

__all__ = ["assert_no_banned_terms"]


def assert_no_banned_terms(
    text: str, terms: Sequence[str], *, where: str = ""
) -> None:
    terms = [t for t in terms if t]
    if not terms:
        return
    pattern = re.compile(
        "|".join(rf"(?<!\w){re.escape(t)}(?!\w)" for t in terms), re.IGNORECASE
    )
    found = sorted({m.group(0) for m in pattern.finditer(text or "")})
    if found:
        place = f" in {where}" if where else ""
        raise GuardViolation(
            f"never-say terms present{place}: {', '.join(found)}", rule="G4"
        )
```

- [ ] **Step 5: Write `vsm/guards/claims.py`**

```python
"""G5 — no forecast, and no accuracy figure.

Spec D13. Competitors publish prediction accuracy because they re-check their
predictions monthly against what actually happened; that is what earns the
number. This tool measures the delta between two dated snapshots and stops
there, and this guard is what stops the prose quietly upgrading a measurement
into a projection.

Patterns are anchored to word boundaries. A guard that fires on "Willis"
because it contains "will" gets switched off within a week, and then it guards
nothing.
"""

from __future__ import annotations

import re

from vsm.errors import GuardViolation

__all__ = ["FORECAST_PATTERNS", "assert_no_unmeasured_claims"]

FORECAST_PATTERNS: tuple[str, ...] = (
    r"will\s+(?:grow|rise|increase|decline|fall|double|halve|continue|reach|become)",
    r"expected\s+to",
    r"projected",
    r"projection",
    r"forecast(?:ed|s)?\s+to",
    r"we\s+forecast",
    r"predicts?\b",
    r"prediction",
    r"\d+(?:\.\d+)?\s*%\s*accur",
    r"accuracy\s+of\s+\d+",
    r"likely\s+to\s+(?:grow|rise|increase|decline|fall|double)",
    r"over\s+the\s+(?:next|coming)\s+\w+\s+(?:months?|weeks?|quarters?)",
)

_PATTERN = re.compile("|".join(f"(?:{p})" for p in FORECAST_PATTERNS), re.IGNORECASE)


def assert_no_unmeasured_claims(text: str, *, where: str = "") -> None:
    found = sorted({m.group(0).lower() for m in _PATTERN.finditer(text or "")})
    if found:
        place = f" in {where}" if where else ""
        raise GuardViolation(
            f"forecast or accuracy language{place}: {', '.join(found)}. "
            "This report describes measured movement between dated snapshots; "
            "it does not predict, and it quotes no accuracy figure it has not "
            "backtested.",
            rule="G5",
        )
```

- [ ] **Step 6: Remove the xfail marker from Task 5's test**

In `tests/test_llm.py`, delete the `@pytest.mark.xfail(...)` decorator on `test_the_two_banned_lists_are_equal`. It should now pass on its own.

- [ ] **Step 7: Run the suite**

Run: `pytest -q`
Expected: all pass, **no xfail remaining**

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Add the three text guards, and pin the banned list to its prompt"
```

---

## Task 17: G1 citations and the REPORT mode

**Files:**
- Create: `vsm/guards/citations.py`, `vsm/modes/report.py`
- Test: `tests/test_citations.py`, `tests/test_report.py`

**Interfaces:**
- Consumes: every guard, `Finding`, `LensGap`, `ThemeMomentum`, `Anomaly`, `RunStore`, `Topic`
- Produces: `Citation` (frozen: `signal_id`, `url`, `venue`, `venue_kind`, `captured_at`, `collection_method`); `bind_citations(signal_ids, ledger) -> list[Citation]` raising `GuardViolation` on any unbindable id; `run_report(topic, insight_run_id, store, *, client=None) -> Run`
- REPORT writes exactly: `pulse_report.md`, `provenance_appendix.md`, `methodology.md`, `worth_considering.md`

**G1, and why it is not negotiable.** The model may not author trust state. Every citation is rebuilt from the ledger by `signal_id`; a citation the model emitted is discarded even when it is correct. The parent engine's scaffolding path once minted PMIDs as `30000000 + (seed % 9999999)` with a matching PubMed URL — plausible enough to survive review, which is precisely what made it the most dangerous thing in that pipeline. A claim whose ids do not resolve blocks the report.

- [ ] **Step 1: Write the citations test**

```python
# tests/test_citations.py
import pytest

from vsm.errors import GuardViolation
from vsm.guards.citations import bind_citations

LEDGER = {
    "sig-a": {"signal_id": "sig-a", "url": "https://gastro.org/x", "venue": "gastro.org",
              "captured_at": "2026-08-25T00:00:00+00:00", "collection_method": "serp_result"},
}


def test_a_bound_citation_comes_from_the_ledger_not_the_caller():
    got = bind_citations(["sig-a"], LEDGER)
    assert got[0].url == "https://gastro.org/x"
    assert got[0].venue_kind  # resolved from the registry, not passed in


def test_an_unknown_id_blocks_rather_than_being_dropped():
    """Dropping it would turn a fabricated citation into a silently
    uncited claim, which is the same lie with fewer symptoms."""
    with pytest.raises(GuardViolation, match="G1"):
        bind_citations(["sig-a", "sig-invented"], LEDGER)


def test_an_empty_citation_list_blocks():
    with pytest.raises(GuardViolation, match="no signal ids"):
        bind_citations([], LEDGER)


def test_the_error_names_the_offending_ids():
    with pytest.raises(GuardViolation, match="sig-invented"):
        bind_citations(["sig-invented"], LEDGER)
```

- [ ] **Step 2: Write `vsm/guards/citations.py`**

```python
"""G1 — a claim binds to ledger rows, or it does not get written.

Every field of a citation is rebuilt here from the signal row. A citation the
model produced is discarded even when it happens to be right, because the point
is not this citation's correctness — it is that no citation in the document
depends on the model having been honest.

The parent engine earned this rule the hard way: its scaffolding path once
minted PMIDs as ``30000000 + (seed % 9999999)`` with a matching PubMed URL,
plausible enough to survive review.

An unbindable id **blocks**. Dropping it instead would convert a fabricated
citation into a silently uncited claim — the same lie with fewer symptoms.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from vsm.errors import GuardViolation
from vsm.mining.venues import kind_of

__all__ = ["Citation", "bind_citations"]


@dataclass(frozen=True)
class Citation:
    signal_id: str
    url: str
    venue: str
    venue_kind: str
    captured_at: str
    collection_method: str


def bind_citations(
    signal_ids: Sequence[str], ledger: Mapping[str, Mapping[str, Any]]
) -> list[Citation]:
    if not signal_ids:
        raise GuardViolation(
            "a claim was written with no signal ids to bind to", rule="G1"
        )
    missing = [sid for sid in signal_ids if sid not in ledger]
    if missing:
        raise GuardViolation(
            f"claim cites signal ids that are not in the ledger: {', '.join(missing)}",
            rule="G1",
        )
    out: list[Citation] = []
    for sid in signal_ids:
        row = ledger[sid]
        venue = str(row.get("venue") or "")
        out.append(
            Citation(
                signal_id=sid,
                url=str(row.get("url") or ""),
                venue=venue,
                venue_kind=kind_of(venue) or "unknown",
                captured_at=str(row.get("captured_at") or ""),
                collection_method=str(row.get("collection_method") or ""),
            )
        )
    return out
```

- [ ] **Step 3: Run the citations test**

Run: `pytest tests/test_citations.py -v`
Expected: 4 passed

- [ ] **Step 4: Write the report test**

```python
# tests/test_report.py
import pytest

from vsm.errors import GuardViolation
from vsm.modes.insight import run_insight
from vsm.modes.report import run_report
from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore

ARTIFACTS = ("pulse_report.md", "provenance_appendix.md", "methodology.md",
             "worth_considering.md")


@pytest.fixture
def env(tmp_path):
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    topic = ts.create(name="OIC", therapeutic_area="gastroenterology",
                      spend_band="standard", brand="Symproic", molecule="naldemedine")
    return ts, rs, topic


def _rows(n, venue="studentdoctor.net", theme="tolerability"):
    return [{"signal_id": f"s{i}", "venue": f"v{i}.example.org", "theme": theme,
             "title": f"{theme} {i}", "excerpt": theme,
             "captured_at": "2026-08-25T00:00:00+00:00",
             "collection_method": "serp_result",
             "url": f"https://v{i}.example.org/{i}"} for i in range(n)]


def _pipeline(rs, topic, rows):
    mine = rs.start(topic.topic_id, "mine")
    rs.write_artifact(mine.run_id, "signals.json", rows)
    rs.finish(mine.run_id, "complete", cost_usd=0.01)
    return run_insight(topic, mine.run_id, rs)


def test_report_writes_its_four_artifacts(env):
    ts, rs, topic = env
    insight = _pipeline(rs, topic, _rows(4))
    run = run_report(topic, insight.run_id, rs)
    for name in ARTIFACTS:
        assert (rs.artifacts_dir(run.run_id) / name).exists(), name


def test_the_methodology_states_the_author_basis(env):
    ts, rs, topic = env
    insight = _pipeline(rs, topic, _rows(4))
    run = run_report(topic, insight.run_id, rs)
    text = rs.read_artifact(run.run_id, "methodology.md")
    assert "venue" in text.lower()


def test_the_methodology_states_the_ae_scope_limit_exactly_once(env):
    """Spec D10 + the no-over-disclosure rule: say it once, in the appendix
    where scope statements belong, and nowhere else."""
    ts, rs, topic = env
    insight = _pipeline(rs, topic, _rows(4))
    run = run_report(topic, insight.run_id, rs)
    method = rs.read_artifact(run.run_id, "methodology.md").lower()
    pulse = rs.read_artifact(run.run_id, "pulse_report.md").lower()
    assert method.count("adverse event") == 1
    assert "adverse event" not in pulse


def test_the_provenance_appendix_lists_every_cited_signal(env):
    ts, rs, topic = env
    rows = _rows(4)
    insight = _pipeline(rs, topic, rows)
    run = run_report(topic, insight.run_id, rs)
    appendix = rs.read_artifact(run.run_id, "provenance_appendix.md")
    for row in rows:
        assert row["signal_id"] in appendix
        assert row["url"] in appendix


def test_an_uncorroborated_finding_cannot_reach_the_body(env):
    """G6, end to end. One signal is an anecdote."""
    ts, rs, topic = env
    insight = _pipeline(rs, topic, _rows(1))
    run = run_report(topic, insight.run_id, rs)
    body = rs.read_artifact(run.run_id, "pulse_report.md")
    assert "single source" in body.lower() or "not corroborated" in body.lower()


def test_forecast_language_from_the_model_blocks_the_report(env):
    """G5 fires on model output exactly as on our own prose."""
    ts, rs, topic = env
    insight = _pipeline(rs, topic, _rows(4))

    class _Client:
        def complete_structured(self, **kw):
            class _Out:
                ok = True
                data = {"sections": [{"heading": "Outlook",
                                      "body": "Discussion will grow through Q4.",
                                      "signal_ids": ["s0", "s1", "s2"]}],
                        "considerations": []}
                reason = ""
            return _Out()

    with pytest.raises(GuardViolation, match="G5"):
        run_report(topic, insight.run_id, rs, client=_Client())


def test_a_fabricated_signal_id_blocks_the_report(env):
    """G1 end to end."""
    ts, rs, topic = env
    insight = _pipeline(rs, topic, _rows(4))

    class _Client:
        def complete_structured(self, **kw):
            class _Out:
                ok = True
                data = {"sections": [{"heading": "Themes", "body": "Tolerability dominates.",
                                      "signal_ids": ["s0", "sig-invented"]}],
                        "considerations": []}
                reason = ""
            return _Out()

    with pytest.raises(GuardViolation, match="G1"):
        run_report(topic, insight.run_id, rs, client=_Client())


def test_a_never_say_term_blocks_the_report(env):
    """G4 end to end."""
    ts, rs, topic = env
    topic = ts.update(topic.topic_id, never_say=("Symproic",))
    insight = _pipeline(rs, topic, _rows(4))

    class _Client:
        def complete_structured(self, **kw):
            class _Out:
                ok = True
                data = {"sections": [{"heading": "Themes",
                                      "body": "Symproic dominates the discussion.",
                                      "signal_ids": ["s0", "s1", "s2"]}],
                        "considerations": []}
                reason = ""
            return _Out()

    with pytest.raises(GuardViolation, match="G4"):
        run_report(topic, insight.run_id, rs, client=_Client())
```

- [ ] **Step 5: Run it, watch it fail**

Run: `pytest tests/test_report.py -v`
Expected: FAIL — no module `vsm.modes.report`

- [ ] **Step 6: Write `vsm/modes/report.py`**

Structure the module as: load the insight artifacts and the snapshot ledger → build the body from `corroborated` findings only (G6) → an `emerging` section, clearly labelled → run G2, G4, G5 over every generated string → bind every claim's citations through G1 → write the four files.

Key requirements the tests pin:

- `methodology.md` states the author-class **basis**, the confidence-tier definitions, what was searched and when, what was excluded and why, and the D10 scope limit **exactly once**: *"This report is not screened for adverse events and is not a pharmacovigilance input."* That sentence appears in `methodology.md` and nowhere else — say it once, in the appendix where scope statements belong.
- `provenance_appendix.md` is a table with one row per cited signal: `signal_id · venue · venue kind · captured_at · collection method · URL`.
- `pulse_report.md` never contains a `single_source` finding in its body; findings below `corroborated` appear only under a heading that names the tier.
- Guards run over model output **and** over our own template prose. `_HONESTY` in the prompts is an optimisation; these three calls are the control.

Offline (no client) the report is assembled from the artifacts with template prose — no model call — so the whole path is demonstrable and testable with `VSM_OFFLINE=1`.

- [ ] **Step 7: Run the suite**

Run: `pytest -q`
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Add REPORT, and rebuild every citation from the ledger"
```

---

## Task 18: UI shell, topics list, topic brief, confirm-spend

**Files:**
- Create: `vsm/ui/__init__.py`, `vsm/ui/app.py`, `vsm/app.py`
- Create: `vsm/ui/templates/_base.html`, `topics.html`, `topic_form.html`, `confirm.html`
- Create: `vsm/ui/static/app.css`
- Test: `tests/test_ui_topics.py`

**REQUIRED SUB-SKILL for every UI task (18, 19, 20): invoke `impeccable` before writing any template or CSS.** This plan specifies behaviour and the routes; `impeccable` owns typography, palette, spacing, layout and states. Do not invent a visual direction here.

**Interfaces:**
- Consumes: `TopicStore`, `RunStore`, `estimate_run_usd`, `BANDS`
- Produces: `create_app(topic_store=None, run_store=None) -> FastAPI`; `app` in `vsm/app.py`
- Routes: `GET /` (topics), `GET /topics/new`, `POST /topics`, `GET /topics/{id}/edit`, `POST /topics/{id}`, `GET /topics/{id}/confirm?band=`, `POST /topics/{id}/mine`

**Screen behaviour:**
1. **Topics** — one card per topic: name, therapeutic area, last snapshot date, snapshot count, spend to date, and a volume sparkline across snapshots. A topic with one snapshot shows the count and no trend line — a single point is not a trend. Empty state explains that momentum needs at least two snapshots.
2. **Topic brief** — create/edit. Spend band as three radio cards, each showing its live estimate.
3. **Confirm spend** — a full interstitial before any live call: the estimate, its four-line breakdown, the cap, and what will be spent where. Confirming is a POST.

- [ ] **Step 1: Invoke the impeccable skill**

Run the `impeccable` skill with: *"Design the shell and first three screens of a local-first healthcare signal-monitoring tool: a topics list with per-topic sparklines, a topic brief form with three spend-band cards, and a confirm-spend interstitial. Constraints: no CDN, no external font, no build step, Jinja2 templates with StrictUndefined, must work with JavaScript disabled."* Follow its output for all visual decisions.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_ui_topics.py
import pytest
from fastapi.testclient import TestClient

from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore
from vsm.ui.app import create_app


@pytest.fixture
def client(tmp_path):
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    return TestClient(create_app(topic_store=ts, run_store=rs)), ts, rs


def test_empty_state_explains_that_momentum_needs_two_snapshots(client):
    c, _, _ = client
    body = c.get("/").text
    assert "two snapshots" in body.lower() or "more than once" in body.lower()


def test_a_topic_appears_on_the_list(client):
    c, ts, _ = client
    ts.create(name="OIC pulse", therapeutic_area="gastroenterology", spend_band="standard")
    assert "OIC pulse" in c.get("/").text


def test_creating_a_topic_redirects_to_the_list(client):
    c, ts, _ = client
    r = c.post("/topics", data={"name": "New", "therapeutic_area": "gi",
                                "spend_band": "probe"}, follow_redirects=False)
    assert r.status_code in (302, 303)
    assert [t.name for t in ts.list()] == ["New"]


def test_the_confirm_screen_shows_the_estimate_and_the_cap(client):
    c, ts, _ = client
    t = ts.create(name="OIC", therapeutic_area="gi", spend_band="standard")
    body = c.get(f"/topics/{t.topic_id}/confirm?band=standard").text
    assert "$" in body
    assert "cap" in body.lower()
    for item in ("serp", "discover", "unlocker", "model"):
        assert item in body.lower()


def test_a_single_snapshot_shows_no_trend_line(client):
    """One point is not a trend, and drawing it as one would be the first lie
    the tool tells."""
    c, ts, rs = client
    t = ts.create(name="OIC", therapeutic_area="gi", spend_band="probe")
    run = rs.start(t.topic_id, "mine")
    rs.write_artifact(run.run_id, "signals.json", [])
    rs.finish(run.run_id, "complete", cost_usd=0.01)
    body = c.get("/").text
    assert "<polyline" not in body


def test_every_page_renders_with_strictundefined(client):
    """StrictUndefined turns a typo'd variable into a 500. Walk every GET."""
    c, ts, _ = client
    t = ts.create(name="OIC", therapeutic_area="gi", spend_band="probe")
    for path in ("/", "/topics/new", f"/topics/{t.topic_id}/edit",
                 f"/topics/{t.topic_id}/confirm?band=probe"):
        assert c.get(path).status_code == 200, path


def test_the_page_requests_nothing_from_the_network(client):
    """No CDN, no external font, no build step — it must work on a plane."""
    c, ts, _ = client
    ts.create(name="OIC", therapeutic_area="gi", spend_band="probe")
    body = c.get("/").text
    assert "//fonts.googleapis" not in body
    assert "https://cdn" not in body
    assert "http://" not in body.replace("http://www.w3.org", "")
```

- [ ] **Step 3: Run it, watch it fail**

Run: `pytest tests/test_ui_topics.py -v`
Expected: FAIL — no module `vsm.ui`

- [ ] **Step 4: Implement the app factory and the three screens**

`vsm/ui/app.py` sets up Jinja with `undefined=StrictUndefined`, mounts `static/`, and registers the seven routes. `vsm/app.py` is the composition root:

```python
"""The composed app. Stores are constructed here and nowhere else."""

from __future__ import annotations

from vsm.config import get_settings
from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore
from vsm.ui.app import create_app

_settings = get_settings()
app = create_app(
    topic_store=TopicStore(_settings.db_path),
    run_store=RunStore(_settings.db_path, _settings.var_dir),
)
```

Templates follow `impeccable`'s output. Remember `{% if foo is defined and foo %}` — a bare `{% if %}` on an undefined name 500s under `StrictUndefined`.

- [ ] **Step 5: Verify in the browser**

Run the dev server via the Browser pane (`preview_start`), not Bash. Add `.claude/launch.json`:

```json
{
  "version": "0.0.1",
  "configurations": [
    {"name": "vsm", "runtimeExecutable": ".venv/bin/python",
     "runtimeArgs": ["-m", "uvicorn", "vsm.app:app", "--port", "8811"],
     "port": 8811}
  ]
}
```

Then `read_console_messages` for errors and `read_page` to confirm structure. Verify it yourself; do not ask the user to check.

- [ ] **Step 6: Run the suite and commit**

Run: `pytest -q`
Expected: all pass

```bash
git add -A
git commit -m "Add the shell, the topics list and the spend confirmation"
```

---

## Task 19: Run stream, snapshot view, insight views

**Files:**
- Create: `vsm/ui/templates/run.html`, `snapshot.html`, `insight.html`
- Modify: `vsm/ui/app.py` — add the routes
- Test: `tests/test_ui_runs.py`

**Interfaces:**
- Consumes: `RunStore`, `vsm.llm.progress`
- Routes: `GET /runs/{run_id}`, `GET /runs/{run_id}/events` (progress poll), `GET /runs/{run_id}/snapshot`, `GET /runs/{run_id}/insight`, `POST /runs/{run_id}/insight`, `POST /runs/{run_id}/report`

**Screen behaviour:**
- **Run stream** — stage timeline, live progress, running cost. Fed by the run-keyed registry in `vsm/llm/progress.py`. It must still render a finished run with scripting disabled.
- **Snapshot** — the signals table, filterable by venue, venue kind, date and confidence tier.
- **Insight** — seven views. **The dual-lens gap leads**, because it is the output nobody thinks to ask for. Momentum and anomaly show `no prior snapshot` in plain words on a topic's first run, never an empty chart.

- [ ] **Step 1: Invoke `impeccable`** for the run timeline, the filterable table, and the seven insight views — leading with the dual-lens gap.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_ui_runs.py
import pytest
from fastapi.testclient import TestClient

from vsm.modes.insight import run_insight
from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore
from vsm.ui.app import create_app


@pytest.fixture
def env(tmp_path):
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    topic = ts.create(name="OIC", therapeutic_area="gastroenterology", spend_band="probe")
    return TestClient(create_app(topic_store=ts, run_store=rs)), ts, rs, topic


def _rows(n_hcp, n_patient):
    rows = [{"signal_id": f"h{i}", "venue": "studentdoctor.net", "theme": "tolerability",
             "title": f"t{i}", "excerpt": "tolerability", "captured_at": "2026-08-25T00:00:00+00:00",
             "collection_method": "serp_result", "url": f"https://studentdoctor.net/{i}"}
            for i in range(n_hcp)]
    rows += [{"signal_id": f"p{i}", "venue": "patient.info", "theme": "tolerability",
              "title": f"p{i}", "excerpt": "tolerability", "captured_at": "2026-08-25T00:00:00+00:00",
              "collection_method": "serp_result", "url": f"https://patient.info/{i}"}
             for i in range(n_patient)]
    return rows


def _snapshot(rs, topic, rows):
    run = rs.start(topic.topic_id, "mine")
    rs.write_artifact(run.run_id, "signals.json", rows)
    rs.write_artifact(run.run_id, "coverage.json", {"venues_attempted": [], "venues_collected": [], "venues_empty": []})
    rs.finish(run.run_id, "complete", cost_usd=0.01)
    return run


def test_the_snapshot_view_lists_its_signals(env):
    c, ts, rs, topic = env
    snap = _snapshot(rs, topic, _rows(2, 1))
    body = c.get(f"/runs/{snap.run_id}/snapshot").text
    assert "studentdoctor.net" in body and "patient.info" in body


def test_the_insight_view_leads_with_the_dual_lens_gap(env):
    """It is the output nobody thinks to ask for, so it does not go below the
    fold behind a chart they already know how to read."""
    c, ts, rs, topic = env
    snap = _snapshot(rs, topic, _rows(2, 2))
    ins = run_insight(topic, snap.run_id, rs)
    body = c.get(f"/runs/{ins.run_id}/insight").text
    gap_at = body.lower().find("dual-lens")
    momentum_at = body.lower().find("momentum")
    assert gap_at != -1 and momentum_at != -1 and gap_at < momentum_at


def test_first_snapshot_says_no_prior_snapshot_in_words(env):
    """Not an empty chart. An empty chart reads as 'nothing is happening'."""
    c, ts, rs, topic = env
    snap = _snapshot(rs, topic, _rows(2, 1))
    ins = run_insight(topic, snap.run_id, rs)
    body = c.get(f"/runs/{ins.run_id}/insight").text
    assert "no prior snapshot" in body.lower()


def test_a_finished_run_renders_without_scripting(env):
    c, ts, rs, topic = env
    snap = _snapshot(rs, topic, _rows(1, 1))
    body = c.get(f"/runs/{snap.run_id}").text
    assert "complete" in body.lower()


def test_the_stance_view_never_shows_a_blended_number(env):
    """The type has nowhere to put one; the template must not compute one either."""
    c, ts, rs, topic = env
    snap = _snapshot(rs, topic, _rows(2, 2))
    ins = run_insight(topic, snap.run_id, rs)
    body = c.get(f"/runs/{ins.run_id}/insight").text.lower()
    assert "overall sentiment" not in body
    assert "hcp" in body and "patient" in body
```

- [ ] **Step 3: Implement the routes and templates, then verify in the browser**

Same Browser-pane workflow as Task 18: `preview_start`, `read_page`, `read_console_messages`. Screenshot only once the views are right.

- [ ] **Step 4: Run the suite and commit**

```bash
git add -A
git commit -m "Add the run stream, the snapshot table and the insight views"
```

---

## Task 20: Report preview with clickable citations, and exports

**Files:**
- Create: `vsm/ui/templates/report.html`
- Modify: `vsm/ui/app.py`
- Test: `tests/test_ui_report.py`

**Interfaces:**
- Routes: `GET /runs/{run_id}/report`, `GET /runs/{run_id}/artifact/{name}` (download)

**The one thing this screen must do:** every claim's citation is clickable through to its source row and its URL. That is the visible half of G1 — the guard is what stops a fabricated citation being written, and this is what lets a reader check that it wasn't.

- [ ] **Step 1: Invoke `impeccable`** for the report preview and the citation-hover/anchor treatment.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_ui_report.py
import pytest
from fastapi.testclient import TestClient

from vsm.modes.insight import run_insight
from vsm.modes.report import run_report
from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore
from vsm.ui.app import create_app


@pytest.fixture
def env(tmp_path):
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    topic = ts.create(name="OIC", therapeutic_area="gi", spend_band="probe")
    rows = [{"signal_id": f"s{i}", "venue": f"v{i}.example.org", "theme": "tolerability",
             "title": f"t{i}", "excerpt": "tolerability",
             "captured_at": "2026-08-25T00:00:00+00:00", "collection_method": "serp_result",
             "url": f"https://v{i}.example.org/{i}"} for i in range(4)]
    mine = rs.start(topic.topic_id, "mine")
    rs.write_artifact(mine.run_id, "signals.json", rows)
    rs.finish(mine.run_id, "complete", cost_usd=0.01)
    ins = run_insight(topic, mine.run_id, rs)
    rep = run_report(topic, ins.run_id, rs)
    return TestClient(create_app(topic_store=ts, run_store=rs)), rs, rep, rows


def test_every_cited_signal_id_is_a_link_to_its_url(env):
    c, rs, rep, rows = env
    body = c.get(f"/runs/{rep.run_id}/report").text
    for row in rows:
        if row["signal_id"] in body:
            assert row["url"] in body, row["signal_id"]


def test_the_confidence_tier_is_visible_on_the_page(env):
    c, rs, rep, _ = env
    body = c.get(f"/runs/{rep.run_id}/report").text.lower()
    assert "corroborated" in body


def test_artifacts_download(env):
    c, rs, rep, _ = env
    r = c.get(f"/runs/{rep.run_id}/artifact/provenance_appendix.md")
    assert r.status_code == 200 and len(r.text) > 0


def test_an_artifact_name_cannot_traverse(env):
    c, rs, rep, _ = env
    assert c.get(f"/runs/{rep.run_id}/artifact/../../../etc/passwd").status_code in (400, 404)
```

- [ ] **Step 3: Implement, verify in the browser, run the suite, commit**

```bash
git add -A
git commit -m "Preview the report with every citation clickable to its source"
```

---

## Task 21: The two integration tests the spec names

**Files:**
- Test: `tests/test_integration.py`

These are the last two assertions in spec §7 with no home yet. Both are
end-to-end and both guard a claim the tool makes about itself.

**Interfaces:**
- Consumes: everything. Produces nothing — this task adds tests only.

- [ ] **Step 1: Write the offline test**

```python
# tests/test_integration.py
"""The two end-to-end assertions from spec §7.

Both are about promises the tool makes rather than behaviour any one module
owns, which is why neither fits inside a unit test file.
"""

import pytest

from vsm.modes.insight import run_insight
from vsm.modes.report import run_report
from vsm.runs.store import RunStore
from vsm.topics.store import TopicStore


@pytest.fixture
def env(tmp_path):
    ts = TopicStore(tmp_path / "db")
    rs = RunStore(tmp_path / "db", tmp_path / "var")
    topic = ts.create(name="OIC", therapeutic_area="gastroenterology",
                      spend_band="probe", brand="Symproic", molecule="naldemedine")
    return ts, rs, topic


def _rows(n):
    return [{"signal_id": f"s{i}", "venue": f"v{i}.example.org",
             "theme": "tolerability", "title": f"t{i}", "excerpt": "tolerability",
             "captured_at": "2026-08-25T00:00:00+00:00",
             "collection_method": "serp_result",
             "url": f"https://v{i}.example.org/{i}"} for i in range(n)]


def test_offline_makes_no_outbound_call_even_with_both_keys_present(monkeypatch, env):
    """The master switch, asserted at the socket rather than at the config.

    A settings test proves the flag resolves. This proves nothing reaches the
    network — which is the actual promise, and the one that matters when a
    developer has real keys in their shell.
    """
    import socket

    monkeypatch.setenv("VSM_OFFLINE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real-looking-key")
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "bd-real-looking-key")
    monkeypatch.setenv("VSM_MINER", "live")

    def _refuse(*args, **kwargs):
        raise AssertionError("an outbound connection was attempted while offline")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)

    from vsm.config import get_settings
    from vsm.llm.client import get_client

    settings = get_settings(refresh=True)
    assert settings.effective_miner_mode() == "fake"
    assert get_client(settings) is None

    ts, rs, topic = env
    mine = rs.start(topic.topic_id, "mine")
    rs.write_artifact(mine.run_id, "signals.json", _rows(4))
    rs.finish(mine.run_id, "complete", cost_usd=0.0)
    insight = run_insight(topic, mine.run_id, rs, client=None)
    run_report(topic, insight.run_id, rs, client=None)


def test_a_report_resolves_back_to_the_exact_rows_it_cites(env):
    """Chaining. A client asks "where did this come from" and the answer has to
    survive three runs of indirection: report -> insight -> snapshot -> row.
    """
    ts, rs, topic = env
    rows = _rows(4)

    mine = rs.start(topic.topic_id, "mine")
    rs.write_artifact(mine.run_id, "signals.json", rows)
    rs.finish(mine.run_id, "complete", cost_usd=0.01)

    insight = run_insight(topic, mine.run_id, rs)
    report = run_report(topic, insight.run_id, rs)

    # report -> insight -> snapshot, by parent pointer alone
    assert report.parent_run_id == insight.run_id
    assert rs.get(insight.run_id).parent_run_id == mine.run_id

    # every id in the appendix is a real row in that snapshot, with its real URL
    appendix = rs.read_artifact(report.run_id, "provenance_appendix.md")
    ledger = {r["signal_id"]: r for r in rs.read_artifact(mine.run_id, "signals.json")}
    cited = [sid for sid in ledger if sid in appendix]
    assert cited, "the appendix cited nothing at all"
    for sid in cited:
        assert ledger[sid]["url"] in appendix
        assert ledger[sid]["venue"] in appendix


def test_the_author_seam_survives_a_resolver_swap_end_to_end(env):
    """Spec §3.3. Swapping in an identity resolver must change the recorded
    basis and nothing about the shape of what INSIGHT writes."""
    from vsm.analysis.authorclass import AuthorClass

    class StubIdentity:
        def resolve(self, signal):
            return AuthorClass("hcp", "identity", 0.97, "NPI matched", npi="1234567890")

    ts, rs, topic = env
    rows = _rows(4)

    a = rs.start(topic.topic_id, "mine")
    rs.write_artifact(a.run_id, "signals.json", rows)
    rs.finish(a.run_id, "complete", cost_usd=0.0)
    venue_run = run_insight(topic, a.run_id, rs)

    b = rs.start(topic.topic_id, "mine")
    rs.write_artifact(b.run_id, "signals.json", rows)
    rs.finish(b.run_id, "complete", cost_usd=0.0)
    ident_run = run_insight(topic, b.run_id, rs, resolver=StubIdentity())

    venue_stance = rs.read_artifact(venue_run.run_id, "stance.json")
    ident_stance = rs.read_artifact(ident_run.run_id, "stance.json")

    assert {k for s in venue_stance for k in s} == {k for s in ident_stance for k in s}
    assert all(s["basis"] == "venue" for s in venue_stance)
    assert all(s["basis"] == "identity" for s in ident_stance)
```

- [ ] **Step 2: Run them**

Run: `pytest tests/test_integration.py -v`
Expected: 3 passed. A failure in the offline test is the most serious result this
suite can produce — it means the master switch does not hold, and nothing else
should be worked on until it does.

- [ ] **Step 3: Run the whole suite**

Run: `pytest -q`
Expected: all pass, no xfail

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "Assert the offline switch at the socket, and the citation chain end to end"
```

---

## Task 22: One live smoke run, with the cost recorded

**Files:**
- Create: `docs/SMOKE-2026-08-25.md`
- Test: none — this task's deliverable is a recorded observation

**Interfaces:**
- Consumes: the whole tool, with real keys
- Produces: a dated record of one real run, and any correction to the cost constants in `vsm/guards/cost.py` that the run shows to be needed

**This is the first task that spends money.** Everything before it runs hermetically.

- [ ] **Step 1: Confirm the keys are present and the cap is set**

```bash
grep -c . .env && .venv/bin/python -c "
from vsm.config import Settings
s = Settings.from_env()
print('offline:', s.offline)
print('miner:', s.effective_miner_mode())
print('drafter:', s.effective_drafter_mode())
print('cap: \$', s.run_cost_cap_usd)
"
```

Expected: `offline: False`, `miner: live`, `drafter: llm`, a cap of 5.0 or lower.

- [ ] **Step 2: Run a `probe` band on one real topic**

Use a topic with a genuine therapeutic area. `probe` buys no page fetches, so the sweep is SERP and Discover only and should land near $0.02–$0.05. Go through the UI so the confirm-spend interstitial is exercised on a real spend.

- [ ] **Step 3: Record what actually happened**

Write `docs/SMOKE-2026-08-25.md` with: the topic, the band, the estimate the UI showed, the **actual** cost from `cost.json`, the row count, which venues answered and which came back empty, and anything that behaved differently from the fake miner. Record failures too — a smoke doc that only records success is a press release.

- [ ] **Step 4: Compare the estimate to the actual and state the gap**

If the estimate was more than 2× off in either direction, fix `MODEL_USD_PER_CLUSTER` or the per-call constants in `vsm/guards/cost.py` and say so in the doc. An estimate an operator learns to ignore is worse than none, because they stop reading the confirm screen.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Record the first live run, and reconcile the estimate against it"
```

---

## Task 23: Create the GitHub repository and push

**Files:**
- Modify: `README.md` — add the repo URL and a one-line status

**Interfaces:**
- Consumes: a clean tree and a green suite
- Produces: `github.com/daniellazar-cpu/vi-signal-mine`, private, with `main` pushed

- [ ] **Step 1: Confirm the working tree is clean and the suite is green**

```bash
git status --porcelain && .venv/bin/python -m pytest -q
```

Expected: no output from `git status`, and every test passing. Do not push a red suite.

- [ ] **Step 2: Confirm no secret is about to be committed**

```bash
git ls-files | xargs grep -lE "sk-ant-|BRIGHTDATA_API_KEY=[^[:space:]]" 2>/dev/null || echo "clean"
git check-ignore -q .env && echo ".env is ignored" || echo "WARNING: .env is NOT ignored"
```

Both lines must be reassuring before continuing. `.env.example` contains empty values by design; a populated `.env` must never be tracked.

- [ ] **Step 3: Create the repository, private**

```bash
gh repo create daniellazar-cpu/vi-signal-mine --private \
  --description "A pulse instrument: what is being said about a brand or product online, and what changed" \
  --source . --remote origin
```

- [ ] **Step 4: Push**

```bash
git push -u origin main
```

- [ ] **Step 5: Verify what landed**

```bash
gh repo view daniellazar-cpu/vi-signal-mine --json name,visibility,url
gh api "repos/daniellazar-cpu/vi-signal-mine/contents/.env" 2>&1 | grep -q "Not Found" && echo "no .env on the remote"
```

- [ ] **Step 6: Add the URL to the README and push**

```bash
git add README.md && git commit -m "Point the README at the repository" && git push
```

---

## Appendix: what to do when a test disagrees with you

Several tests in this plan encode a decision rather than a mechanism — the
absence of a blended stance field, `unclear` rather than `neutral` when no
classifier ran, `None` rather than `0` for a first-snapshot delta, syndication
collapsing to one source, an unbindable citation blocking rather than dropping.

If one of them fails and the fix looks like loosening the assertion, it is
almost certainly the implementation that is wrong. Each of those tests exists
because the looser behaviour produces a report that is confidently incorrect —
which is the only failure mode that matters in something handed to a client.

A test that genuinely encodes stale behaviour should be **rewritten with the
reason recorded in the commit message**, never quietly relaxed.


---

## Task 24: The Postgres and blob backend

**Files:**
- Create: `vsm/backends/__init__.py`, `vsm/backends/postgres.py`, `vsm/backends/blob.py`, `vsm/backends/dburl.py`
- Modify: `vsm/storage.py` — `open_stores` selects a backend from settings
- Modify: `pyproject.toml` — add `psycopg[binary]` as an optional extra, not a core dependency
- Test: `tests/test_dburl.py`, `tests/test_storage_contract.py` (register the new backend)

**Interfaces:**
- Consumes: `vsm/storage.py`'s two Protocols, `Settings`
- Produces: `PostgresTopicStore`, `PostgresRunStore`, `BlobArtifacts`; `resolve_db_url(env) -> str | None`; `open_stores(settings)` returning the Postgres pair when a database is configured and the SQLite pair otherwise

**Read the spec's §11 before starting.** It records what the parent engine already
lost to this exact platform, and every requirement below comes from one of those
failures rather than from theory.

- [ ] **Step 1: Write the failing `resolve_db_url` test**

```python
# tests/test_dburl.py
from vsm.backends.dburl import resolve_db_url


def test_unpooled_url_wins():
    """The pooled URL is PgBouncer in transaction mode and does not support
    prepared statements — a failure that surfaces as a confusing runtime error
    rather than at connect time. Prefer the unpooled one."""
    got = resolve_db_url({
        "POSTGRES_URL": "postgres://pooled/db",
        "POSTGRES_URL_NON_POOLING": "postgres://direct/db",
    })
    assert "direct" in got


def test_the_postgres_scheme_alias_is_rewritten():
    """Every provider's dashboard emits `postgres://`. Drivers want
    `postgresql://`. Rewriting it here removes the trap rather than documenting
    it."""
    assert resolve_db_url({"DATABASE_URL": "postgres://h/db"}).startswith("postgresql://")


def test_no_database_configured_returns_none_not_a_tmp_sqlite_path():
    """The parent fell back to `sqlite:////tmp/...` here and lost a real
    visitor's consent record: /tmp on a serverless host belongs to one
    invocation, so the write succeeded and the container holding it was
    destroyed. Returning None makes the caller decide, loudly."""
    assert resolve_db_url({}) is None


def test_every_recognised_variable_name():
    for name in ("POSTGRES_URL_NON_POOLING", "POSTGRES_URL", "DATABASE_URL"):
        assert resolve_db_url({name: "postgres://h/db"}) is not None
```

- [ ] **Step 2: Run it, watch it fail, then write `vsm/backends/dburl.py`**

Read the three variables in that order. Rewrite the `postgres://` scheme. Return
`None` when none is set — the caller warns; this module does not guess.

- [ ] **Step 3: Write the Postgres stores**

Same public methods as the SQLite pair, own SQL. Two notes that will otherwise
cost an hour: Postgres placeholders are `%s` not `?`, and the monotonic `seq`
column is `BIGSERIAL` rather than a `SELECT COALESCE(MAX(seq),0)+1` subquery —
which is also safer, because the subquery races under concurrency and the
sequence does not. Snapshot ordering depends on `seq` (Task 4's ruling), so this
is load-bearing, not cosmetic.

- [ ] **Step 4: Write `BlobArtifacts`**

Artifacts are files locally and blobs on Vercel. Keep the same
`write_artifact` / `read_artifact` / `artifacts_dir` surface. **Carry the
traversal guard across** — Task 4 rejects an artifact name that escapes its run
directory, and a key-based store needs the same check on the key, for the same
reason.

- [ ] **Step 5: Register the backend in the shared contract suite**

`tests/test_storage_contract.py` is parametrised over a store factory. Add the
Postgres+blob factory, skipped when no test database is configured. Every case
Task 4 wrote must pass against the new backend unchanged; if a case needs
altering to pass, the backend is wrong, not the case.

- [ ] **Step 6: `open_stores` selects, and says which it chose**

Postgres+blob when `resolve_db_url` finds a URL, SQLite+filesystem otherwise, and
it **logs which one at INFO**. The parent's own note on this is the reason: the
warning went nowhere because no handler was configured, so the one signal saying
"your writes are being lost" was discarded. Log the consequence, not the
condition.

- [ ] **Step 7: Run the suite and commit**

```bash
git add -A
git commit -m "Add the Postgres and blob backend behind the storage contract"
```

---

## Task 25: Make the app survive Vercel

**Files:**
- Create: `api/index.py`, `vercel.json`, `.vercelignore`
- Create: `vsm/platform.py` — where the app is running, and what that forbids
- Modify: `vsm/modes/insight.py` — resumable passes (spec D17)
- Modify: `vsm/modes/mine.py` — band restriction (spec D14)
- Test: `tests/test_platform.py`, `tests/test_insight_resume.py`

**Interfaces:**
- Consumes: `Settings`, the mode functions
- Produces: `platform.is_vercel()`, `platform.vercel_env()`, `platform.assert_serveable()`, `platform.assert_band_allowed(band)`; `run_insight(..., resume=True)`

- [ ] **Step 1: Write the platform test**

```python
# tests/test_platform.py
import pytest

from vsm.errors import GuardViolation
from vsm.platform import assert_band_allowed, assert_serveable, is_vercel


def test_production_deployment_refuses_to_serve(monkeypatch):
    """Spec D15. Protection is Vercel preview gating, which covers preview
    deployments only. This guard is what makes 'preview-only' a property of the
    code instead of a dashboard setting that has to stay correct — a deploy that
    escapes to a production domain is inert rather than open, with the API keys
    behind it."""
    monkeypatch.setenv("VERCEL_ENV", "production")
    with pytest.raises(GuardViolation, match="production"):
        assert_serveable()


def test_preview_deployment_serves(monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "preview")
    assert assert_serveable() is None


def test_local_serves(monkeypatch):
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    assert assert_serveable() is None
    assert is_vercel() is False


@pytest.mark.parametrize("band", ["standard", "deep"])
def test_only_probe_runs_on_vercel(monkeypatch, band):
    """Spec D14. A standard or deep sweep does not fit in a function timeout,
    and a sweep that dies halfway leaves a half-written snapshot that later
    momentum silently treats as real."""
    monkeypatch.setenv("VERCEL", "1")
    with pytest.raises(GuardViolation, match="probe"):
        assert_band_allowed(band)


def test_probe_runs_on_vercel(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    assert assert_band_allowed("probe") is None


def test_every_band_runs_locally(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    for band in ("probe", "standard", "deep"):
        assert assert_band_allowed(band) is None


def test_the_refusal_names_where_to_run_it_instead(monkeypatch):
    """A guard that only says no teaches nothing."""
    monkeypatch.setenv("VERCEL", "1")
    with pytest.raises(GuardViolation) as exc:
        assert_band_allowed("deep")
    assert "local" in str(exc.value).lower()
```

- [ ] **Step 2: Write `vsm/platform.py`**

`is_vercel()` reads `VERCEL`. `vercel_env()` reads `VERCEL_ENV`.
`assert_serveable()` raises when the env is `production`. `assert_band_allowed`
raises for anything but `probe` on Vercel, and the message names local execution
as the alternative.

- [ ] **Step 3: Wire both guards in**

`assert_serveable()` runs as ASGI middleware in `vsm/ui/app.py`, so it covers
**every** route including static and health — a guard with an exempt route is a
guard with a way around it. `assert_band_allowed(topic.spend_band)` runs in
`run_mine` before the estimate.

- [ ] **Step 4: Write the INSIGHT resume test**

```python
# tests/test_insight_resume.py
def test_a_resumed_insight_skips_passes_already_on_disk(tmp_path):
    """Spec D17. INSIGHT is the mode that will hit a function timeout on a
    large snapshot. Each pass already writes its artifact the moment it
    finishes, so resuming costs a re-request rather than the work."""
    # Build a snapshot, run insight, delete ONE artifact, re-run with
    # resume=True, and assert: the deleted artifact is rebuilt, and the
    # surviving artifacts keep their original mtime and byte content.


def test_resume_false_rebuilds_everything(tmp_path):
    # Same setup; assert every artifact is rewritten.
```

Write both bodies out fully when you implement — the assertions above describe
what to check, and mtime plus byte-identity together are what prove a pass was
skipped rather than re-run to the same answer.

- [ ] **Step 5: Implement `resume` in `run_insight`**

Default `resume=True`. Before each pass, if its artifact exists on this run,
skip it. A resumed run must produce the identical artifact set to an unresumed
one — the difference is only what was recomputed.

- [ ] **Step 6: Write `api/index.py`, `vercel.json`, `.vercelignore`**

Four things the parent learned the hard way, all in spec §11:

1. Vercel discovers functions by **scanning `api/`**; it does not read an
   entrypoint from `pyproject.toml`. A `[tool.vercel]` table is inert.
2. The rewrite destination **must carry `$1`**. Without it every path collapses
   to one literal path, matches no route, and the app serves its own styled 404
   for every URL — clearly running, serving nothing.
3. Strip the function prefix with an **ASGI wrapper, not `root_path`**.
   `root_path` also shifts URL *generation*, which would put `/api/index` into
   every link the app emits.
4. Set `VSM_VAR_DIR=/tmp/vsm-var` so the ephemeral path is at least writable —
   and rely on Task 24's Postgres+blob for anything that must survive.

`.vercelignore` must not exclude anything the app reads at runtime. The parent
shipped a deployment whose seed loader was excluded and spent a cycle on it.

- [ ] **Step 7: Run the suite and commit**

```bash
git add -A
git commit -m "Refuse to serve a production deployment, and make INSIGHT resumable"
```

---

## Task 26: Deploy, and verify it actually works

**Files:**
- Create: `docs/DEPLOY.md`

**Interfaces:**
- Consumes: the pushed repository from Task 23, a Vercel project
- Produces: a gated preview deployment, and a record of what was verified on it

**This task spends money and publishes something. Do not run it without the owner present** — creating the Vercel project, provisioning the database, and setting the secrets are all theirs to do or approve.

- [ ] **Step 1: Write `docs/DEPLOY.md` first**

The exact sequence: create the Vercel project from the repo, provision Postgres,
set `ANTHROPIC_API_KEY` / `BRIGHTDATA_API_KEY` / `BRIGHTDATA_SERP_ZONE` /
`BRIGHTDATA_UNLOCKER_ZONE` / `VSM_OFFLINE=0` / `VSM_RUN_COST_CAP_USD`, confirm
Vercel Authentication is enabled on preview deployments, and ship via the
`deploy` branch. **Never `vercel --prod`** — that is the existing convention for
these apps, and Task 25's guard now enforces it in code.

- [ ] **Step 2: Deploy the `deploy` branch as a preview**

- [ ] **Step 3: Verify, in the browser, in this order**

1. The preview URL demands authentication before rendering anything.
2. The topics page renders and can create a topic — **then reload from a
   different request and confirm the topic is still there.** This is the parent's
   exact failure and the only way to catch it is to look after the container has
   turned over.
3. A `probe` MINE run completes inside the function timeout, and its snapshot is
   readable afterwards.
4. `standard` is refused, with a message naming local execution.
5. An INSIGHT run over that snapshot completes, or times out and **resumes** to
   completion on a second request.
6. A report renders with its citations clickable.

- [ ] **Step 4: Record what actually happened**

Append results to `docs/DEPLOY.md`: the URL, the wall-clock of the probe run, the
real cost, and anything that behaved differently from local. Record failures too.
If INSIGHT could not finish even with resume, say so plainly and state the
snapshot size at which it stopped being viable — that number is the honest limit
of D14 and belongs in writing rather than in someone's memory.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "Record the deployment and what was verified on it" && git push
```
