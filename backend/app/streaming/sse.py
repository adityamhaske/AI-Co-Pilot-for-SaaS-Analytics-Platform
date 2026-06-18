import json
from sqlalchemy.orm import Session
from app.orchestrator.tools import TOOLS
from app.validator.query_validator import execute_tool
from app.core.rbac import check_tool_access
from app.orchestrator.orchestrator import client, SYSTEM_PROMPT

async def stream_orchestrator(db: Session, tenant_id: str, role: str, user_message: str):
    messages = [{"role": "user", "content": user_message}]
    allowed_tools = [t for t in TOOLS if check_tool_access(role, t["name"])]
    
    # First call - non-streaming to handle tool use
    response = await client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=messages,
        tools=allowed_tools,
    )

    if response.stop_reason == "tool_use":
        tool_use = next((b for b in response.content if b.type == "tool_use"), None)
        
        if not tool_use or not check_tool_access(role, tool_use.name):
            tool_result_content = "Error: Unauthorized or missing tool use."
        else:
            try:
                tool_result = execute_tool(db, tenant_id, tool_use.name, tool_use.input)
                tool_result_content = json.dumps(tool_result)
            except Exception as e:
                tool_result_content = f"Error executing tool: {str(e)}"
        
        messages.append({
            "role": "assistant",
            "content": response.content,
        })
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": tool_result_content,
                }
            ],
        })
        
        # Second call - stream the final answer
        async with client.messages.stream(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=allowed_tools,
        ) as stream:
            async for text in stream.text_stream:
                yield f"data: {json.dumps({'content': text})}\n\n"
        
        yield "data: [DONE]\n\n"
    else:
        # If no tool use, just yield the text content
        for block in response.content:
            if block.type == 'text':
                yield f"data: {json.dumps({'content': block.text})}\n\n"
        yield "data: [DONE]\n\n"
