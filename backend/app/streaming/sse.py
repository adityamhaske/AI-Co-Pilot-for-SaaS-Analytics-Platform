import json
from sqlalchemy.orm import Session
from app.orchestrator.tools import TOOLS
from app.validator.query_validator import execute_tool
from app.core.rbac import check_tool_access
from app.orchestrator.orchestrator import client, SYSTEM_PROMPT

async def stream_orchestrator(db: Session, tenant_id: str, role: str, user_message: str):
    messages = [{"role": "user", "content": user_message}]
    allowed_tools = [t for t in TOOLS if check_tool_access(role, t["name"])]
    
    # We loop to allow multiple sequential tool calls in a single turn.
    while True:
        # Buffer to accumulate tool_use arguments
        current_tool_id = None
        current_tool_name = None
        current_tool_input = ""
        async with client.messages.stream(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=allowed_tools,
        ) as stream:
            async for event in stream:
                if event.type == "text":
                    # Send text to user immediately
                    yield f"data: {json.dumps({'content': event.text})}\n\n"
                elif event.type == "content_block_start" and event.content_block.type == "tool_use":
                    current_tool_id = event.content_block.id
                    current_tool_name = event.content_block.name
                    current_tool_input = ""
                elif event.type == "content_block_delta" and event.delta.type == "input_json_delta":
                    current_tool_input += event.delta.partial_json
                elif event.type == "message_stop":
                    # Stream finished, check stop reason inside the block or wait after
                    pass
            
            # After stream completes, we can get the final message object to append to history
            final_message = await stream.get_final_message()
            messages.append({"role": "assistant", "content": final_message.content})

            if final_message.stop_reason == "tool_use":
                # Ensure we have parsed the input
                tool_input_dict = json.loads(current_tool_input) if current_tool_input else {}
                
                if not check_tool_access(role, current_tool_name):
                    tool_result_content = "Error: Unauthorized or missing tool use."
                else:
                    try:
                        tool_result = execute_tool(db, tenant_id, current_tool_name, tool_input_dict)
                        tool_result_content = json.dumps(tool_result)
                        
                        # Check if it should be charted
                        if isinstance(tool_result, list) or isinstance(tool_result, dict):
                            yield f"data: {json.dumps({'chart_data': tool_result, 'tool_name': current_tool_name})}\n\n"
                            
                    except Exception as e:
                        tool_result_content = f"Error executing tool: {str(e)}"
                
                messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": current_tool_id,
                            "content": tool_result_content,
                        }
                    ],
                })
                # Continue loop to send tool_result back to Claude
            else:
                # Stop reason was not tool_use, we are done
                break
                
    yield "data: [DONE]\n\n"
