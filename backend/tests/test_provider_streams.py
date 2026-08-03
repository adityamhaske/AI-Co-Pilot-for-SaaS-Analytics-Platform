"""Inbound tests: what each adapter makes of a provider's *response*.

`test_providers.py` covers the outbound half — neutral types translated into each
vendor's wire format. That half was well covered and none of it was wrong.

Every bug the first live run found was on this side, reading the response back:

  * Gemini returns `finish_reason` as an enum, so `str()` yields "FinishReason.STOP"
    rather than "STOP" and every normal completion reported `stop_reason=other`.
  * Gemini attaches a `thought_signature` to each function call and rejects a follow-up
    that replays the call without it, so it has to survive the round trip.
  * OpenAI streams tool arguments as string fragments across deltas, keyed only by an
    `index`; concatenating two calls' fragments produces one corrupt argument string.

None of those are reachable through `to_wire_*`. They need a response fed back through
`stream_turn`, which is what this file does — with fakes shaped like each SDK's objects,
so no API key and no network are involved.
"""

import pytest

from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import TextChunk, ToolCallStarted, TurnFinished
from app.providers.gemini_provider import GeminiProvider
from app.providers.openai_provider import OpenAIProvider

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class Obj:
    """Attribute bag. The adapters read responses with getattr, so this is enough."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FinishReasonEnum:
    """Reproduces the shape that broke `_stop_reason`.

    The real SDK hands back an enum whose `str()` is "FinishReason.STOP". Any fake that
    is a plain string passes against the buggy code, so the enum is the whole point.
    """

    def __init__(self, name: str):
        self.name = name

    def __str__(self) -> str:
        return f"FinishReason.{self.name}"


async def aiter(items):
    for item in items:
        yield item


def build(provider_cls, client):
    """A provider with its client replaced, skipping __init__'s SDK import and key check."""
    instance = object.__new__(provider_cls)
    instance.model = "test-model"
    instance._client = client
    return instance


async def drain(provider):
    return [
        event
        async for event in provider.stream_turn(
            system="s", turns=[], tools=[], max_tokens=100
        )
    ]


def finished(events) -> TurnFinished:
    return next(e for e in events if isinstance(e, TurnFinished))


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------


def gemini_client(chunks):
    async def generate_content_stream(**_kwargs):
        return aiter(chunks)

    return Obj(aio=Obj(models=Obj(generate_content_stream=generate_content_stream)))


def gemini_chunk(parts, finish_reason=None, usage=None):
    return Obj(
        candidates=[Obj(content=Obj(parts=parts), finish_reason=finish_reason)],
        usage_metadata=usage,
    )


async def test_gemini_maps_the_finish_reason_enum_to_end_turn():
    """The regression test for a normal completion reporting `other`."""
    chunks = [
        gemini_chunk([Obj(text="hello", function_call=None)]),
        gemini_chunk(
            [],
            finish_reason=FinishReasonEnum("STOP"),
            usage=Obj(prompt_token_count=11, candidates_token_count=5),
        ),
    ]
    events = await drain(build(GeminiProvider, gemini_client(chunks)))

    assert finished(events).stop_reason == "end_turn"
    assert [e.text for e in events if isinstance(e, TextChunk)] == ["hello"]
    assert (finished(events).input_tokens, finished(events).output_tokens) == (11, 5)


async def test_gemini_maps_max_tokens_and_leaves_anything_else_as_other():
    for name, expected in [("MAX_TOKENS", "max_tokens"), ("SAFETY", "other")]:
        chunks = [gemini_chunk([], finish_reason=FinishReasonEnum(name))]
        events = await drain(build(GeminiProvider, gemini_client(chunks)))
        assert finished(events).stop_reason == expected, name


async def test_gemini_keeps_the_thought_signature_for_the_replay():
    """Dropping this is a 400 on the next request, not a degraded answer."""
    call = Obj(name="get_metric_value", args={"metric": "mrr"})
    chunks = [
        gemini_chunk(
            [Obj(text=None, function_call=call, thought_signature=b"opaque-bytes")],
            finish_reason=FinishReasonEnum("STOP"),
        )
    ]
    events = await drain(build(GeminiProvider, gemini_client(chunks)))
    result = finished(events)

    assert [e.name for e in events if isinstance(e, ToolCallStarted)] == [
        "get_metric_value"
    ]
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].provider_state == {"thought_signature": b"opaque-bytes"}
    assert result.tool_calls[0].arguments == {"metric": "mrr"}
    # A turn with calls is `tool_use` whatever the finish reason says.
    assert result.stop_reason == "tool_use"


