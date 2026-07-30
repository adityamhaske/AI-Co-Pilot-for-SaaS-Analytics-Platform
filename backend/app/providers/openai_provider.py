"""OpenAI adapter (Chat Completions)."""

from collections.abc import AsyncIterator
from typing import Any

from app.core.config import settings
from app.providers.anthropic_provider import parse_arguments
from app.providers.base import (
    ChatProvider,
    ProviderError,
    ProviderEvent,
    TextChunk,
    ToolCall,
    ToolCallStarted,
    ToolSpec,
    Turn,
    TurnFinished,
    coerce_int,
)

DEFAULT_MODEL = "gpt-4.1"


def to_wire_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


def to_wire_messages(system: str, turns: list[Turn]) -> list[dict[str, Any]]:
    """Neutral turns to OpenAI's flat message list.

    Two shape differences from Anthropic matter. The system prompt is a message rather
    than a top-level parameter, and each tool result is its own `role: "tool"` message
    rather than blocks inside one user message.
    """
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]

    for turn in turns:
        if turn.role == "assistant":
            message: dict[str, Any] = {"role": "assistant"}
            # `content` must be present even when null, alongside tool_calls.
            message["content"] = turn.text or None
            if turn.tool_calls:
                message["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            # Arguments travel as a JSON string, not an object.
                            "arguments": _dump(call.arguments),
                        },
                    }
                    for call in turn.tool_calls
                ]
            if message["content"] or message.get("tool_calls"):
                messages.append(message)
            continue

        if turn.tool_results:
            for result in turn.tool_results:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": result.call_id,
                        "content": result.content,
                    }
                )
        elif turn.text:
            messages.append({"role": "user", "content": turn.text})

    return messages


def _dump(arguments: dict[str, Any]) -> str:
    import json

    return json.dumps(arguments, default=str)


def _stop_reason(raw: Any) -> str:
    return {
        "tool_calls": "tool_use",
        "function_call": "tool_use",
        "stop": "end_turn",
        "length": "max_tokens",
    }.get(str(raw), "other")


class OpenAIProvider(ChatProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:  # pragma: no cover - depends on the install
            raise ProviderError(
                "The 'openai' package is not installed. "
                "Install it with: pip install 'openai>=1.40'"
            ) from exc

        if not api_key:
            raise ProviderError("OPENAI_API_KEY is required for LLM_PROVIDER=openai")

        self.model = model
        self._client = AsyncOpenAI(
            api_key=api_key, timeout=settings.provider_timeout_seconds, max_retries=2
        )

    async def stream_turn(
        self,
        *,
        system: str,
        turns: list[Turn],
        tools: list[ToolSpec],
        max_tokens: int,
    ) -> AsyncIterator[ProviderEvent]:
        stream = await self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=to_wire_messages(system, turns),
            tools=to_wire_tools(tools) or None,
            stream=True,
            # Usage is omitted from streamed responses unless asked for.
            stream_options={"include_usage": True},
        )

        text_parts: list[str] = []
        # Unlike Anthropic, arguments arrive as string fragments that must be
        # accumulated, and the delta's `index` is the only thing that says which call a
        # fragment belongs to. Keying on it is what makes parallel calls work.
        pending: dict[int, dict[str, str]] = {}
        announced: set[int] = set()
        finish_reason: Any = None
        input_tokens = output_tokens = 0

        async for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                input_tokens = coerce_int(getattr(usage, "prompt_tokens", 0))
                output_tokens = coerce_int(getattr(usage, "completion_tokens", 0))

            for choice in getattr(chunk, "choices", None) or []:
                if getattr(choice, "finish_reason", None):
                    finish_reason = choice.finish_reason

                delta = getattr(choice, "delta", None)
                if delta is None:
                    continue

                content = getattr(delta, "content", None)
                if content:
                    text_parts.append(content)
                    yield TextChunk(content)

                for call_delta in getattr(delta, "tool_calls", None) or []:
                    index = coerce_int(getattr(call_delta, "index", 0))
                    slot = pending.setdefault(index, {"id": "", "name": "", "args": ""})

                    if getattr(call_delta, "id", None):
                        slot["id"] = call_delta.id
                    function = getattr(call_delta, "function", None)
                    if function is not None:
                        if getattr(function, "name", None):
                            slot["name"] = function.name
                        if getattr(function, "arguments", None):
                            slot["args"] += function.arguments

                    if slot["name"] and index not in announced:
                        announced.add(index)
                        yield ToolCallStarted(slot["name"])

        calls = [
            ToolCall(
                id=slot["id"] or f"call_{index}",
                name=slot["name"],
                arguments=parse_arguments(slot["args"]),
            )
            for index, slot in sorted(pending.items())
            if slot["name"]
        ]

        # A model can stop with "stop" while still having emitted tool calls; the calls
        # are what the loop must act on.
        reason = _stop_reason(finish_reason)
        if calls and reason != "tool_use":
            reason = "tool_use"

        yield TurnFinished(
            text="".join(text_parts),
            tool_calls=calls,
            stop_reason=reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
