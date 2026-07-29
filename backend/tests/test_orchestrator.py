import json
from unittest.mock import patch

import pytest

from app.streaming.sse import stream_orchestrator

# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class MockEvent:
    """Lightweight stand-in for an Anthropic streaming event."""

    def __init__(self, type_: str, **kwargs):
        self.type = type_
        for k, v in kwargs.items():
            setattr(self, k, v)


class MockToolUseBlock:
    type = "tool_use"

    def __init__(self, id_: str, name: str, input_: dict):
        self.id = id_
        self.name = name
        self.input = input_


class MockTextBlock:
    type = "text"

    def __init__(self, text: str):
        self.text = text


class MockUsage:
    def __init__(self, input_tokens: int = 10, output_tokens: int = 5):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class MockFinalMessage:
    def __init__(self, stop_reason: str = "end_turn", content=None):
        self.stop_reason = stop_reason
        self.content = content or []
        self.usage = MockUsage()


class MockStream:
    """Async context manager + async iterator simulating client.messages.stream."""

    def __init__(self, events: list, final_message: MockFinalMessage):
        self._events = events
        self._final_message = final_message
        self._pos = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._pos >= len(self._events):
            raise StopAsyncIteration
        event = self._events[self._pos]
        self._pos += 1
        return event

    async def get_final_message(self) -> MockFinalMessage:
        return self._final_message


async def collect(gen) -> list:
    return [chunk async for chunk in gen]


def parse_events(chunks: list) -> list:
    """Decode the JSON payload of every SSE data line except the [DONE] sentinel."""
    events = []
    for chunk in chunks:
        body = chunk.removeprefix("data: ").strip()
        if not body or body == "[DONE]":
            continue
        events.append(json.loads(body))
    return events


def scripted_streams(*pairs):
    """Return a side_effect that yields a different MockStream per call."""
    calls = {"n": 0}

    def make(*args, **kwargs):
        idx = calls["n"]
        calls["n"] += 1
        events, final = pairs[min(idx, len(pairs) - 1)]
        return MockStream(events, final)

    return make, calls


# ---------------------------------------------------------------------------
# Basic streaming behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emits_token_events(db_session):
    events = [MockEvent("text", text="Here is your MRR trend.")]
    final = MockFinalMessage(stop_reason="end_turn")

    with patch(
        "app.streaming.sse.client.messages.stream",
        return_value=MockStream(events, final),
    ):
        output = await collect(
            stream_orchestrator(db_session, "tenant_test", "viewer", "What is my MRR?")
        )

    tokens = [e for e in parse_events(output) if e.get("type") == "token"]
    assert tokens, "expected at least one token event"
    assert "MRR trend" in tokens[0]["text"]


