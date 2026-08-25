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
