"""Anthropic adapter."""

import json
from collections.abc import AsyncIterator
from typing import Any

from app.core.config import settings
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

DEFAULT_MODEL = "claude-sonnet-4-6"


def to_wire_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {"name": t.name, "description": t.description, "input_schema": t.parameters}
        for t in tools
    ]


def to_wire_messages(turns: list[Turn]) -> list[dict[str, Any]]:
    """Neutral turns to Anthropic's content-block format.

    Every tool_use block must be answered by a tool_result block carrying the same id,
    in a single following user message, or the API rejects the request.
    """
    messages: list[dict[str, Any]] = []

    for turn in turns:
        if turn.role == "assistant":
            blocks: list[dict[str, Any]] = []
            if turn.text:
                blocks.append({"type": "text", "text": turn.text})
            for call in turn.tool_calls:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.id,
                        "name": call.name,
                        "input": call.arguments,
                    }
                )
            if blocks:
                messages.append({"role": "assistant", "content": blocks})
            continue

        if turn.tool_results:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": r.call_id,
                            "content": r.content,
                            **({"is_error": True} if r.is_error else {}),
                        }
                        for r in turn.tool_results
                    ],
                }
            )
        elif turn.text:
            messages.append({"role": "user", "content": turn.text})

    return messages


def _stop_reason(raw: Any) -> str:
    return {
        "tool_use": "tool_use",
        "end_turn": "end_turn",
        "max_tokens": "max_tokens",
    }.get(str(raw), "other")


class AnthropicProvider(ChatProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - depends on the install
            raise ProviderError(
                "The 'anthropic' package is not installed. "
                "Install it with: pip install anthropic"
            ) from exc

        if not api_key:
            raise ProviderError(
                "ANTHROPIC_API_KEY is required for LLM_PROVIDER=anthropic"
            )

        self.model = model
        # A per-request timeout is the only thing that bounds a hung provider call.
        # Wrapping the agent loop in asyncio.timeout cannot do this job: the loop is an
        # async generator, so when the deadline fires it is usually suspended at a yield
        # and the cancellation lands on the consumer instead.
        self._client = anthropic.AsyncAnthropic(
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
        announced: set[int] = set()

        async with self._client.messages.stream(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=to_wire_messages(turns),
            tools=to_wire_tools(tools),
        ) as stream:
            async for event in stream:
                kind = getattr(event, "type", None)

                if kind == "text":
                    yield TextChunk(event.text)

                elif kind == "content_block_start":
                    block = getattr(event, "content_block", None)
                    if getattr(block, "type", None) == "tool_use":
                        # Keyed by content-block index so parallel calls each announce
                        # themselves rather than overwriting one another.
                        index = getattr(event, "index", None)
                        if index not in announced:
                            announced.add(index)
                            yield ToolCallStarted(block.name)

            final = await stream.get_final_message()

        # Tool calls are read off the assembled message, not accumulated from
        # input_json_delta fragments: the SDK has already parsed each block's input, so
        # there is no partial-JSON state to track and no way for fragments from
        # different blocks to be concatenated into one corrupt string.
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for block in getattr(final, "content", None) or []:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                text_parts.append(block.text)
            elif block_type == "tool_use":
                arguments = block.input if isinstance(block.input, dict) else {}
                calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=arguments)
                )

        usage = getattr(final, "usage", None)
        yield TurnFinished(
            text="".join(text_parts),
            tool_calls=calls,
            stop_reason=_stop_reason(getattr(final, "stop_reason", None)),
            input_tokens=coerce_int(getattr(usage, "input_tokens", 0)),
            output_tokens=coerce_int(getattr(usage, "output_tokens", 0)),
        )


def parse_arguments(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    """Shared helper: tolerate a provider handing back arguments as a JSON string."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
