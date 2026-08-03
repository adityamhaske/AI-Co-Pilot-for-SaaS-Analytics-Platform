"""Provider wire-format translation.

Translation is where a multi-provider agent loop actually breaks: each vendor names the
argument schema differently, carries tool results in a different place, and represents
call ids differently. These assert the exact shapes, because a translation bug shows up
as a confusing API rejection rather than a clear failure.

No network calls — only the pure conversion functions.
"""

import json

import pytest

from app.providers import pricing_for
from app.providers.anthropic_provider import parse_arguments
from app.providers.anthropic_provider import to_wire_messages as anthropic_messages
from app.providers.anthropic_provider import to_wire_tools as anthropic_tools
from app.providers.base import (
    ToolCall,
    ToolResult,
    ToolSpec,
    Turn,
    strip_unsupported_schema_keys,
)
from app.providers.gemini_provider import to_wire_contents as gemini_contents
from app.providers.gemini_provider import to_wire_tools as gemini_tools
from app.providers.openai_provider import to_wire_messages as openai_messages
from app.providers.openai_provider import to_wire_tools as openai_tools

SPEC = ToolSpec(
    name="get_metric_trend",
    description="Return a time series.",
    parameters={
        "type": "object",
        "properties": {
            "metric": {"type": "string", "enum": ["mrr", "arr"]},
            "start_date": {"type": "string", "format": "date"},
        },
        "required": ["metric", "start_date"],
    },
)

CONVERSATION = [
    Turn(role="user", text="What is my MRR?"),
    Turn(
        role="assistant",
        text="Let me check.",
        tool_calls=[
            ToolCall(id="c1", name="get_metric_value", arguments={"metric": "mrr"}),
            ToolCall(id="c2", name="get_metric_value", arguments={"metric": "arr"}),
        ],
    ),
    Turn(
        role="user",
        tool_results=[
            ToolResult(
                call_id="c1", name="get_metric_value", content='{"value": 5600}'
            ),
            ToolResult(
                call_id="c2", name="get_metric_value", content='{"value": 67200}'
            ),
        ],
    ),
]


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------


def test_anthropic_uses_input_schema():
    wire = anthropic_tools([SPEC])[0]
    assert set(wire) == {"name", "description", "input_schema"}
    assert wire["input_schema"] == SPEC.parameters


def test_openai_nests_under_function():
    wire = openai_tools([SPEC])[0]
    assert wire["type"] == "function"
    assert set(wire["function"]) == {"name", "description", "parameters"}
    assert wire["function"]["parameters"] == SPEC.parameters


def test_gemini_groups_all_functions_under_one_tool():
    wire = gemini_tools([SPEC, SPEC])
    assert len(wire) == 1
    assert len(wire[0]["function_declarations"]) == 2


def test_gemini_strips_schema_keywords_it_rejects():
    """Gemini errors on unknown schema keywords rather than ignoring them."""
    params = gemini_tools([SPEC])[0]["function_declarations"][0]["parameters"]
    assert "format" not in json.dumps(params)
    # The parts that carry meaning survive.
    assert params["properties"]["metric"]["enum"] == ["mrr", "arr"]
    assert params["required"] == ["metric", "start_date"]


def test_other_providers_keep_format():
    assert "format" in json.dumps(anthropic_tools([SPEC]))
    assert "format" in json.dumps(openai_tools([SPEC]))


def test_schema_stripper_is_recursive():
    nested = {
        "type": "object",
        "format": "drop-me",
        "properties": {
            "a": {"type": "array", "items": {"type": "string", "format": "x"}}
        },
    }
    cleaned = strip_unsupported_schema_keys(nested)
    assert "format" not in json.dumps(cleaned)
    assert cleaned["properties"]["a"]["items"]["type"] == "string"


# ---------------------------------------------------------------------------
# Conversation shape
# ---------------------------------------------------------------------------


def test_anthropic_pairs_every_tool_use_with_a_result():
    wire = anthropic_messages(CONVERSATION)
    assistant = next(m for m in wire if m["role"] == "assistant")
    tool_uses = [b for b in assistant["content"] if b["type"] == "tool_use"]

    results_message = wire[-1]
    result_ids = [b["tool_use_id"] for b in results_message["content"]]

    assert [b["id"] for b in tool_uses] == ["c1", "c2"]
    # One user message holding both results, ids matching the calls.
    assert results_message["role"] == "user"
    assert result_ids == ["c1", "c2"]


def test_openai_puts_the_system_prompt_in_the_message_list():
    wire = openai_messages("You are a co-pilot.", CONVERSATION)
    assert wire[0] == {"role": "system", "content": "You are a co-pilot."}


