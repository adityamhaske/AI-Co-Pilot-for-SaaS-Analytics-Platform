"""The agent loop.

Driven through a fake provider rather than a mocked vendor SDK, so these assert the
loop's own behaviour — bounds, authorisation, error containment, one result per call —
independently of which model answers.
"""

import json
from unittest.mock import patch

import pytest

from app.providers import (
    ChatProvider,
    TextChunk,
    ToolCall,
    ToolCallStarted,
    Turn,
    TurnFinished,
)
from app.streaming.sse import stream_orchestrator

# ---------------------------------------------------------------------------
# Fake provider
# ---------------------------------------------------------------------------


class FakeProvider(ChatProvider):
    """Replays scripted turns and records what the loop sent it.

    `scripts` is a list of event lists, one per expected step. The last script repeats if
    the loop asks for more steps, which is how the bounded-loop test works.
    """

    name = "fake"
    model = "fake-1"

    def __init__(self, *scripts):
        self.scripts = list(scripts)
        self.calls = 0
        #: A copy of the turn list per call — the loop mutates its own list in place.
        self.seen_turns: list[list[Turn]] = []
        self.seen_tools: list[list[str]] = []

    async def stream_turn(self, *, system, turns, tools, max_tokens):
        self.seen_turns.append(list(turns))
        self.seen_tools.append([t.name for t in tools])
        script = self.scripts[min(self.calls, len(self.scripts) - 1)]
        self.calls += 1
        for event in script:
            yield event


def text_turn(text: str):
    return [
        TextChunk(text),
        TurnFinished(text=text, tool_calls=[], stop_reason="end_turn"),
    ]


def tool_turn(*calls: ToolCall, text: str = ""):
    events = [ToolCallStarted(c.name) for c in calls]
    events.append(
        TurnFinished(
            text=text,
            tool_calls=list(calls),
            stop_reason="tool_use",
            input_tokens=10,
            output_tokens=5,
        )
    )
    return events


async def collect(gen) -> list:
    return [chunk async for chunk in gen]


def parse_events(chunks: list) -> list:
    events = []
    for chunk in chunks:
        body = chunk.removeprefix("data: ").strip()
        if not body or body == "[DONE]":
            continue
        events.append(json.loads(body))
    return events


async def run(provider, db, role="admin", message="q", **kwargs):
    # The generator must be driven to completion *inside* the patch. Returning the
    # un-awaited coroutine let the patch exit first, and the loop then built a real
    # provider and made a real API call.
    with patch("app.streaming.sse.get_provider", return_value=provider):
        return await collect(
            stream_orchestrator(db, "tenant_test", role, message, **kwargs)
        )


# ---------------------------------------------------------------------------
# Basic streaming
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emits_token_events(db_session):
    provider = FakeProvider(text_turn("Here is your MRR trend."))
    output = await run(provider, db_session, "viewer", "What is my MRR?")

    tokens = [e for e in parse_events(output) if e.get("type") == "token"]
    assert tokens and "MRR trend" in tokens[0]["text"]


