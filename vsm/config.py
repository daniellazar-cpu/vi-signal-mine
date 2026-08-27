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


def _raw(env: Mapping[str, str], key: str, default: str) -> str:
    """The value of ``key``, treating blank as **absent** rather than as a value.

    Every reader below goes through this, and it exists because of a real
    outage. A hosting dashboard will happily hold an environment variable with
    an empty value, and a platform may inject a declared-but-unset variable as
    ``""``. Read naively, ``VSM_MINER=""`` is not "unset" — it is the string
    ``""``, which is not a valid mode, so :func:`_choice` raised at import time
    and the entire application failed to start on every request.

    The crash was the mild version. The same naive read made
    ``VSM_RUN_COST_CAP_USD=""`` a ``ValueError`` from ``float("")``,
    ``VSM_VAR_DIR=""`` resolve to the working directory, and — worst —
    ``VSM_OFFLINE=""`` evaluate as *false*, silently disarming the master
    switch that is supposed to make outbound calls impossible.

    An operator who clears a field means "use the default". Blank is not a
    value, and the one place to say so is here.
    """
    value = env.get(key)
    if value is None:
        return default
    value = str(value).strip()
    return value if value else default


def _flag(env: Mapping[str, str], key: str, default: str) -> bool:
    return _raw(env, key, default).lower() in _TRUE


def _choice(env: Mapping[str, str], key: str, allowed: tuple[str, ...], default: str) -> str:
    """One of ``allowed``, blank meaning the default.

    A genuinely wrong value still raises — ``VSM_MINER=sometimes`` is a
    mistake worth stopping for, and failing loudly at startup beats guessing.
    Blank is not a wrong value; it is no value.
    """
    value = _raw(env, key, default).lower()
    if value not in allowed:
        raise ConfigError(f"{key}={value!r} is not one of {allowed}", rule="config")
    return value


def _default_var_dir(env: Mapping[str, str]) -> str:
    """Where to write when nobody said — and the one writable path on Vercel.

    ``var`` is right locally and wrong on a serverless function: the code is
    unpacked under a read-only ``/var/task``, so a relative path makes every
    write fail. ``vercel.json`` declares ``VSM_VAR_DIR=/tmp/vsm-var`` for
    exactly that reason, but a dashboard variable **overrides** ``vercel.json``,
    so an operator who creates ``VSM_VAR_DIR`` as an empty placeholder silently
    removes the only correct value. That is not hypothetical: it is the state
    this deployment was found in.

    The platform check is duplicated from ``vsm.platform.is_vercel`` rather than
    imported, because ``vsm.platform`` imports this module — taking the
    dependency the other way would make the cycle real. Kept to one line so the
    duplication cannot drift into a second opinion about anything else.
    """
    on_vercel = bool(str(env.get("VERCEL_ENV", "")).strip()) or str(
        env.get("VERCEL", "")
    ).strip() == "1"
    return "/tmp/vsm-var" if on_vercel else "var"


def _money(env: Mapping[str, str], key: str, default: str) -> float:
    """A dollar figure, refusing to start on a value that is not a number.

    Separate from the others because the failure mode is specific: a cap that
    cannot be parsed must never fall back to something permissive. A malformed
    cap is a mistake to stop for; a blank one means the default.
    """
    value = _raw(env, key, default)
    try:
        return float(value)
    except ValueError:
        raise ConfigError(
            f"{key}={value!r} is not a number, and a spend cap must be one",
            rule="config",
        ) from None


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
            brightdata_serp_zone=_raw(env, "BRIGHTDATA_SERP_ZONE", "dataweb_serp_api1"),
            brightdata_unlocker_zone=_raw(env, "BRIGHTDATA_UNLOCKER_ZONE", "dataweb"),
            llm_model=_raw(env, "VSM_LLM_MODEL", "claude-opus-5"),
            run_cost_cap_usd=_money(env, "VSM_RUN_COST_CAP_USD", "5.0"),
            var_dir=Path(_raw(env, "VSM_VAR_DIR", _default_var_dir(env))),
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
