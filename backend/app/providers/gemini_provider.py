"""Gemini adapter (google-genai)."""

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
    strip_unsupported_schema_keys,
)

# `gemini-2.5-pro` was the previous default and is now rejected for new API keys with
# "no longer available to new users" — it still appears in models.list(), so listing is
# not proof of access. The `-latest` aliases track Google's current generally-available
# model and do not go stale the same way. Override with LLM_MODEL.
DEFAULT_MODEL = "gemini-flash-latest"


def to_wire_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    """Gemini groups every function under one tool entry.

    Its schema dialect is a subset of OpenAPI, and unknown keywords are rejected rather
    than ignored — `format: date` in particular — so schemas are filtered first.
    """
    return [
        {
            "function_declarations": [
                {
                    "name": t.name,
                    "description": t.description,
                    "parameters": strip_unsupported_schema_keys(t.parameters),
                }
                for t in tools
            ]
        }
    ]


def to_wire_contents(turns: list[Turn]) -> list[dict[str, Any]]:
    """Neutral turns to Gemini `contents`.

    Three differences from the others: the assistant role is called "model", tool calls
    and results are *parts* inside a turn rather than separate fields or messages, and a
    function response is keyed by function *name* rather than by call id — so a
    provider-neutral call id cannot be round-tripped and is regenerated on the way back.
    """
    contents: list[dict[str, Any]] = []

    for turn in turns:
        parts: list[dict[str, Any]] = []

        if turn.role == "assistant":
            if turn.text:
                parts.append({"text": turn.text})
            for call in turn.tool_calls:
                part: dict[str, Any] = {
                    "function_call": {"name": call.name, "args": call.arguments}
                }
                # Gemini rejects a replayed function call whose thought_signature is
                # missing: "required for tools to work correctly". It is opaque bytes we
                # captured from the response and hand straight back.
                signature = (call.provider_state or {}).get("thought_signature")
                if signature:
                    part["thought_signature"] = signature
                parts.append(part)
            if parts:
                contents.append({"role": "model", "parts": parts})
            continue

        if turn.tool_results:
            for result in turn.tool_results:
                parts.append(
                    {
                        "function_response": {
                            "name": result.name,
                            # The response must be an object, so a plain string is wrapped.
                            "response": _as_object(result.content),
                        }
                    }
                )
        elif turn.text:
            parts.append({"text": turn.text})

        if parts:
            contents.append({"role": "user", "parts": parts})

    return contents


def _as_object(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except (TypeError, ValueError):
        return {"result": content}
    if isinstance(parsed, dict):
        return parsed
    return {"result": parsed}


def _stop_reason(raw: Any) -> str:
    """Map Gemini's finish reason onto the neutral vocabulary.

    The SDK hands back an enum, so `str()` yields "FinishReason.STOP" rather than "STOP".
    Reading `.name` first — and falling back to the text after the last dot — is what
    makes a normal completion report `end_turn` instead of `other`.
    """
    if raw is None:
        return "other"
    name = getattr(raw, "name", None) or str(raw).rsplit(".", 1)[-1]
    return {
        "STOP": "end_turn",
        "MAX_TOKENS": "max_tokens",
    }.get(name.upper(), "other")


class GeminiProvider(ChatProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - depends on the install
            raise ProviderError(
                "The 'google-genai' package is not installed. "
                "Install it with: pip install google-genai"
            ) from exc

        if not api_key:
            raise ProviderError("GEMINI_API_KEY is required for LLM_PROVIDER=gemini")

        self.model = model
        self._client = genai.Client(
            api_key=api_key,
            # google-genai takes the timeout in milliseconds.
            http_options={"timeout": int(settings.provider_timeout_seconds * 1000)},
        )

    async def stream_turn(
        self,
        *,
        system: str,
        turns: list[Turn],
        tools: list[ToolSpec],
        max_tokens: int,
    ) -> AsyncIterator[ProviderEvent]:
        stream = await self._client.aio.models.generate_content_stream(
            model=self.model,
            contents=to_wire_contents(turns),
            config={
                # The system prompt is configuration here, not a message.
                "system_instruction": system,
                "max_output_tokens": max_tokens,
                "tools": to_wire_tools(tools),
            },
        )

        text_parts: list[str] = []
        calls: list[ToolCall] = []
        announced: set[str] = set()
        finish_reason: Any = None
        input_tokens = output_tokens = 0

        async for chunk in stream:
            usage = getattr(chunk, "usage_metadata", None)
            if usage is not None:
                input_tokens = coerce_int(getattr(usage, "prompt_token_count", 0))
                output_tokens = coerce_int(getattr(usage, "candidates_token_count", 0))

            for candidate in getattr(chunk, "candidates", None) or []:
                if getattr(candidate, "finish_reason", None):
                    finish_reason = candidate.finish_reason

                content = getattr(candidate, "content", None)
                for part in getattr(content, "parts", None) or []:
                    text = getattr(part, "text", None)
                    if text:
                        text_parts.append(text)
                        yield TextChunk(text)

                    call = getattr(part, "function_call", None)
                    if call is not None and getattr(call, "name", None):
                        arguments = getattr(call, "args", None)
                        # Gemini has no call id, so one is synthesised. It only has to be
                        # unique within this turn for the loop to pair results correctly.
                        identifier = f"gemini_{call.name}_{len(calls)}"
                        signature = getattr(part, "thought_signature", None)
                        calls.append(
                            ToolCall(
                                id=identifier,
                                name=call.name,
                                arguments=dict(arguments) if arguments else {},
                                provider_state=(
                                    {"thought_signature": signature}
                                    if signature
                                    else None
                                ),
                            )
                        )
                        if call.name not in announced:
                            announced.add(call.name)
                            yield ToolCallStarted(call.name)

        reason = "tool_use" if calls else _stop_reason(finish_reason)

        yield TurnFinished(
            text="".join(text_parts),
            tool_calls=calls,
            stop_reason=reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
