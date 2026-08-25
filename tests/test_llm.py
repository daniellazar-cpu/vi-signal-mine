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
    assert out.spend.usd > 0


def test_spend_is_a_public_cumulative_ledger():
    """A run makes several calls and records one cost. The client's own
    ``.spend`` must therefore accumulate across calls, not just the per-call
    figure a single ``StructuredOutcome`` carries — and it must be a plain
    public attribute, never read through a defaulting ``getattr``, because a
    zero from a renamed attribute is indistinguishable from a run that
    genuinely spent nothing.
    """
    calls = []
    client = AnthropicClient(
        sdk=_FakeAnthropic({"themes": []}, calls), model="claude-opus-5", cap_usd=5.0
    )
    assert client.spend.usd == 0.0
    assert client.spend.calls == 0

    client.complete_structured(system="SYS", user="USR", schema=SCHEMA, max_output_tokens=64)
    client.complete_structured(system="SYS", user="USR", schema=SCHEMA, max_output_tokens=64)

    assert client.spend.usd > 0
    assert client.spend.calls == 2


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


class _FakeMessagesNoToolUse:
    """Always responds, but never with the forced tool — every attempt looks
    like a successful, billable call that produced nothing usable, which is
    what should make the loop retry (and therefore re-check the budget and
    the backoff) rather than treating it as a one-shot terminal failure.
    """

    def __init__(self, recorder):
        self._recorder = recorder

    def create(self, **kwargs):
        self._recorder.append(kwargs)

        class _Block:
            type = "text"

        class _Usage:
            input_tokens = 1000
            output_tokens = 200
            cache_read_input_tokens = 0
            cache_creation_input_tokens = 0

        class _Msg:
            content = [_Block()]
            usage = _Usage()

        return _Msg()


class _FakeAnthropicNoToolUse:
    def __init__(self, recorder):
        self.messages = _FakeMessagesNoToolUse(recorder)


class _FakeMessagesNoUsageBlock:
    """A successful call whose response carries no usage block at all --
    the case a real API response can return and that must never be recorded
    as a free call."""

    def __init__(self, payload, recorder):
        self._payload = payload
        self._recorder = recorder

    def create(self, **kwargs):
        self._recorder.append(kwargs)

        class _Block:
            type = "tool_use"
            input = self._payload

        class _Msg:
            content = [_Block()]
            usage = None

        return _Msg()


class _FakeAnthropicNoUsageBlock:
    def __init__(self, payload, recorder):
        self.messages = _FakeMessagesNoUsageBlock(payload, recorder)


class _FakeMessagesAlwaysFails:
    """Every attempt raises a transport-level failure (no ``status_code``),
    which ``_may_have_been_billed`` treats as possibly billed -- exactly the
    case that must still land in the ledger as a flagged estimate rather than
    a silent $0.00.
    """

    def __init__(self, recorder):
        self._recorder = recorder

    def create(self, **kwargs):
        self._recorder.append(kwargs)
        raise RuntimeError("connection reset")


class _FakeAnthropicAlwaysFails:
    def __init__(self, recorder):
        self.messages = _FakeMessagesAlwaysFails(recorder)


def test_a_billed_but_failed_attempt_is_still_booked():
    """A transport failure on a long prompt used to record exactly $0.0000,
    because the attempt meter was built with no ``prompt_chars`` and its
    estimate fell back to zero. Every attempt here fails, and every one of
    them must still add to the ledger.
    """
    calls = []
    client = AnthropicClient(
        sdk=_FakeAnthropicAlwaysFails(calls),
        model="claude-opus-5",
        cap_usd=5.0,
        retry_backoff_s=0.0,
    )
    system = "S" * 5000
    user = "U" * 5000
    out = client.complete_structured(
        system=system, user=user, schema=SCHEMA, max_output_tokens=64
    )
    assert out.ok is False
    assert len(calls) == 3, "all three attempts should have been made"
    assert out.spend.calls == 3
    assert out.spend.estimated_calls == 3
    assert out.spend.usd > 0, "a billed-but-failed attempt must not book $0.00"


