"""Provider-neutral types for the agent loop.

The orchestrator used to speak Anthropic's wire format directly — its content blocks,
its `input_schema` key, its streaming event names. Swapping model provider meant
rewriting the loop.

Everything here is the format the loop actually reasons about. Each adapter in this
package translates to and from its provider's wire format, and translation is the only
place provider-specific knowledge lives. That translation is also the risky part, so it
is tested directly in `tests/test_providers.py`.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

StopReason = Literal["end_turn", "tool_use", "max_tokens", "other"]


@dataclass(frozen=True)
class ToolSpec:
    """A tool as the loop declares it. `parameters` is plain JSON Schema."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    """A model's request to run a tool, with arguments already parsed."""

    id: str
    name: str
    arguments: dict[str, Any]
    #: Opaque provider state that must be handed back verbatim on the next request.
    #: Gemini attaches a `thought_signature` to each function call and rejects a
    #: follow-up that replays the call without it. The loop never inspects this; only
    #: the adapter that produced it knows what it means.
    provider_state: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass
class Turn:
    """One conversational turn.

    An assistant turn may carry text, tool calls, or both. A user turn carries either
    text or the results of the tool calls the previous assistant turn requested.
    """

    role: Literal["user", "assistant"]
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


# --- streaming events -------------------------------------------------------


@dataclass(frozen=True)
class TextChunk:
    text: str


@dataclass(frozen=True)
class ToolCallStarted:
    """Emitted as soon as a tool call is recognised, for UI feedback."""

    name: str


@dataclass(frozen=True)
class TurnFinished:
    text: str
    tool_calls: list[ToolCall]
    stop_reason: StopReason
    input_tokens: int = 0
    output_tokens: int = 0


ProviderEvent = TextChunk | ToolCallStarted | TurnFinished


@runtime_checkable
class ChatProvider(Protocol):
    """What the agent loop needs from a model provider."""

    #: Short identifier, e.g. "anthropic". Used in logs and the /providers response.
    name: str
    #: The concrete model id in use.
    model: str

    def stream_turn(
        self,
        *,
        system: str,
        turns: list[Turn],
        tools: list[ToolSpec],
        max_tokens: int,
    ) -> AsyncIterator[ProviderEvent]:
        """Stream one assistant turn, ending with exactly one TurnFinished."""
        ...


class ProviderError(RuntimeError):
    """Configuration or availability problem with a provider. Fatal at startup."""


class ProviderCallFailed(ProviderError):
    """A request to the vendor failed mid-turn: a 5xx, a rate limit, a dropped socket.

    Separate from ProviderError because the cause is different in kind. A missing SDK or
    an absent key is a misconfiguration that will fail identically every time; this is
    weather. The distinction is what lets the eval suite retry one and not the other, and
    stops a transient network fault being reported as a wrong answer from the model.
    """


def coerce_int(value: Any) -> int:
    """Usage counters vary in type and presence across SDKs."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# Keys that appear in our JSON Schemas but that some providers reject. Gemini in
# particular accepts only a subset of OpenAPI schema and errors on unknown keys.
_SCHEMA_ALLOWED = {
    "type",
    "properties",
    "required",
    "items",
    "enum",
    "description",
    "nullable",
}


def strip_unsupported_schema_keys(schema: Any) -> Any:
    """Recursively drop schema keywords a strict provider will not accept.

    `format: date` is the one that matters here: it is informative for Anthropic and
    OpenAI but rejected by Gemini. Dropping it loses nothing, because the date strings
    are validated by Pydantic on the way in regardless.
    """
    if isinstance(schema, dict):
        cleaned: dict[str, Any] = {}
        for key, value in schema.items():
            if key not in _SCHEMA_ALLOWED:
                continue
            if key == "properties" and isinstance(value, dict):
                # The keys under `properties` are *property names*, chosen by whoever
                # wrote the tool, not schema keywords — filtering them would delete the
                # arguments themselves.
                cleaned[key] = {
                    name: strip_unsupported_schema_keys(sub)
                    for name, sub in value.items()
                }
            else:
                cleaned[key] = strip_unsupported_schema_keys(value)
        return cleaned
    if isinstance(schema, list):
        return [strip_unsupported_schema_keys(item) for item in schema]
    return schema