def test_openai_emits_one_tool_message_per_result():
    wire = openai_messages("sys", CONVERSATION)
    tool_messages = [m for m in wire if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == ["c1", "c2"]


def test_openai_serialises_arguments_as_a_json_string():
    wire = openai_messages("sys", CONVERSATION)
    assistant = next(m for m in wire if m["role"] == "assistant")
    raw = assistant["tool_calls"][0]["function"]["arguments"]
    assert isinstance(raw, str)
    assert json.loads(raw) == {"metric": "mrr"}


def test_gemini_renames_the_assistant_role_to_model():
    wire = gemini_contents(CONVERSATION)
    assert [c["role"] for c in wire] == ["user", "model", "user"]


def test_gemini_carries_calls_and_results_as_parts():
    wire = gemini_contents(CONVERSATION)
    model_parts = wire[1]["parts"]
    assert any("text" in p for p in model_parts)
    assert [
        p["function_call"]["name"] for p in model_parts if "function_call" in p
    ] == [
        "get_metric_value",
        "get_metric_value",
    ]

    result_parts = wire[2]["parts"]
    # Keyed by function name, not call id — Gemini has no id to round-trip.
    assert result_parts[0]["function_response"]["name"] == "get_metric_value"
    assert result_parts[0]["function_response"]["response"] == {"value": 5600}


def test_gemini_wraps_a_non_object_result():
    """A function response must be an object, so a bare string is wrapped."""
    turns = [
        Turn(
            role="user",
            tool_results=[ToolResult(call_id="c", name="t", content="plain text")],
        )
    ]
    response = gemini_contents(turns)[0]["parts"][0]["function_response"]["response"]
    assert response == {"result": "plain text"}


def test_empty_turns_are_dropped_not_emitted_blank():
    """A blank message is rejected by every provider."""
    turns = [Turn(role="assistant", text=""), Turn(role="user", text="hello")]
    assert len(anthropic_messages(turns)) == 1
    assert len(gemini_contents(turns)) == 1
    # OpenAI keeps the system message plus the one real turn.
    assert len(openai_messages("sys", turns)) == 2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_parse_arguments_tolerates_both_shapes():
    assert parse_arguments({"a": 1}) == {"a": 1}
    assert parse_arguments('{"a": 1}') == {"a": 1}
    assert parse_arguments("") == {}
    assert parse_arguments(None) == {}
    # Malformed JSON must not raise into the agent loop.
    assert parse_arguments("{not json") == {}
    # A JSON scalar is not arguments.
    assert parse_arguments("42") == {}


@pytest.mark.parametrize("provider", ["anthropic", "openai", "gemini"])
def test_every_provider_is_priced(provider):
    input_rate, output_rate = pricing_for(provider)
    assert input_rate > 0 and output_rate > 0


def test_unknown_provider_falls_back_to_the_priciest_known_rate():
    """Under-metering spend is worse than over-metering it."""
    assert pricing_for("some-new-vendor") == (3.00, 15.00)


# ---------------------------------------------------------------------------
# Retryability
#
# The first live OpenAI call returned 429 insufficient_quota. The eval runner retried it
# twice, because every provider error was treated as weather. An exhausted quota is not
# weather — waiting changes nothing, and the retries only delayed the same failure.
# ---------------------------------------------------------------------------


class Status(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


@pytest.mark.parametrize(
    ("exc", "retryable"),
    [
        # The exact error the live OpenAI key produced.
        (Status("Error code: 429 - {'code': 'insufficient_quota'}", 429), False),
        (Status("You exceeded your current quota, please check your plan", 429), False),
        (Status("Incorrect API key provided", 401), False),
        (Status("model_not_found", 404), False),
        (Status("gemini-2.5-pro is no longer available to new users", 404), False),
        # Weather.
        (Status("Rate limit reached, please slow down", 429), True),
        (Status("Internal server error", 500), True),
        (Status("Bad gateway", 502), True),
        (Status("Request timed out", 408), True),
        # No status at all — a dropped socket. Assumed transient on purpose.
        (ConnectionResetError("Connection reset by peer"), True),
        (Exception("something unlabelled went wrong"), True),
        # A 4xx that is not one of the known-permanent shapes still is not retried.
        (Status("Bad request: schema rejected", 400), False),
    ],
)
def test_provider_errors_are_classified_by_whether_a_retry_could_help(exc, retryable):
    from app.providers import is_retryable_provider_error

    assert is_retryable_provider_error(exc) is retryable


def test_permanent_markers_beat_a_retryable_status_code():
    """429 alone says retry; 429 plus an exhausted quota does not."""
    from app.providers import is_retryable_provider_error

    assert is_retryable_provider_error(Status("insufficient_quota", 429)) is False
    assert is_retryable_provider_error(Status("rate_limit_exceeded", 429)) is True
