"""The agent loop, streamed to the browser as Server-Sent Events.

Provider-neutral: it speaks the types in `app/providers/base.py` and never touches a
vendor SDK. Swapping Anthropic for OpenAI or Gemini is a configuration change.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import structlog
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.rbac import check_tool_access
from app.orchestrator import tools as toolbox
from app.orchestrator.prompts import SYSTEM_PROMPT
from app.providers import (
    TextChunk,
    ToolCallStarted,
    ToolResult,
    Turn,
    TurnFinished,
    get_provider,
)

logger = structlog.get_logger()


def _event(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def _run_tool(
    db: Session, tenant_id: str, role: str, name: str, tool_input: dict
) -> Any:
    # Tool execution is synchronous SQLAlchemy. Calling it directly from this async
    # generator would block the event loop for every concurrent request, not just this
    # one. The threadpool keeps the loop free while the query runs.
    return await run_in_threadpool(
        toolbox.execute, db, tenant_id, role, name, tool_input
    )


async def stream_orchestrator(
    db: Session,
    tenant_id: str,
    role: str,
    user_message: str,
    history: list[dict[str, Any]] | None = None,
    on_complete: Callable[[str, list[dict], dict], None] | None = None,
) -> AsyncIterator[str]:
    """Stream one assistant turn.

    `history` is the prior conversation, replayed so follow-up questions resolve.
    `on_complete` receives the assembled answer, the tools that produced it, and the
    token usage — the caller uses it to persist the turn once the stream has finished.
    """
    provider = get_provider()

    turns: list[Turn] = [
        Turn(role=t["role"], text=t["content"]) for t in (history or [])
    ]
    turns.append(Turn(role="user", text=user_message))

    # Schemas are generated per role: the model is never shown a tool — or a metric
    # inside a tool's enum — that this caller is not permitted to use.
    allowed_tools = toolbox.specs_for(role)

    total_input_tokens = 0
    total_output_tokens = 0
    answer_parts: list[str] = []
    executed_tools: list[dict] = []

    try:
        # Bounded, unlike the original `while True`. Without a ceiling a model that keeps
        # requesting tools drives unbounded API spend and holds the connection open
        # indefinitely, on the caller's say-so.
        for step in range(settings.max_agent_steps):
            finished: TurnFinished | None = None

            async for event in provider.stream_turn(
                system=SYSTEM_PROMPT,
                turns=turns,
                tools=allowed_tools,
                max_tokens=settings.max_tokens_per_turn,
            ):
                if isinstance(event, TextChunk):
                    answer_parts.append(event.text)
                    yield _event({"type": "token", "text": event.text})
                elif isinstance(event, ToolCallStarted):
                    yield _event({"type": "tool_call", "name": event.name})
                elif isinstance(event, TurnFinished):
                    finished = event

            if finished is None:
                logger.warning("provider_finished_without_summary", step=step)
                break

            total_input_tokens += finished.input_tokens
            total_output_tokens += finished.output_tokens

            turns.append(
                Turn(
                    role="assistant",
                    text=finished.text,
                    tool_calls=finished.tool_calls,
                )
            )

            if not finished.tool_calls:
                break

            # Every tool call must get a matching result, or the next request is
            # malformed. This is one result per call, in one following user turn.
            results: list[ToolResult] = []
            for call in finished.tool_calls:
                if not check_tool_access(role, call.name):
                    logger.warning(
                        "tool_access_denied",
                        tool=call.name,
                        role=role,
                        tenant_id=tenant_id,
                    )
                    results.append(
                        ToolResult(
                            call_id=call.id,
                            name=call.name,
                            content="Error: your role is not permitted to use this tool.",
                            is_error=True,
                        )
                    )
                    continue

                try:
                    result = await _run_tool(
                        db, tenant_id, role, call.name, call.arguments
                    )
                except ValueError as exc:
                    # Argument-validation failures. These messages are written by us and
                    # are safe to surface — telling the model *why* a call was rejected
                    # lets it correct the arguments on the next step.
                    logger.info(
                        "tool_arguments_rejected", tool=call.name, error=str(exc)
                    )
                    results.append(
                        ToolResult(
                            call_id=call.id,
                            name=call.name,
                            content=f"Invalid arguments: {exc}",
                            is_error=True,
                        )
                    )
                    continue
                except Exception as exc:
                    # The exception text can carry SQL, column names and internal paths.
                    # Log it in full; hand the model and the user a generic message.
                    logger.exception(
                        "tool_execution_failed",
                        tool=call.name,
                        tenant_id=tenant_id,
                        error=str(exc),
                    )
                    results.append(
                        ToolResult(
                            call_id=call.id,
                            name=call.name,
                            content=f"Error: {call.name} could not be executed.",
                            is_error=True,
                        )
                    )
                    continue

                results.append(
                    ToolResult(
                        call_id=call.id,
                        name=call.name,
                        content=json.dumps(result, default=str),
                    )
                )

                # Every successful result is pushed to the client, not just the chartable
                # ones: the UI shows the arguments and the returned rows under each
                # answer so a number can be checked rather than taken on trust.
                if isinstance(result, (list, dict)):
                    executed_tools.append(
                        {"name": call.name, "input": call.arguments, "data": result}
                    )
                    yield _event(
                        {
                            "type": "tool_result",
                            "name": call.name,
                            "input": call.arguments,
                            "data": result,
                        }
                    )

            turns.append(Turn(role="user", tool_results=results))
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
        logger.exception(
            "stream_failed",
            tenant_id=tenant_id,
            provider=provider.name,
            error=str(exc),
        )
        yield _event(
            {"type": "error", "message": "The assistant hit an unexpected error."}
        )
    else:
        yield _event(
            {
                "type": "usage",
                "provider": provider.name,
                "model": provider.model,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
            }
        )

    # Persist whatever the turn produced, including a partial answer after an error —
    # losing a half-written response is worse than storing it.
    if on_complete is not None:
        try:
            on_complete(
                "".join(answer_parts),
                executed_tools,
                {
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                },
            )
        except Exception as exc:
            logger.exception("persist_turn_failed", tenant_id=tenant_id, error=str(exc))

    yield "data: [DONE]\n\n"