async def test_gemini_leaves_provider_state_unset_when_there_is_no_signature():
    call = Obj(name="get_metric_value", args={})
    chunks = [gemini_chunk([Obj(text=None, function_call=call)])]
    result = finished(await drain(build(GeminiProvider, gemini_client(chunks))))

    assert result.tool_calls[0].provider_state is None


async def test_gemini_gives_parallel_calls_distinct_ids():
    """The synthesised id only has to be unique within the turn, but it does have to be."""
    parts = [
        Obj(
            text=None,
            function_call=Obj(name="get_metric_value", args={"metric": "mrr"}),
        ),
        Obj(
            text=None,
            function_call=Obj(name="get_metric_value", args={"metric": "arr"}),
        ),
    ]
    result = finished(
        await drain(build(GeminiProvider, gemini_client([gemini_chunk(parts)])))
    )

    ids = [c.id for c in result.tool_calls]
    assert len(ids) == len(set(ids)) == 2
    assert [c.arguments["metric"] for c in result.tool_calls] == ["mrr", "arr"]


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


def openai_client(chunks):
    async def create(**_kwargs):
        return aiter(chunks)

    return Obj(chat=Obj(completions=Obj(create=create)))


def openai_chunk(*, content=None, tool_calls=None, finish_reason=None, usage=None):
    delta = Obj(content=content, tool_calls=tool_calls)
    return Obj(choices=[Obj(delta=delta, finish_reason=finish_reason)], usage=usage)


def call_delta(index, *, id=None, name=None, arguments=None):
    return Obj(index=index, id=id, function=Obj(name=name, arguments=arguments))


async def test_openai_reassembles_arguments_split_across_deltas():
    """The fragments are meaningless individually; only the concatenation parses."""
    chunks = [
        openai_chunk(tool_calls=[call_delta(0, id="call_a", name="get_metric_value")]),
        openai_chunk(tool_calls=[call_delta(0, arguments='{"met')]),
        openai_chunk(tool_calls=[call_delta(0, arguments='ric": "m')]),
        openai_chunk(tool_calls=[call_delta(0, arguments='rr"}')]),
        openai_chunk(finish_reason="tool_calls"),
    ]
    result = finished(await drain(build(OpenAIProvider, openai_client(chunks))))

    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].arguments == {"metric": "mrr"}
    assert result.tool_calls[0].id == "call_a"
    assert result.stop_reason == "tool_use"


async def test_openai_does_not_merge_two_calls_streamed_interleaved():
    """`index` is the only thing separating them, and the deltas do interleave."""
    chunks = [
        openai_chunk(tool_calls=[call_delta(0, id="call_a", name="get_metric_value")]),
        openai_chunk(tool_calls=[call_delta(1, id="call_b", name="get_metric_trend")]),
        openai_chunk(tool_calls=[call_delta(0, arguments='{"metric":')]),
        openai_chunk(tool_calls=[call_delta(1, arguments='{"metric":')]),
        openai_chunk(tool_calls=[call_delta(0, arguments=' "mrr"}')]),
        openai_chunk(tool_calls=[call_delta(1, arguments=' "churn"}')]),
        openai_chunk(finish_reason="tool_calls"),
    ]
    result = finished(await drain(build(OpenAIProvider, openai_client(chunks))))

    assert [c.name for c in result.tool_calls] == [
        "get_metric_value",
        "get_metric_trend",
    ]
    assert [c.arguments["metric"] for c in result.tool_calls] == ["mrr", "churn"]
    assert [c.id for c in result.tool_calls] == ["call_a", "call_b"]


async def test_openai_announces_each_call_once_not_once_per_fragment():
    chunks = [
        openai_chunk(tool_calls=[call_delta(0, id="call_a", name="get_metric_value")]),
        openai_chunk(tool_calls=[call_delta(0, arguments='{"a":')]),
        openai_chunk(tool_calls=[call_delta(0, arguments="1}")]),
    ]
    events = await drain(build(OpenAIProvider, openai_client(chunks)))

    assert len([e for e in events if isinstance(e, ToolCallStarted)]) == 1


async def test_openai_reports_tool_use_even_when_it_stops_with_stop():
    """A turn carrying calls must be `tool_use`, or the loop stops and never runs them."""
    chunks = [
        openai_chunk(
            tool_calls=[call_delta(0, id="c", name="get_metric_value", arguments="{}")]
        ),
        openai_chunk(finish_reason="stop"),
    ]
    assert (
        finished(await drain(build(OpenAIProvider, openai_client(chunks)))).stop_reason
        == "tool_use"
    )