@pytest.mark.asyncio
async def test_stream_always_ends_with_done(db_session):
    output = await run(FakeProvider(text_turn("Hello!")), db_session)
    assert output[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_usage_reports_the_provider_and_model(db_session):
    provider = FakeProvider(
        [
            TurnFinished(
                text="",
                tool_calls=[],
                stop_reason="end_turn",
                input_tokens=42,
                output_tokens=7,
            )
        ]
    )
    output = await run(provider, db_session)

    usage = [e for e in parse_events(output) if e.get("type") == "usage"]
    assert usage == [
        {
            "type": "usage",
            "provider": "fake",
            "model": "fake-1",
            "input_tokens": 42,
            "output_tokens": 7,
        }
    ]


@pytest.mark.asyncio
async def test_the_model_is_only_offered_tools_its_role_permits(db_session):
    provider = FakeProvider(text_turn("ok"))
    await run(provider, db_session, "viewer")
    offered = provider.seen_tools[0]
    assert "list_active_alerts" not in offered
    assert "get_top_customers" not in offered
    assert "get_metric_trend" in offered


# ---------------------------------------------------------------------------
# Parallel tool calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_calls_each_get_their_own_result(db_session):
    """One result per call, in a single following turn.

    The original loop tracked the in-flight tool in scalar variables, so two calls left
    one result and a malformed request.
    """
    provider = FakeProvider(
        tool_turn(
            ToolCall(
                "c1", "get_metric_value", {"metric": "mrr", "period": "last_month"}
            ),
            ToolCall("c2", "get_top_customers", {"sort_by": "mrr", "limit": 3}),
        ),
        text_turn("Both are ready."),
    )

    with patch("app.orchestrator.tools.execute", return_value={"ok": True}):
        output = await run(provider, db_session)

    # The second request carries the results.
    results_turn = provider.seen_turns[1][-1]
    assert results_turn.role == "user"
    assert [r.call_id for r in results_turn.tool_results] == ["c1", "c2"]
    assert [r.name for r in results_turn.tool_results] == [
        "get_metric_value",
        "get_top_customers",
    ]
    assert output[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_parallel_calls_are_announced_individually(db_session):
    provider = FakeProvider(
        tool_turn(
            ToolCall("c1", "get_metric_value", {"metric": "mrr"}),
            ToolCall("c2", "get_top_customers", {"sort_by": "mrr", "limit": 3}),
        ),
        text_turn("done"),
    )
    with patch("app.orchestrator.tools.execute", return_value=[{"a": 1}]):
        output = await run(provider, db_session)

    names = [e["name"] for e in parse_events(output) if e.get("type") == "tool_call"]
    assert names == ["get_metric_value", "get_top_customers"]


@pytest.mark.asyncio
async def test_assistant_tool_calls_are_replayed_to_the_provider(db_session):
    """The follow-up request must include what the model asked for, or the pairing breaks."""
    provider = FakeProvider(
        tool_turn(
            ToolCall("c1", "get_metric_value", {"metric": "mrr"}), text="checking"
        ),
        text_turn("done"),
    )
    with patch("app.orchestrator.tools.execute", return_value={"value": 1}):
        await run(provider, db_session)

    assistant_turn = provider.seen_turns[1][-2]
    assert assistant_turn.role == "assistant"
    assert [c.id for c in assistant_turn.tool_calls] == ["c1"]


# ---------------------------------------------------------------------------
# Authorisation, bounds, error containment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthorized_tool_is_refused_without_running(db_session):
    provider = FakeProvider(
        tool_turn(ToolCall("c1", "list_active_alerts", {})),
        text_turn("I cannot access that."),
    )

    with patch("app.orchestrator.tools.execute") as execute:
        output = await run(provider, db_session, "viewer")

    execute.assert_not_called()
    results_turn = provider.seen_turns[1][-1]
    assert results_turn.tool_results[0].is_error
    assert "not permitted" in results_turn.tool_results[0].content
    # Nothing was pushed to the client as data.
    assert not [e for e in parse_events(output) if e.get("type") == "tool_result"]


@pytest.mark.asyncio
async def test_loop_is_bounded_by_max_agent_steps(db_session):
    """A model that keeps asking for tools must not spin forever."""
    from app.core.config import settings

    provider = FakeProvider(
        tool_turn(ToolCall("c", "get_metric_value", {"metric": "mrr"}))
    )

    with patch("app.orchestrator.tools.execute", return_value={"ok": True}):
        output = await run(provider, db_session)

    assert provider.calls == settings.max_agent_steps
    errors = [e for e in parse_events(output) if e.get("type") == "error"]
    assert errors and "Stopped after" in errors[0]["message"]
    assert output[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_tool_exception_does_not_leak_internals(db_session):
    provider = FakeProvider(
        tool_turn(ToolCall("c1", "get_metric_value", {"metric": "mrr"})),
        text_turn("sorry"),
    )
    secret = "relation 'subscriptions' does not exist at /srv/app/internal.py"

    with patch("app.orchestrator.tools.execute", side_effect=RuntimeError(secret)):
        output = await run(provider, db_session)

    sent_back = provider.seen_turns[1][-1].tool_results[0].content
    assert secret not in sent_back
    assert "could not be executed" in sent_back
    assert secret not in "".join(output)


@pytest.mark.asyncio
async def test_invalid_arguments_are_explained_to_the_model(db_session):
    """Our own validation messages are safe, and let the model correct itself."""
    provider = FakeProvider(
        tool_turn(ToolCall("c1", "get_metric_trend", {"metric": "nope"})),
        text_turn("retrying"),
    )

    with patch(
        "app.orchestrator.tools.execute",
        side_effect=ValueError("granularity must be one of day, week, month"),
    ):
        await run(provider, db_session)

    content = provider.seen_turns[1][-1].tool_results[0].content
    assert "granularity must be one of" in content


@pytest.mark.asyncio
async def test_provider_failure_surfaces_a_generic_error(db_session):
    class Exploding(FakeProvider):
        async def stream_turn(self, *, system, turns, tools, max_tokens):
            raise RuntimeError("api key sk-secret-123 rejected")
            yield  # pragma: no cover - unreachable, marks this a generator

    output = await run(Exploding(), db_session)
    body = "".join(output)
    assert "sk-secret-123" not in body
    assert "unexpected error" in body
    assert output[-1] == "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# History and persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_history_is_replayed_before_the_new_question(db_session):
    provider = FakeProvider(text_turn("ok"))
    history = [
        {"role": "user", "content": "What is my MRR?"},
        {"role": "assistant", "content": "It is 5600."},
    ]
    await run(provider, db_session, message="And churn?", history=history)

    turns = provider.seen_turns[0]
    assert [t.role for t in turns] == ["user", "assistant", "user"]
    assert turns[0].text == "What is my MRR?"
    assert turns[-1].text == "And churn?"


@pytest.mark.asyncio
async def test_on_complete_receives_answer_tools_and_usage(db_session):
    captured = {}

    def persist(answer, tools, usage):
        captured.update(answer=answer, tools=tools, usage=usage)

    provider = FakeProvider(
        tool_turn(ToolCall("c1", "get_metric_value", {"metric": "mrr"})),
        text_turn("Your MRR is 5600."),
    )
    with patch("app.orchestrator.tools.execute", return_value={"value": 5600}):
        await run(provider, db_session, on_complete=persist)

    assert "5600" in captured["answer"]
    assert [t["name"] for t in captured["tools"]] == ["get_metric_value"]
    assert captured["usage"]["input_tokens"] > 0


@pytest.mark.asyncio
async def test_wall_clock_deadline_stops_the_loop(db_session, monkeypatch):
    """agent_timeout_seconds was declared and never read, while the docs claimed it.

    Checked between steps, so a step already in flight completes and the answer so far is
    preserved — a hung single request is bounded by the SDK timeout instead.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "agent_timeout_seconds", 0.0)

    provider = FakeProvider(
        tool_turn(ToolCall("c", "get_metric_value", {"metric": "mrr"}), text="working")
    )
    with patch("app.orchestrator.tools.execute", return_value={"ok": True}):
        output = await run(provider, db_session)

    # One step ran, then the deadline stopped it — well short of max_agent_steps.
    assert provider.calls == 1
    errors = [e for e in parse_events(output) if e.get("type") == "error"]
    assert errors and "Stopped after" in errors[0]["message"]
    assert output[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_deadline_is_not_checked_before_the_first_step(db_session, monkeypatch):
    """A zero budget must still allow one attempt rather than answering nothing."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "agent_timeout_seconds", 0.0)

    provider = FakeProvider(text_turn("Answered on the first pass."))
    output = await run(provider, db_session)

    assert provider.calls == 1
    tokens = [e for e in parse_events(output) if e.get("type") == "token"]
    assert tokens
