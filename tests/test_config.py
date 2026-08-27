from pathlib import Path

import pytest

from vsm.config import Settings
from vsm.errors import ConfigError


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


def test_miner_auto_resolves_on_key_presence():
    """Mirrors test_auto_resolves_on_key_presence, but for the miner's auto mode
    — only the drafter's key resolution was covered before this."""
    off = Settings.from_env({"VSM_OFFLINE": "0"})
    on = Settings.from_env({"VSM_OFFLINE": "0", "BRIGHTDATA_API_KEY": "bd-real"})
    assert off.effective_miner_mode() == "fake"
    assert on.effective_miner_mode() == "live"


def test_unknown_mode_is_rejected_loudly():
    from vsm.errors import ConfigError

    with pytest.raises(ConfigError, match="VSM_MINER"):
        Settings.from_env({"VSM_MINER": "sometimes"})


# --- blank env vars mean "use the default", never "this is the value" -------
#
# A real production outage: the hosting dashboard held VSM_MINER with an empty
# value, `_choice` read "" as an invalid mode, and the app raised at import so
# every single request 500'd. These pin the whole class, because the crash was
# the mildest of the five failures an empty var could cause.


def test_a_blank_choice_falls_back_to_the_default():
    """The exact outage: VSM_MINER="" killed the app at import."""
    assert Settings.from_env({"VSM_MINER": ""}).miner_mode == "auto"
    assert Settings.from_env({"VSM_MINER": "   "}).miner_mode == "auto"
    assert Settings.from_env({"VSM_DRAFTER": ""}).drafter_mode == "auto"


def test_a_blank_offline_flag_still_means_offline():
    """The most dangerous of the five. Read naively, VSM_OFFLINE="" evaluates
    false and silently disarms the master switch that makes outbound calls
    impossible — the app would look configured and be able to spend money."""
    assert Settings.from_env({"VSM_OFFLINE": ""}).offline is True
    assert Settings.from_env({"VSM_OFFLINE": "   "}).offline is True


def test_a_blank_cost_cap_falls_back_rather_than_crashing():
    """float("") raises ValueError, which killed the app the same way."""
    assert Settings.from_env({"VSM_RUN_COST_CAP_USD": ""}).run_cost_cap_usd == 5.0


def test_a_malformed_cost_cap_still_refuses_to_start():
    """Blank is no value; garbage is a mistake. A cap that cannot be parsed
    must never quietly become something permissive."""
    with pytest.raises(ConfigError, match="VSM_RUN_COST_CAP_USD"):
        Settings.from_env({"VSM_RUN_COST_CAP_USD": "cheap"})


def test_a_blank_var_dir_does_not_become_the_working_directory():
    """Path("") is Path("."), which would scatter run artifacts into cwd."""
    assert Settings.from_env({"VSM_VAR_DIR": ""}).var_dir == Path("var")


def test_blank_zones_and_model_fall_back():
    s = Settings.from_env(
        {"BRIGHTDATA_SERP_ZONE": "", "BRIGHTDATA_UNLOCKER_ZONE": "", "VSM_LLM_MODEL": ""}
    )
    assert s.brightdata_serp_zone == "dataweb_serp_api1"
    assert s.brightdata_unlocker_zone == "dataweb"
    assert s.llm_model == "claude-opus-5"


def test_a_genuinely_wrong_choice_still_raises():
    """The guard must not have been loosened into uselessness."""
    with pytest.raises(ConfigError, match="VSM_MINER"):
        Settings.from_env({"VSM_MINER": "sometimes"})


def test_the_var_dir_default_is_writable_on_vercel():
    """A blank VSM_VAR_DIR in a dashboard overrides vercel.json's correct value,
    and a relative path lands under Vercel's read-only /var/task where every
    write fails. Found in the real deployment's env, not imagined."""
    assert Settings.from_env({"VSM_VAR_DIR": "", "VERCEL_ENV": "production"}).var_dir == Path("/tmp/vsm-var")
    assert Settings.from_env({"VERCEL": "1"}).var_dir == Path("/tmp/vsm-var")


def test_the_var_dir_default_stays_relative_locally():
    """A local install must be untouched by the platform special case."""
    assert Settings.from_env({}).var_dir == Path("var")


def test_an_explicit_var_dir_still_wins_everywhere():
    assert Settings.from_env({"VSM_VAR_DIR": "/custom", "VERCEL_ENV": "production"}).var_dir == Path("/custom")
