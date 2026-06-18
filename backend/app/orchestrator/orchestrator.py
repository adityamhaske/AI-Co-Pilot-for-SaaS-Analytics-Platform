import anthropic
import json
from sqlalchemy.orm import Session
from app.core.config import settings
from app.orchestrator.tools import TOOLS
from app.validator.query_validator import execute_tool
from app.core.rbac import check_tool_access

client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

SYSTEM_PROMPT = """You are an AI co-pilot for a SaaS analytics dashboard.
Your job is to answer user queries by calling the provided tools.
You MUST ONLY answer using facts returned by tool calls. Do not invent data.
If you need a tool you do not have, apologize and state you cannot answer.
"""

async def run_orchestrator(db: Session, tenant_id: str, role: str, user_message: str):
    messages = [{"role": "user", "content": user_message}]
    
    # Filter tools based on RBAC
    allowed_tools = [t for t in TOOLS if check_tool_access(role, t["name"])]
    
    response = await client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=messages,
        tools=allowed_tools,
    )

    if response.stop_reason == "tool_use":
        tool_use = next(b for b in response.content if b.type == "tool_use")
        
        # Verify access again defensively
        if not check_tool_access(role, tool_use.name):
            tool_result_content = "Error: Unauthorized tool use."
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
        
        final_response = await client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=allowed_tools,
        )
        return final_response.content[0].text
    
    return response.content[0].text
