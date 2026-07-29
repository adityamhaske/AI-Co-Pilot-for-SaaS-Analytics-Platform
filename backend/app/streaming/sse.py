import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import structlog
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.rbac import check_tool_access
from app.orchestrator.orchestrator import SYSTEM_PROMPT, client
from app.orchestrator.tools import TOOLS
from app.validator.query_validator import execute_tool

logger = structlog.get_logger()

MODEL = "claude-sonnet-4-6"

# Tool results that render as a chart in the UI. Everything else is returned to the model
# but not pushed to the client as chart data.
CHARTABLE_TOOLS = {
    "get_metric_trend",
    "compare_segments",
    "get_top_customers",
}


def _event(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _as_int(value: Any) -> int:
    """Coerce a usage counter to int, tolerating absent or non-numeric values."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _collect_tool_uses(final_message) -> list[Any]:
    """Return every tool_use block in the assistant message, in order.

    Reading the blocks off the assembled final message rather than accumulating
    `input_json_delta` fragments is what makes parallel tool calls work. The SDK has
    already reassembled and parsed each block's `input` by this point, so there is no
    partial-JSON state to track and no way for fragments from different blocks to be
    concatenated into one corrupt string.
    """
    content = getattr(final_message, "content", None) or []
    return [block for block in content if getattr(block, "type", None) == "tool_use"]


async def _run_tool(db: Session, tenant_id: str, name: str, tool_input: dict) -> Any:
    # execute_tool is synchronous SQLAlchemy. Calling it directly from this async
    # generator would block the event loop for every concurrent request, not just this
    # one. The threadpool keeps the loop free while the query runs.
    return await run_in_threadpool(execute_tool, db, tenant_id, name, tool_input)


async def stream_orchestrator(
    db: Session, tenant_id: str, role: str, user_message: str
) -> AsyncIterator[str]:
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]
    allowed_tools = [t for t in TOOLS if check_tool_access(role, t["name"])]

    total_input_tokens = 0
    total_output_tokens = 0

    try:
        # Bounded, unlike the previous `while True`. Without a ceiling a model that keeps
        # requesting tools drives unbounded API spend and holds the connection open
        # indefinitely, on the caller's say-so.
        for step in range(settings.max_agent_steps):
            emitted_calls: set = set()

            async with client.messages.stream(
                model=MODEL,
                max_tokens=settings.max_tokens_per_turn,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=allowed_tools,
            ) as stream:
                async for event in stream:
                    etype = getattr(event, "type", None)

                    if etype == "text":
                        yield _event({"type": "token", "text": event.text})

                    elif etype == "content_block_start":
                        block = getattr(event, "content_block", None)
                        if getattr(block, "type", None) == "tool_use":
                            # Keyed by content-block index so parallel calls announce
                            # themselves individually rather than overwriting each other.
                            idx = getattr(event, "index", None)
                            if idx not in emitted_calls:
                                emitted_calls.add(idx)
                                yield _event({"type": "tool_call", "name": block.name})

                final_message = await stream.get_final_message()

            usage = getattr(final_message, "usage", None)
            if usage is not None:
                total_input_tokens += _as_int(getattr(usage, "input_tokens", 0))
                total_output_tokens += _as_int(getattr(usage, "output_tokens", 0))

            messages.append({"role": "assistant", "content": final_message.content})

            if getattr(final_message, "stop_reason", None) != "tool_use":
                break

            tool_uses = _collect_tool_uses(final_message)
            if not tool_uses:
                # stop_reason said tool_use but no block was present. Nothing sensible to
                # send back; ending the turn beats looping forever on an empty request.
                logger.warning("tool_use_without_block", step=step)
                break

            # Every tool_use block must get a matching tool_result in a single user
            # message, or the next request is rejected as malformed.
            results: list[dict[str, Any]] = []
            for block in tool_uses:
                tool_input = block.input if isinstance(block.input, dict) else {}

                if not check_tool_access(role, block.name):
                    logger.warning(
                        "tool_access_denied",
                        tool=block.name,
                        role=role,
                        tenant_id=tenant_id,
                    )
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "Error: your role is not permitted to use this tool.",
                            "is_error": True,
                        }
                    )
                    continue

                try:
                    result = await _run_tool(db, tenant_id, block.name, tool_input)
                except ValueError as exc:
                    # Argument-validation failures. These messages are written by us and
                    # are safe to surface — telling the model *why* the call was rejected
                    # lets it correct the arguments on the next step.
                    logger.info(
                        "tool_arguments_rejected", tool=block.name, error=str(exc)
                    )
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"Invalid arguments: {exc}",
                            "is_error": True,
                        }
                    )
                    continue
                except Exception as exc:
                    # The exception text can carry SQL, column names and internal paths.
                    # Log it in full; hand the model and the user a generic message.
                    logger.exception(
                        "tool_execution_failed",
                        tool=block.name,
                        tenant_id=tenant_id,
                        error=str(exc),
                    )
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"Error: {block.name} could not be executed.",
                            "is_error": True,
                        }
                    )
                    continue

                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str),
                    }
                )

                if block.name in CHARTABLE_TOOLS and isinstance(result, (list, dict)):
                    yield _event(
                        {
                            "type": "tool_result",
                            "name": block.name,
                            "input": tool_input,
                            "data": result,
                        }
                    )

            messages.append({"role": "user", "content": results})
        else:
            # Loop exhausted without the model finishing. Say so rather than truncating
            # silently, so the user knows the answer may be incomplete.
            logger.warning(
                "agent_step_limit_reached",
                limit=settings.max_agent_steps,
                tenant_id=tenant_id,
            )
            yield _event(
                {
                    "type": "error",
                    "message": (
                        f"Stopped after {settings.max_agent_steps} tool-calling steps. "
                        "Try asking a narrower question."
                    ),
                }
            )

    except asyncio.CancelledError:
        # The client disconnected. Let the cancellation propagate so the upstream request
        # is torn down instead of billing for tokens nobody will read.
        logger.info("stream_cancelled", tenant_id=tenant_id)
        raise
    except Exception as exc:
        logger.exception("stream_failed", tenant_id=tenant_id, error=str(exc))
        yield _event(
            {"type": "error", "message": "The assistant hit an unexpected error."}
        )
    else:
        yield _event(
            {
                "type": "usage",
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
            }
        )

    yield "data: [DONE]\n\n"
