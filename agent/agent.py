"""CampusMate Agent module.

Acts as a client to the self-hosted MCP Server:
- Communicates strictly via official MCP protocol over Streamable HTTP (Non-Negotiable Principle 2)
- Discovers tools dynamically via tools/list
- Executes tool calls via tools/call with Bearer token authentication
- Manages LLM tool-calling loop with guards:
  * Maximum 6 iterations
  * Per-call timeout (15s)
  * Tool allow-list guard
  * Prompt-injection defense (treats outputs as data)
- Streams real-time execution events for SSE:
  * tool_started
  * tool_result
  * final_answer
  * error
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, AsyncGenerator, Dict, List, Optional
from dotenv import load_dotenv
import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from campusmate.agent.prompts import get_system_prompt

load_dotenv()

DEFAULT_MCP_SERVER_URL = "http://127.0.0.1:8000/mcp"
MAX_ITERATIONS = 6
PER_CALL_TIMEOUT_SECONDS = 15.0


class AgentError(Exception):
    """Raised when agent execution fails."""
    pass


def mcp_tools_to_openai_schema(mcp_tools: List[Any]) -> List[Dict[str, Any]]:
    """Convert MCP tool specifications to OpenAI function calling definitions."""
    tools = []
    for tool in mcp_tools:
        schema = tool.inputSchema if hasattr(tool, "inputSchema") and tool.inputSchema else {"type": "object", "properties": {}}
        tools.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": schema,
            },
        })
    return tools


def simulate_tool_selection_for_query(query: str, available_tools: set[str]) -> Optional[Dict[str, Any]]:
    """Deterministic intent router for testing/scripted evals without requiring live API keys.

    Enables reliable offline evaluations with expected tool sequences.
    """
    q = query.lower()

    # 1. Prepare day / daily plan
    if "prepare" in q or "plan my day" in q or "plan today" in q or "my day" in q:
        if "prepare_my_day" in available_tools:
            date_val = "2026-10-13" if "tomorrow" in q else "2026-10-12"
            mode_val = "tomorrow_preview" if "tomorrow" in q else "today"
            return {"name": "prepare_my_day", "arguments": {"date": date_val, "mode": mode_val}}

    # 2. Attendance & skip checks (checked before general class queries)
    if "attendance" in q or "skip" in q or "miss" in q or "absent" in q or "bunk" in q:
        if "get_attendance" in available_tools:
            subj = (
                "Operating Systems" if "os" in q or "operating" in q else (
                    "Database Systems" if "database" in q or "db" in q else (
                        "Circuit Analysis" if "circuit" in q else (
                            "Electromagnetics" if "electro" in q else None
                        )
                    )
                )
            )
            args = {"subject": subj} if subj else {}
            return {"name": "get_attendance", "arguments": args}

    # 3. Classroom directions / locations
    if "where" in q or "room" in q or "direction" in q or "find" in q or "location" in q:
        if "find_classroom" in available_tools:
            subj = "Database Systems" if "database" in q else (
                "Operating Systems" if "os" in q or "operating" in q else (
                    "Computer Networks" if "network" in q else (
                        "Circuit Analysis" if "circuit" in q else "Database Systems"
                    )
                )
            )
            return {"name": "find_classroom", "arguments": {"subject": subj}}

    # 4. Class schedules & timetable
    if "class" in q or "schedule" in q or "timetable" in q or "lecture" in q:
        if "get_timetable" in available_tools:
            date_val = "2026-10-13" if "tomorrow" in q else ("2026-10-16" if "friday" in q else "2026-10-12")
            return {"name": "get_timetable", "arguments": {"date": date_val}}

    # 5. Assignments & homework
    if "assignment" in q or "homework" in q or "due" in q or "pending" in q or "overdue" in q:
        if "get_assignments" in available_tools:
            status = "overdue" if "overdue" in q else ("all" if "all" in q else "pending")
            return {"name": "get_assignments", "arguments": {"status": status}}

    # 6. Free slots & open time
    if "free" in q or "slot" in q or "gap" in q or "break" in q:
        if "get_free_slots" in available_tools:
            date_val = "2026-10-16" if "friday" in q else "2026-10-12"
            return {"name": "get_free_slots", "arguments": {"date": date_val}}

    # 7. Exams & midterms
    if "exam" in q or "midterm" in q or "test" in q:
        if "get_exams" in available_tools:
            return {"name": "get_exams", "arguments": {}}

    # 8. Campus facilities (Library, Canteen, Lab)
    if "facility" in q or "facilities" in q or "library" in q or "canteen" in q or "cafeteria" in q or "lab" in q:
        if "get_facility_info" in available_tools:
            name_val = "Library" if "library" in q else ("Campus Canteen" if "canteen" in q or "cafeteria" in q else None)
            args = {"name": name_val} if name_val else {}
            return {"name": "get_facility_info", "arguments": args}

    # 9. Confirmed write tool: study block
    if "study block" in q or "schedule study" in q or "add study" in q:
        if "add_study_block" in available_tools:
            confirmed_val = True if "confirm" in q or "yes" in q else False
            return {
                "name": "add_study_block",
                "arguments": {
                    "subject": "Database Systems",
                    "date": "2026-10-12",
                    "start_time": "12:30",
                    "end_time": "13:30",
                    "title": "Exam Review Session",
                    "confirmed": confirmed_val,
                },
            }

    return None


async def execute_agent_loop(
    user_message: str,
    bearer_token: str,
    mode: str = "voice",
    mcp_server_url: str = DEFAULT_MCP_SERVER_URL,
    custom_llm_client: Any = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Execute the multi-turn agent loop connecting to MCP server over Streamable HTTP.

    Yields event dictionaries in real time:
    - {'type': 'tool_started', 'tool': name, 'arguments': args}
    - {'type': 'tool_result', 'tool': name, 'result': content, 'latency_ms': ms}
    - {'type': 'final_answer', 'content': text}
    - {'type': 'error', 'error': text}
    """
    system_prompt = get_system_prompt(mode=mode)
    headers = {"Authorization": f"Bearer {bearer_token}"}

    # Verify LLM provider configuration
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    use_live_openai = bool(openai_api_key) and custom_llm_client is None

    try:
        async with httpx2.AsyncClient(headers=headers, timeout=PER_CALL_TIMEOUT_SECONDS) as http_client:
            async with streamable_http_client(mcp_server_url, http_client=http_client) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    # 1. MCP Protocol Handshake
                    await session.initialize()

                    # 2. Tool Discovery
                    tools_result = await session.list_tools()
                    available_mcp_tools = tools_result.tools
                    tool_names = {t.name for t in available_mcp_tools}
                    openai_tools = mcp_tools_to_openai_schema(available_mcp_tools)

                    # Conversation history for tool calling loop
                    messages: List[Dict[str, Any]] = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ]

                    iterations = 0
                    final_answer_produced = False

                    while iterations < MAX_ITERATIONS and not final_answer_produced:
                        iterations += 1

                        tool_to_call = None
                        call_arguments = {}
                        tool_call_id = f"call_{int(time.time() * 1000)}"

                        if use_live_openai:
                            # Invoke real OpenAI API
                            from openai import AsyncOpenAI
                            client = AsyncOpenAI(api_key=openai_api_key)
                            model = os.getenv("LLM_MODEL", "gpt-4o")

                            response = await client.chat.completions.create(
                                model=model,
                                messages=messages,
                                tools=openai_tools,
                                tool_choice="auto",
                            )
                            choice = response.choices[0]
                            msg = choice.message

                            if msg.tool_calls:
                                tc = msg.tool_calls[0]
                                tool_to_call = tc.function.name
                                try:
                                    call_arguments = json.loads(tc.function.arguments)
                                except Exception:
                                    call_arguments = {}
                                tool_call_id = tc.id
                                messages.append(msg.model_dump())
                            else:
                                yield {"type": "final_answer", "content": msg.content or ""}
                                final_answer_produced = True
                                break
                        else:
                            # Deterministic simulation for test & evaluation workflows
                            simulated = simulate_tool_selection_for_query(user_message, tool_names)
                            if simulated and iterations == 1:
                                tool_to_call = simulated["name"]
                                call_arguments = simulated["arguments"]
                            else:
                                # Synthesize final answer from previous tool result
                                last_tool_msg = next((m for m in reversed(messages) if m["role"] == "tool"), None)
                                if last_tool_msg:
                                    try:
                                        res_data = json.loads(last_tool_msg["content"])
                                        answer = res_data.get("speech_summary") or res_data.get("result") or str(res_data)
                                    except Exception:
                                        answer = last_tool_msg["content"]
                                else:
                                    low_q = user_message.lower().strip()
                                    if any(w in low_q for w in ("hi", "hello", "hey", "good morning", "good afternoon")):
                                        answer = "Hello! I'm CampusMate, your AI college assistant. Ask me about your class schedule, upcoming assignments, classroom directions, attendance thresholds, or say 'Prepare my day' to generate an optimized daily plan."
                                    elif any(w in low_q for w in ("who are you", "what are you", "help", "what can you do", "features")):
                                        answer = "I am CampusMate, an AI college assistant for Alexa+. I can check your timetable, find classrooms with directions, list pending assignments, calculate free study slots, answer attendance skip questions, and synthesize your complete day with 'Prepare my day'."
                                    else:
                                        answer = f"I'm here to help with your college day! Try asking about your classes, pending assignments, classroom directions, attendance, or say 'Prepare my day'. You can also click any of the prompt chips below."

                                yield {"type": "final_answer", "content": answer}
                                final_answer_produced = True
                                break

                        # Execute tool call if requested by LLM
                        if tool_to_call:
                            # Guard: Tool allow-list check
                            if tool_to_call not in tool_names:
                                yield {
                                    "type": "error",
                                    "error": f"Tool '{tool_to_call}' is not authorized or not available.",
                                }
                                break

                            # Yield tool_started event
                            yield {
                                "type": "tool_started",
                                "tool": tool_to_call,
                                "arguments": call_arguments,
                            }

                            # Execute tool call over MCP Protocol with timeout guard
                            start_time = time.time()
                            try:
                                call_res = await asyncio.wait_for(
                                    session.call_tool(tool_to_call, arguments=call_arguments),
                                    timeout=PER_CALL_TIMEOUT_SECONDS,
                                )
                                latency_ms = int((time.time() - start_time) * 1000)

                                # Extract result payload
                                content_text = call_res.content[0].text if call_res.content else "{}"

                                # Yield tool_result event
                                yield {
                                    "type": "tool_result",
                                    "tool": tool_to_call,
                                    "result": content_text,
                                    "latency_ms": latency_ms,
                                    "is_error": call_res.is_error,
                                }

                                # Feed tool result back to LLM context (wrapped as DATA)
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call_id,
                                    "name": tool_to_call,
                                    "content": content_text,
                                })

                            except asyncio.TimeoutError:
                                yield {
                                    "type": "error",
                                    "error": f"Tool call to '{tool_to_call}' timed out after {PER_CALL_TIMEOUT_SECONDS}s.",
                                }
                                break

                    # Guard against exceeding maximum iterations
                    if iterations >= MAX_ITERATIONS and not final_answer_produced:
                        yield {
                            "type": "error",
                            "error": f"Exceeded maximum agent execution iterations ({MAX_ITERATIONS}).",
                        }

    except Exception as e:
        yield {
            "type": "error",
            "error": f"Agent communication failure: {str(e)}",
        }
