"""CampusMate MCP Server application.

Implements:
- Self-hosted MCP server over Streamable HTTP (MCP Spec 2025-11-25+)
- Bearer token authentication middleware with student session resolution
- /health endpoint
- CORS headers for browser clients and MCP Inspector
"""

from __future__ import annotations

import argparse
import os
from typing import Any, Dict, Optional
import uvicorn
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from mcp.server.mcpserver import MCPServer
import mcp.types as types
from dotenv import load_dotenv

load_dotenv()

from campusmate.server.app import auth, clock
from campusmate.server.app.database import get_db_session, init_db
from campusmate.server.app.tools.assignments import execute_get_assignments
from campusmate.server.app.tools.attendance import execute_get_attendance
from campusmate.server.app.tools.classrooms import execute_find_classroom
from campusmate.server.app.tools.exams import execute_get_exams
from campusmate.server.app.tools.facilities import execute_get_facility_info
from campusmate.server.app.tools.free_slots import execute_get_free_slots
from campusmate.server.app.tools.prepare_day import execute_prepare_my_day
from campusmate.server.app.tools.study_block import execute_add_study_block
from campusmate.server.app.tools.timetable import execute_get_timetable

# In-memory mapping of MCP Session IDs to resolved students
_session_student_cache: Dict[str, auth.Student] = {}


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """ASGI Middleware extracting Bearer token and establishing student session context."""

    async def dispatch(self, request: Request, call_next):
        # Allow health and CORS preflight without auth check
        if request.url.path in ("/health", "/", "/favicon.ico") or request.method == "OPTIONS":
            return await call_next(request)

        # 1. Try to extract token from Authorization header or custom header / query
        auth_header = request.headers.get("authorization", "")
        token = ""
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
        elif "x-campusmate-token" in request.headers:
            token = request.headers.get("x-campusmate-token", "").strip()
        elif "token" in request.query_params:
            token = request.query_params.get("token", "").strip()

        # 2. Check MCP Session ID header
        mcp_session_id = request.headers.get("mcp-session-id", "")

        resolved_student = None
        if token:
            try:
                with get_db_session() as db:
                    resolved_student = auth.resolve_student_from_token(token, db)
                    if mcp_session_id:
                        _session_student_cache[mcp_session_id] = resolved_student
            except auth.AuthenticationError:
                # If invalid token explicitly provided, return 401
                return JSONResponse(
                    {"error": "Unauthorized: Invalid or expired bearer token", "status_code": 401},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
        elif mcp_session_id and mcp_session_id in _session_student_cache:
            resolved_student = _session_student_cache[mcp_session_id]

        if resolved_student:
            auth.set_current_session(resolved_student, token)

        try:
            response = await call_next(request)
            return response
        finally:
            auth.clear_current_session()


def create_mcp_server() -> MCPServer:
    """Create and configure the MCPServer instance with all tools."""
    server = MCPServer(
        name="CampusMate",
        version="1.0.0",
        instructions=(
            "CampusMate: AI College Assistant MCP Server. "
            "Provides student timetable, assignments, exams, attendance, and campus facility assistance."
        ),
    )

    # Register get_timetable tool
    @server.tool(
        name="get_timetable",
        description=(
            "Retrieve class schedule for a specific date (YYYY-MM-DD). "
            "Returns list of classes with subject, time, room, building, floor, and spoken summary. "
            "Automatically scoped to the authenticated student."
        ),
        annotations=types.ToolAnnotations(read_only_hint=True, idempotent_hint=True),
    )
    async def get_timetable(date: str) -> Dict[str, Any]:
        return execute_get_timetable(date=date)

    # Register get_assignments tool
    @server.tool(
        name="get_assignments",
        description=(
            "Retrieve assignments for the authenticated student. "
            "Optional filters: status ('pending', 'submitted', 'overdue', 'all'), from_date, to_date. "
            "Returns titles, subjects, due dates, estimated effort, hours remaining, and spoken summary."
        ),
        annotations=types.ToolAnnotations(read_only_hint=True, idempotent_hint=True),
    )
    async def get_assignments(
        status: str = "pending",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        return execute_get_assignments(status=status, from_date=from_date, to_date=to_date)

    # Register find_classroom tool
    @server.tool(
        name="find_classroom",
        description=(
            "Locate the classroom and get step-by-step walking directions for a course/subject or room number. "
            "Optional date (YYYY-MM-DD) looks up the classroom for that specific day. "
            "Returns building, floor, room number, detailed directions, and spoken summary."
        ),
        annotations=types.ToolAnnotations(read_only_hint=True, idempotent_hint=True),
    )
    async def find_classroom(
        subject: str,
        date: Optional[str] = None,
    ) -> Dict[str, Any]:
        return execute_find_classroom(subject=subject, date=date)

    # Register get_free_slots tool
    @server.tool(
        name="get_free_slots",
        description=(
            "Calculate open, free time intervals between scheduled classes for a specific date (YYYY-MM-DD). "
            "Optional parameters: day_start (HH:MM, default '08:00'), day_end (HH:MM, default '18:00'), "
            "and min_minutes (minimum slot duration in minutes, default 30). "
            "Returns free time slots, total free duration, and spoken summary."
        ),
        annotations=types.ToolAnnotations(read_only_hint=True, idempotent_hint=True),
    )
    async def get_free_slots(
        date: str,
        day_start: Optional[str] = "08:00",
        day_end: Optional[str] = "18:00",
        min_minutes: Optional[int] = 30,
    ) -> Dict[str, Any]:
        return execute_get_free_slots(date=date, day_start=day_start, day_end=day_end, min_minutes=min_minutes)

    # Register prepare_my_day tool
    @server.tool(
        name="prepare_my_day",
        description=(
            "Synthesize a personalised, conflict-free daily schedule plan. "
            "Combines timetable classes, assignments, and exams into an organized day plan with study blocks, "
            "lunch buffer, capacity warnings when tasks do not fit, and spoken summary. "
            "Modes: 'today' or 'tomorrow_preview'."
        ),
        annotations=types.ToolAnnotations(read_only_hint=True, idempotent_hint=True),
    )
    async def prepare_my_day(
        date: str,
        mode: Optional[str] = "today",
    ) -> Dict[str, Any]:
        return execute_prepare_my_day(date=date, mode=mode)

    # Register get_exams tool
    @server.tool(
        name="get_exams",
        description=(
            "Retrieve scheduled exams for the authenticated student. "
            "Optional date range filters: from_date, to_date (YYYY-MM-DD). "
            "Returns exam subjects, dates, timings, classrooms, days remaining, and spoken summary."
        ),
        annotations=types.ToolAnnotations(read_only_hint=True, idempotent_hint=True),
    )
    async def get_exams(
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        return execute_get_exams(from_date=from_date, to_date=to_date)

    # Register get_attendance tool
    @server.tool(
        name="get_attendance",
        description=(
            "Check attendance records and evaluate skip margin headroom. "
            "Optional parameter: subject name. "
            "Returns percentage, attended/total classes, threshold status, "
            "classes you can still safely miss, and spoken summary."
        ),
        annotations=types.ToolAnnotations(read_only_hint=True, idempotent_hint=True),
    )
    async def get_attendance(
        subject: Optional[str] = None,
    ) -> Dict[str, Any]:
        return execute_get_attendance(subject=subject)

    # Register get_facility_info tool
    @server.tool(
        name="get_facility_info",
        description=(
            "Check campus facility locations, operating hours, and live open status (Library, Canteen, AI Lab). "
            "Optional parameters: facility name, at_time (HH:MM). "
            "Returns location, hours, open_now status, description, and spoken summary."
        ),
        annotations=types.ToolAnnotations(read_only_hint=True, idempotent_hint=True),
    )
    async def get_facility_info(
        name: Optional[str] = None,
        at_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        return execute_get_facility_info(name=name, at_time=at_time)

    # Register add_study_block (Confirmed Write Tool)
    @server.tool(
        name="add_study_block",
        description=(
            "Schedule a custom dedicated study block. "
            "WRITE OPERATION requiring explicit confirmation: "
            "When confirmed=False, checks for class conflicts and proposes the block without saving. "
            "When confirmed=True, validates no conflicts exist and schedules the block. "
            "Arguments: subject, date (YYYY-MM-DD), start_time (HH:MM), end_time (HH:MM), title, confirmed (bool)."
        ),
        annotations=types.ToolAnnotations(read_only_hint=False, destructive_hint=False),
    )
    async def add_study_block(
        subject: str,
        date: str,
        start_time: str,
        end_time: str,
        title: str,
        confirmed: bool = False,
    ) -> Dict[str, Any]:
        return execute_add_study_block(
            subject=subject,
            date=date,
            start_time=start_time,
            end_time=end_time,
            title=title,
            confirmed=confirmed,
        )

    return server


def create_app() -> Any:
    """Create and assemble the Starlette/ASGI application."""
    init_db()

    server = create_mcp_server()
    app = server.streamable_http_app()

    # Health check route
    async def health_check(request: Request) -> Response:
        return JSONResponse({
            "status": "ok",
            "service": "CampusMate MCP Server",
            "spec_revision": "2025-11-25",
            "sdk_version": "2.3.0",
            "timestamp": clock.iso_now(),
        })

    app.routes.insert(0, Route("/health", health_check, methods=["GET"]))

    # Add BearerAuthMiddleware
    app.add_middleware(BearerAuthMiddleware)

    # Add CORS Middleware for MCP Inspector & browser agents
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return app


def main():
    parser = argparse.ArgumentParser(description="Run CampusMate MCP Server.")
    parser.add_argument("--host", default=os.getenv("MCP_SERVER_HOST", "127.0.0.1"), help="Host to bind server to")
    parser.add_argument("--port", type=int, default=int(os.getenv("MCP_SERVER_PORT", "8000")), help="Port to bind server to")
    args = parser.parse_args()

    print(f"============================================================")
    print(f" CampusMate MCP Server (Spec 2025-11-25 / SDK 2.3.0)")
    print(f" Streamable HTTP endpoint: http://{args.host}:{args.port}/mcp")
    print(f" Health check:             http://{args.host}:{args.port}/health")
    print(f"============================================================")

    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
