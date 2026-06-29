import pytest
import json
from unittest.mock import patch
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


class MockFinalMessage:
    def __init__(self, stop_reason: str = "end_turn", content=None):
        self.stop_reason = stop_reason
        self.content = content or []


class MockStream:
    """Async context manager + async iterator that simulates client.messages.stream."""

    def __init__(self, events: list, final_message: MockFinalMessage):
        self._events = events
        self._final_message = final_message
        self._pos = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

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


async def collect(gen) -> list[str]:
    """Drive an async generator and collect all yielded strings."""
    results = []
    async for chunk in gen:
        results.append(chunk)
    return results


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_orchestrator_emits_content(db_session):
    """At least one data: line with a 'content' key should be emitted."""
    events = [MockEvent("text", text="Here is your MRR trend.")]
    final_msg = MockFinalMessage(stop_reason="end_turn")

    with patch(
        "app.streaming.sse.client.messages.stream",
        return_value=MockStream(events, final_msg),
    ):
        output = await collect(
            stream_orchestrator(db_session, "tenant_test", "viewer", "What is my MRR?")
        )

    content_lines = [
        line for line in output if "content" in line and line.startswith("data:")
    ]
    assert len(content_lines) >= 1, "Expected at least one data: content line"

    # Verify the text made it through
    data = json.loads(content_lines[0].removeprefix("data: ").strip())
    assert "content" in data
    assert "MRR trend" in data["content"]


@pytest.mark.asyncio
async def test_stream_orchestrator_ends_with_done(db_session):
    """The stream must always end with data: [DONE]."""
    events = [MockEvent("text", text="Hello!")]
    final_msg = MockFinalMessage(stop_reason="end_turn")

    with patch(
        "app.streaming.sse.client.messages.stream",
        return_value=MockStream(events, final_msg),
    ):
        output = await collect(
            stream_orchestrator(db_session, "tenant_test", "viewer", "Hello")
        )

    assert output[-1] == "data: [DONE]\n\n", f"Last chunk was: {output[-1]!r}"


@pytest.mark.asyncio
async def test_stream_orchestrator_unauthorized_tool_no_chart_data(db_session):
    """
    When a tool call is made for a tool the role cannot access:
    - no chart_data event should be emitted
    - the stream must still terminate cleanly with data: [DONE]
    """

    class MockContentBlock:
        type = "tool_use"
        id = "tool_unauthorized"
        name = "get_churn_rate"

    final_msg1 = MockFinalMessage(
        stop_reason="tool_use",
        content=[MockContentBlock()],
    )
    # After the error tool_result, Claude ends the turn
    events2 = [MockEvent("text", text="I cannot access that tool.")]
    final_msg2 = MockFinalMessage(stop_reason="end_turn")

    call_count = 0

    def make_stream(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return MockStream([], final_msg1)
        return MockStream(events2, final_msg2)

    with patch("app.streaming.sse.client.messages.stream", side_effect=make_stream):
        # Patch check_tool_access so the tool is always denied
        with patch("app.streaming.sse.check_tool_access", return_value=False):
            output = await collect(
                stream_orchestrator(
                    db_session, "tenant_test", "viewer", "Get churn rate"
                )
            )

    chart_lines = [line for line in output if "chart_data" in line]
    assert len(chart_lines) == 0, "No chart_data event expected for unauthorized tool"
    assert output[-1] == "data: [DONE]\n\n", "Stream must end with [DONE]"