def test_a_success_with_no_usage_block_is_booked_and_flagged_estimated():
    """Recording ``usage`` directly with ``LlmSpend.record`` silently drops a
    response that carries no usage block: ``record(None)`` books nothing at
    all, not even the call. The attempt must instead fall through to a
    flagged estimate.
    """
    calls = []
    client = AnthropicClient(
        sdk=_FakeAnthropicNoUsageBlock({"themes": ["x"]}, calls),
        model="claude-opus-5",
        cap_usd=5.0,
    )
    out = client.complete_structured(
        system="SYS", user="USR", schema=SCHEMA, max_output_tokens=64
    )
    assert out.ok is True, "the call still succeeded and must report its data"
    assert out.spend.calls == 1
    assert out.spend.estimated_calls == 1
    assert out.spend.estimated is True
    assert out.spend.usd > 0, "a response with no usage block must not book $0.00"


def test_the_cap_binds_mid_loop():
    """Reproduces the reported defect directly: the budget used to be checked
    once before the first attempt and then only on the exception-retry path,
    so a success that produced nothing usable looped straight back into
    another billed call with no re-check. Each simulated call costs $0.01;
    the cap here permits two but must block the third before it is made.
    """
    calls = []
    client = AnthropicClient(
        sdk=_FakeAnthropicNoToolUse(calls),
        model="claude-opus-5",
        cap_usd=0.012,
        retry_backoff_s=0.0,
    )
    out = client.complete_structured(
        system="SYS", user="USR", schema=SCHEMA, max_output_tokens=64
    )
    assert out.ok is False
    assert len(calls) == 2, "the third, cap-breaching call must never be made"
    assert out.spend.usd <= 0.02 + 1e-9, "spend must not include a third call"


def test_the_retry_backoff_index_is_one_based():
    """``_sleep_before_retry`` computes ``2 ** (attempt - 1)``, so a 0-based
    loop halved every backoff (the first retry waited 0.25s instead of 0.5s).
    The loop must pass attempt numbers 1, 2, ... straight through, matching
    the parent's ``range(1, _MAX_ATTEMPTS + 1)``.
    """
    calls = []
    client = AnthropicClient(
        sdk=_FakeAnthropicAlwaysFails(calls),
        model="claude-opus-5",
        cap_usd=5.0,
        retry_backoff_s=0.0,
    )
    seen_attempts = []
    original = client._sleep_before_retry

    def _spy(attempt, exc):
        seen_attempts.append(attempt)
        return original(attempt, exc)

    client._sleep_before_retry = _spy
    client.complete_structured(system="SYS", user="USR", schema=SCHEMA, max_output_tokens=64)
    assert seen_attempts == [1, 2], "backoff must be requested for attempts 1 and 2, 1-based"


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


def test_system_prompts_are_not_yet_cacheable():
    """Every ``*_SYSTEM`` prompt is ~140 tokens; Claude Opus 5's cacheable-prefix
    floor is 512. None of them is cached today, and the caching discipline they
    keep anyway (byte-identical, no interpolation) earns nothing yet — it costs
    nothing to keep and starts paying off the day one of them grows past the
    floor. This test is the tripwire for that day: it fails once a prompt
    crosses the floor, which is the signal that the docstring's claim needs to
    flip from "not cacheable" to "cacheable" instead of silently going stale.
    """
    from vsm.llm import prompts

    system_prompts = {
        name: value
        for name, value in vars(prompts).items()
        if name.endswith("_SYSTEM")
    }
    assert system_prompts
    for name, text in system_prompts.items():
        assert prefix_is_cacheable("claude-opus-5", text) is False, (
            f"{name} now clears the cacheable-prefix floor — update the "
            "module docstring's caching claim before this test's failure is "
            "the only place that says so"
        )


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