@pytest.mark.asyncio
async def test_stream_always_ends_with_done(db_session):
    events = [MockEvent("text", text="Hello!")]
    final = MockFinalMessage(stop_reason="end_turn")

    with patch(
        "app.streaming.sse.client.messages.stream",
        return_value=MockStream(events, final),
    ):
        output = await collect(
            stream_orchestrator(db_session, "tenant_test", "viewer", "Hello")
        )

    assert output[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_reports_token_usage(db_session):
    final = MockFinalMessage(stop_reason="end_turn")
    with patch(
        "app.streaming.sse.client.messages.stream",
        return_value=MockStream([], final),
    ):
        output = await collect(
            stream_orchestrator(db_session, "tenant_test", "viewer", "Hi")
        )

    usage = [e for e in parse_events(output) if e.get("type") == "usage"]
    assert usage == [{"type": "usage", "input_tokens": 10, "output_tokens": 5}]


# ---------------------------------------------------------------------------
# Parallel tool use — regression tests for the scalar-state bug
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_tool_calls_each_get_a_tool_result(db_session):
    """Every tool_use block must receive its own tool_result in one user message.

    The orchestrator used to track the in-flight tool in scalar variables, so when Claude
    emitted two tool_use blocks it kept only the last one and replied with a single
    tool_result. The Anthropic API rejects that message as malformed, and the first
    tool's work was silently discarded.
    """
    first = MockFinalMessage(
        stop_reason="tool_use",
        content=[
            MockToolUseBlock("toolu_a", "get_churn_rate", {"period": "last_month"}),
            MockToolUseBlock(
                "toolu_b", "get_top_customers", {"sort_by": "mrr", "limit": 3}
            ),
        ],
    )
    second = MockFinalMessage(
        stop_reason="end_turn", content=[MockTextBlock("Both are ready.")]
    )

    captured = []

    def make_stream(*args, **kwargs):
        # `messages` is the same list the orchestrator keeps mutating in place across
        # steps, so a shallow copy is needed to freeze what was sent *this* call.
        captured.append(list(kwargs.get("messages") or []))
        if len(captured) == 1:
            return MockStream([], first)
        return MockStream([MockEvent("text", text="Both are ready.")], second)

    with patch("app.streaming.sse.client.messages.stream", side_effect=make_stream):
        with patch("app.streaming.sse.execute_tool", return_value={"ok": True}):
            output = await collect(
                stream_orchestrator(
                    db_session, "tenant_test", "admin", "Churn and top customers?"
                )
            )

    assert len(captured) == 2, "expected a follow-up request after the tool calls"

    tool_result_msg = captured[1][-1]
    assert tool_result_msg["role"] == "user"
    ids = [b["tool_use_id"] for b in tool_result_msg["content"]]
    assert ids == [
        "toolu_a",
        "toolu_b",
    ], f"expected one tool_result per tool_use block, got {ids}"
    assert all(b["type"] == "tool_result" for b in tool_result_msg["content"])
    assert output[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_parallel_tool_calls_announce_each_tool(db_session):
    first = MockFinalMessage(
        stop_reason="tool_use",
        content=[
            MockToolUseBlock("toolu_a", "get_churn_rate", {"period": "last_month"}),
            MockToolUseBlock(
                "toolu_b", "get_top_customers", {"sort_by": "mrr", "limit": 3}
            ),
        ],
    )
    second = MockFinalMessage(stop_reason="end_turn")

    start_events = [
        MockEvent(
            "content_block_start",
            index=0,
            content_block=MockToolUseBlock("toolu_a", "get_churn_rate", {}),
        ),
        MockEvent(
            "content_block_start",
            index=1,
            content_block=MockToolUseBlock("toolu_b", "get_top_customers", {}),
        ),
    ]
    make, _ = scripted_streams((start_events, first), ([], second))

    with patch("app.streaming.sse.client.messages.stream", side_effect=make):
        with patch("app.streaming.sse.execute_tool", return_value=[{"a": 1}]):
            output = await collect(
                stream_orchestrator(db_session, "tenant_test", "admin", "Two things")
            )

    names = [e["name"] for e in parse_events(output) if e.get("type") == "tool_call"]
    assert names == ["get_churn_rate", "get_top_customers"]


# ---------------------------------------------------------------------------
# Authorisation, bounds and error containment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthorized_tool_yields_no_data_and_terminates(db_session):
    first = MockFinalMessage(
        stop_reason="tool_use",
        content=[
            MockToolUseBlock("toolu_x", "get_churn_rate", {"period": "last_month"})
        ],
    )
    second = MockFinalMessage(stop_reason="end_turn")
    make, _ = scripted_streams(
        ([], first), ([MockEvent("text", text="I cannot access that.")], second)
    )

    with patch("app.streaming.sse.client.messages.stream", side_effect=make):
        with patch("app.streaming.sse.check_tool_access", return_value=False):
            output = await collect(
                stream_orchestrator(db_session, "tenant_test", "viewer", "Get churn")
            )

    events = parse_events(output)
    assert not [e for e in events if e.get("type") == "tool_result" and "data" in e]
    assert output[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_loop_is_bounded_by_max_agent_steps(db_session):
    """A model that keeps asking for tools must not spin forever."""
    from app.core.config import settings

    always_tool_use = MockFinalMessage(
        stop_reason="tool_use",
        content=[
            MockToolUseBlock("toolu_loop", "get_churn_rate", {"period": "last_month"})
        ],
    )

    calls = {"n": 0}

    def make_stream(*args, **kwargs):
        calls["n"] += 1
        return MockStream([], always_tool_use)

    with patch("app.streaming.sse.client.messages.stream", side_effect=make_stream):
        with patch("app.streaming.sse.execute_tool", return_value={"ok": True}):
            output = await collect(
                stream_orchestrator(db_session, "tenant_test", "admin", "loop forever")
            )

    assert calls["n"] == settings.max_agent_steps
    errors = [e for e in parse_events(output) if e.get("type") == "error"]
    assert errors, "expected an error event when the step limit is hit"
    assert output[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_tool_exception_does_not_leak_internals(db_session):
    first = MockFinalMessage(
        stop_reason="tool_use",
        content=[
            MockToolUseBlock("toolu_e", "get_churn_rate", {"period": "last_month"})
        ],
    )
    second = MockFinalMessage(stop_reason="end_turn")

    captured = []
    secret = "relation 'subscriptions' does not exist at /srv/app/internal.py"

    def make_stream(*args, **kwargs):
        captured.append(list(kwargs.get("messages") or []))
        return MockStream([], first) if len(captured) == 1 else MockStream([], second)

    with patch("app.streaming.sse.client.messages.stream", side_effect=make_stream):
        with patch("app.streaming.sse.execute_tool", side_effect=RuntimeError(secret)):
            output = await collect(
                stream_orchestrator(db_session, "tenant_test", "admin", "boom")
            )

    sent_back = json.dumps(captured[1][-1])
    assert secret not in sent_back, "internal error text must not reach the model"
    assert "could not be executed" in sent_back
    assert secret not in "".join(
        output
    ), "internal error text must not reach the client"


@pytest.mark.asyncio
async def test_invalid_tool_arguments_are_explained_to_the_model(db_session):
    """ValueError is our own validation message and is safe to pass through verbatim."""
    first = MockFinalMessage(
        stop_reason="tool_use",
        content=[MockToolUseBlock("toolu_v", "get_metric_trend", {"metric": "nope"})],
    )
    second = MockFinalMessage(stop_reason="end_turn")

    captured = []

    def make_stream(*args, **kwargs):
        captured.append(list(kwargs.get("messages") or []))
        return MockStream([], first) if len(captured) == 1 else MockStream([], second)

    with patch("app.streaming.sse.client.messages.stream", side_effect=make_stream):
        with patch(
            "app.streaming.sse.execute_tool",
            side_effect=ValueError("granularity must be one of day, week, month"),
        ):
            await collect(
                stream_orchestrator(db_session, "tenant_test", "admin", "bad args")
            )

    sent_back = json.dumps(captured[1][-1])
    assert "granularity must be one of" in sent_back
