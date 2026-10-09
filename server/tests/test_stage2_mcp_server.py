"""Stage 2 tests: MCP Server over Streamable HTTP with get_timetable & auth."""

import os
import pytest
import uvicorn
import httpx
import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from campusmate.data.seed_data import TOKEN_ALICE, TOKEN_BOB, seed_database
from campusmate.server.app import auth
from campusmate.server.app.main import create_app
from campusmate.server.app.tools.timetable import execute_get_timetable


@pytest.fixture(scope="module", autouse=True)
def setup_seed_db():
    """Seed test database once for the module."""
    seed_database(reset=True)


@pytest.fixture
async def test_client():
    """Httpx AsyncClient for direct HTTP tests on Starlette ASGI app."""
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_check_returns_ok_and_spec_revision(self, test_client):
        response = await test_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "CampusMate MCP Server"
        assert data["spec_revision"] == "2025-11-25"
        assert data["sdk_version"] == "2.3.0"


class TestTimetableToolLogic:
    def test_execute_get_timetable_without_auth_fails_gracefully(self):
        auth.clear_current_session()
        result = execute_get_timetable("2026-10-12")
        assert result.get("is_error") is True
        assert "Authentication required" in result["error"]

    def test_execute_get_timetable_invalid_date_returns_error(self):
        mock_student = auth.Student(id="student_alice", name="Alice Rivera", department="CS", semester=5, email="a@test.edu")
        auth.set_current_session(mock_student)
        try:
            result = execute_get_timetable("not-a-valid-date")
            assert result.get("is_error") is True
            assert "Invalid date format" in result["error"]
        finally:
            auth.clear_current_session()

    def test_execute_get_timetable_for_alice_returns_classes(self):
        mock_student = auth.Student(id="student_alice", name="Alice Rivera", department="CS", semester=5, email="a@test.edu")
        auth.set_current_session(mock_student)
        try:
            result = execute_get_timetable("2026-10-12")
            assert result.get("is_error") is not True
            assert result["date"] == "2026-10-12"
            assert result["student_name"] == "Alice Rivera"
            assert len(result["classes"]) >= 3
            # Check presence of first class
            first = result["classes"][0]
            assert "Database Systems" in first["subject"]
            assert first["room"] == "CS-302"
            assert "speech_summary" in result
            assert "Database Systems" in result["speech_summary"]
        finally:
            auth.clear_current_session()

    def test_student_isolation_bob_vs_alice(self):
        # Alice has classes on Friday 2026-10-16
        student_alice = auth.Student(id="student_alice", name="Alice Rivera", department="CS", semester=5, email="a@test.edu")
        auth.set_current_session(student_alice)
        alice_res = execute_get_timetable("2026-10-16")
        assert alice_res["class_count"] >= 1
        auth.clear_current_session()

        # Bob has NO classes on Friday 2026-10-16 (Edge Case)
        student_bob = auth.Student(id="student_bob", name="Bob Chen", department="EE", semester=3, email="b@test.edu")
        auth.set_current_session(student_bob)
        bob_res = execute_get_timetable("2026-10-16")
        assert bob_res["class_count"] == 0
        assert "no classes scheduled" in bob_res["speech_summary"].lower()
        auth.clear_current_session()


class TestMcpProtocolOverStreamableHttp:
    @pytest.mark.asyncio
    async def test_mcp_client_handshake_and_tool_call(self):
        """Spawns an ASGI server instance on a test port and connects via official MCP client."""
        import asyncio
        app = create_app()
        test_port = 8765
        config = uvicorn.Config(app, host="127.0.0.1", port=test_port, log_level="error")
        server = uvicorn.Server(config)
        server_task = asyncio.create_task(server.serve())

        # Give server time to bind
        await asyncio.sleep(0.5)

        try:
            # 1. Connect with Alice's Bearer token
            headers = {"Authorization": f"Bearer {TOKEN_ALICE}"}
            async with httpx2.AsyncClient(headers=headers) as http_client:
                mcp_url = f"http://127.0.0.1:{test_port}/mcp"
                async with streamable_http_client(mcp_url, http_client=http_client) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        # Handshake
                        init_result = await session.initialize()
                        assert init_result is not None

                        # List tools
                        tools_result = await session.list_tools()
                        tool_names = [t.name for t in tools_result.tools]
                        assert "get_timetable" in tool_names

                        # Call tool through MCP protocol
                        call_result = await session.call_tool(
                            "get_timetable",
                            arguments={"date": "2026-10-12"}
                        )
                        assert call_result is not None
                        assert call_result.is_error is False

                        # Verify content returned
                        text_content = call_result.content[0].text
                        assert "Database Systems" in text_content
                        assert "Alice Rivera" in text_content

            # 2. Connect with Bob's Bearer token and verify isolation
            headers_bob = {"Authorization": f"Bearer {TOKEN_BOB}"}
            async with httpx2.AsyncClient(headers=headers_bob) as http_client:
                mcp_url = f"http://127.0.0.1:{test_port}/mcp"
                async with streamable_http_client(mcp_url, http_client=http_client) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        call_result = await session.call_tool(
                            "get_timetable",
                            arguments={"date": "2026-10-12"}
                        )
                        assert call_result.is_error is False
                        text_content = call_result.content[0].text
                        # Bob takes Circuit Analysis, NOT Database Systems
                        assert "Circuit Analysis" in text_content
                        assert "Bob Chen" in text_content

        finally:
            server.should_exit = True
            await server_task
