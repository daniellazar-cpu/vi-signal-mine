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


@pytest.mark.xfail(reason="guards land in Task 16", strict=False)
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
