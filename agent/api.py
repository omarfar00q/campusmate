"""Agent HTTP and Server-Sent Events (SSE) API endpoint for CampusMate.

Exposes:
- POST /api/chat: streams tool execution events (tool_started, tool_result, final_answer, error) via SSE.
- GET /api/health: health check for the agent service.
- Full CORS support for Vite + React frontend.
- Zero database or API key leakage to frontend (Principle 8).
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, AsyncGenerator, Dict, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from dotenv import load_dotenv

load_dotenv()

from campusmate.agent.agent import execute_agent_loop

app = FastAPI(title="CampusMate Agent SSE Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(..., description="The user query or spoken utterance.", examples=["What classes do I have today?"])
    token: str = Field(..., description="Student demo bearer token.", examples=["token-alice-demo-cs"])
    mode: Optional[str] = Field(default="voice", description="Interaction mode: 'voice' or 'screen'.")


@app.get("/api/health")
async def health_check():
    """Agent health status."""
    return {
        "status": "ok",
        "service": "CampusMate Agent SSE API",
        "mcp_url": os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp"),
    }


@app.post("/api/chat")
async def stream_chat(req: ChatRequest):
    """Stream real-time agent execution events to frontend via Server-Sent Events."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    if not req.token.strip():
        raise HTTPException(status_code=401, detail="Bearer token is required.")

    mcp_url = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp")

    async def event_generator() -> AsyncGenerator[Dict[str, str], None]:
        async for event in execute_agent_loop(
            user_message=req.message,
            bearer_token=req.token,
            mode=req.mode or "voice",
            mcp_server_url=mcp_url,
        ):
            event_type = event.get("type", "message")
            yield {
                "event": event_type,
                "data": json.dumps(event),
            }

    return EventSourceResponse(event_generator())


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description="Run CampusMate Agent SSE API.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind agent service to")
    parser.add_argument("--port", type=int, default=8001, help="Port to bind agent service to (default 8001)")
    args = parser.parse_args()

    print(f"============================================================")
    print(f" CampusMate Agent SSE API")
    print(f" Endpoint:     http://{args.host}:{args.port}/api/chat")
    print(f" Health check: http://{args.host}:{args.port}/api/health")
    print(f"============================================================")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