async def test_openai_streams_text_and_reads_usage():
    chunks = [
        openai_chunk(content="Your MRR "),
        openai_chunk(content="is $5,600."),
        openai_chunk(
            finish_reason="stop", usage=Obj(prompt_tokens=30, completion_tokens=9)
        ),
    ]
    events = await drain(build(OpenAIProvider, openai_client(chunks)))
    result = finished(events)

    assert [e.text for e in events if isinstance(e, TextChunk)] == [
        "Your MRR ",
        "is $5,600.",
    ]
    assert result.text == "Your MRR is $5,600."
    assert result.stop_reason == "end_turn"
    assert (result.input_tokens, result.output_tokens) == (30, 9)


async def test_openai_survives_a_call_that_never_sent_an_id():
    chunks = [
        openai_chunk(
            tool_calls=[call_delta(0, name="get_metric_value", arguments="{}")]
        )
    ]
    result = finished(await drain(build(OpenAIProvider, openai_client(chunks))))

    assert result.tool_calls[0].id  # synthesised, but present — the loop pairs on it


async def test_openai_tolerates_arguments_that_are_not_valid_json():
    """A truncated stream should degrade to empty arguments, not raise mid-generator."""
    chunks = [
        openai_chunk(
            tool_calls=[
                call_delta(0, id="c", name="get_metric_value", arguments='{"met')
            ]
        )
    ]
    result = finished(await drain(build(OpenAIProvider, openai_client(chunks))))

    assert result.tool_calls[0].arguments == {}


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


class FakeAnthropicStream:
    """`messages.stream()` is an async context manager that also yields events."""

    def __init__(self, events, final):
        self._events = events
        self._final = final

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    def __aiter__(self):
        return aiter(self._events)

    async def get_final_message(self):
        return self._final


def anthropic_client(events, final):
    return Obj(
        messages=Obj(stream=lambda **_kwargs: FakeAnthropicStream(events, final))
    )


async def test_anthropic_reads_calls_off_the_assembled_message():
    events_in = [
        Obj(type="text", text="Checking."),
        Obj(
            type="content_block_start",
            index=0,
            content_block=Obj(type="tool_use", name="get_metric_value"),
        ),
    ]
    final = Obj(
        content=[
            Obj(type="text", text="Your MRR is $5,600."),
            Obj(
                type="tool_use",
                id="toolu_1",
                name="get_metric_value",
                input={"metric": "mrr"},
            ),
        ],
        stop_reason="tool_use",
        usage=Obj(input_tokens=42, output_tokens=7),
    )
    events = await drain(build(AnthropicProvider, anthropic_client(events_in, final)))
    result = finished(events)

    assert [e.text for e in events if isinstance(e, TextChunk)] == ["Checking."]
    assert [e.name for e in events if isinstance(e, ToolCallStarted)] == [
        "get_metric_value"
    ]
    assert result.text == "Your MRR is $5,600."
    assert result.tool_calls[0].arguments == {"metric": "mrr"}
    assert result.tool_calls[0].id == "toolu_1"
    assert (result.input_tokens, result.output_tokens) == (42, 7)


async def test_anthropic_announces_parallel_blocks_separately():
    """Keyed on the block index — keying on anything shared would drop the second."""
    events_in = [
        Obj(
            type="content_block_start",
            index=0,
            content_block=Obj(type="tool_use", name="get_metric_value"),
        ),
        Obj(
            type="content_block_start",
            index=1,
            content_block=Obj(type="tool_use", name="get_metric_trend"),
        ),
    ]
    final = Obj(content=[], stop_reason="end_turn", usage=Obj())
    events = await drain(build(AnthropicProvider, anthropic_client(events_in, final)))

    assert [e.name for e in events if isinstance(e, ToolCallStarted)] == [
        "get_metric_value",
        "get_metric_trend",
    ]


async def test_anthropic_ignores_a_text_block_start():
    events_in = [
        Obj(type="content_block_start", index=0, content_block=Obj(type="text")),
    ]
    final = Obj(content=[], stop_reason="end_turn", usage=Obj())
    events = await drain(build(AnthropicProvider, anthropic_client(events_in, final)))

    assert not [e for e in events if isinstance(e, ToolCallStarted)]


async def test_anthropic_maps_stop_reasons():
    for raw, expected in [
        ("end_turn", "end_turn"),
        ("tool_use", "tool_use"),
        ("max_tokens", "max_tokens"),
        ("refusal", "other"),
    ]:
        final = Obj(content=[], stop_reason=raw, usage=Obj())
        events = await drain(build(AnthropicProvider, anthropic_client([], final)))
        assert finished(events).stop_reason == expected, raw


async def test_anthropic_defaults_non_dict_tool_input_to_empty():
    final = Obj(
        content=[Obj(type="tool_use", id="t", name="get_metric_value", input=None)],
        stop_reason="tool_use",
        usage=Obj(),
    )
    result = finished(
        await drain(build(AnthropicProvider, anthropic_client([], final)))
    )

    assert result.tool_calls[0].arguments == {}
