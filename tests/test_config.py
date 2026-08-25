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
