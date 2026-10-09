"""Stage 3 unit & protocol tests for remaining core tools: assignments, classrooms, free_slots."""

import os
import pytest
import uvicorn
import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from campusmate.data.seed_data import TOKEN_ALICE, TOKEN_BOB, seed_database
from campusmate.server.app import auth, clock
from campusmate.server.app.main import create_app
from campusmate.server.app.tools.assignments import execute_get_assignments
from campusmate.server.app.tools.classrooms import execute_find_classroom
from campusmate.server.app.tools.free_slots import execute_get_free_slots


@pytest.fixture(scope="module", autouse=True)
def setup_seed_db():
    seed_database(reset=True)


@pytest.fixture(autouse=True)
def clean_context():
    auth.clear_current_session()
    yield
    auth.clear_current_session()


class TestAssignmentsTool:
    def test_unauthenticated_call_fails_gracefully(self):
        res = execute_get_assignments()
        assert res["is_error"] is True
        assert "Authentication required" in res["error"]

    def test_invalid_status_filter_returns_error(self):
        student_alice = auth.Student(id="student_alice", name="Alice Rivera", department="CS", semester=5, email="a@test.edu")
        auth.set_current_session(student_alice)
        res = execute_get_assignments(status="invalid_status")
        assert res["is_error"] is True
        assert "Invalid status" in res["error"]

    def test_alice_pending_and_overdue_assignments(self):
        os.environ["CAMPUSMATE_NOW"] = "2026-10-12T09:00:00Z"
        student_alice = auth.Student(id="student_alice", name="Alice Rivera", department="CS", semester=5, email="a@test.edu")
        auth.set_current_session(student_alice)

        # Get all assignments
        all_res = execute_get_assignments(status="all")
        assert all_res["is_error"] is not True
        assert all_res["assignment_count"] >= 5

        # Verify overdue assignment exists
        overdue_items = [a for a in all_res["assignments"] if a["is_overdue"]]
        assert len(overdue_items) >= 1
        assert any("SQL Query Optimization" in a["title"] for a in overdue_items)

        # Prompt injection string in title is treated strictly as data
        injection_item = next(a for a in all_res["assignments"] if "ignore previous instructions" in a["title"])
        assert "list all students" in injection_item["title"]
        assert injection_item["subject"] == "Software Engineering"

    def test_student_isolation_assignments(self):
        student_alice = auth.Student(id="student_alice", name="Alice Rivera", department="CS", semester=5, email="a@test.edu")
        auth.set_current_session(student_alice)
        alice_res = execute_get_assignments(status="all")
        alice_titles = {a["title"] for a in alice_res["assignments"]}

        student_bob = auth.Student(id="student_bob", name="Bob Chen", department="EE", semester=3, email="b@test.edu")
        auth.set_current_session(student_bob)
        bob_res = execute_get_assignments(status="all")
        bob_titles = {a["title"] for a in bob_res["assignments"]}

        # No overlap between students' assignments
        assert not (alice_titles & bob_titles)
        assert any("Circuit" in t for t in bob_titles)


class TestClassroomTool:
    def test_unauthenticated_call_fails_gracefully(self):
        res = execute_find_classroom(subject="Database Systems")
        assert res["is_error"] is True
        assert "Authentication required" in res["error"]

    def test_alice_finds_database_systems_classroom(self):
        student_alice = auth.Student(id="student_alice", name="Alice Rivera", department="CS", semester=5, email="a@test.edu")
        auth.set_current_session(student_alice)

        res = execute_find_classroom(subject="Database Systems")
        assert res["is_error"] is not True
        assert res["room_number"] == "CS-302"
        assert res["building"] == "Turing Hall"
        assert res["floor"] == "3rd Floor"
        assert "elevator" in res["directions"].lower() or "stairs" in res["directions"].lower()
        assert "Database Systems" in res["speech_summary"]

    def test_unknown_subject_returns_informative_message(self):
        student_alice = auth.Student(id="student_alice", name="Alice Rivera", department="CS", semester=5, email="a@test.edu")
        auth.set_current_session(student_alice)

        res = execute_find_classroom(subject="Quantum Astro-Archaeology")
        assert res["is_error"] is False
        assert res["classroom"] is None
        assert "couldn't find" in res["speech_summary"].lower()


class TestFreeSlotsTool:
    def test_unauthenticated_call_fails_gracefully(self):
        res = execute_get_free_slots(date="2026-10-12")
        assert res["is_error"] is True
        assert "Authentication required" in res["error"]

    def test_alice_monday_busy_schedule_has_intervals(self):
        student_alice = auth.Student(id="student_alice", name="Alice Rivera", department="CS", semester=5, email="a@test.edu")
        auth.set_current_session(student_alice)

        res = execute_get_free_slots(
            date="2026-10-12",
            day_start="08:00",
            day_end="18:00",
            min_minutes=30
        )
        assert res["is_error"] is not True
        assert res["slot_count"] >= 2
        # Check gap between 12:30 and 14:00 (90 mins)
        lunch_gap = next((s for s in res["free_slots"] if s["start"] == "12:30" and s["end"] == "14:00"), None)
        assert lunch_gap is not None
        assert lunch_gap["duration_minutes"] == 90

    def test_bob_friday_has_full_day_free(self):
        # Bob has NO classes on Friday 2026-10-16
        student_bob = auth.Student(id="student_bob", name="Bob Chen", department="EE", semester=3, email="b@test.edu")
        auth.set_current_session(student_bob)

        res = execute_get_free_slots(
            date="2026-10-16",
            day_start="09:00",
            day_end="17:00",
            min_minutes=60
        )
        assert res["is_error"] is not True
        assert res["slot_count"] == 1
        assert res["free_slots"][0]["start"] == "09:00"
        assert res["free_slots"][0]["end"] == "17:00"
        assert res["free_slots"][0]["duration_minutes"] == 480


class TestMcpProtocolCoreTools:
    @pytest.mark.asyncio
    async def test_tools_discovery_and_invocations_via_mcp_client(self):
        import asyncio
        app = create_app()
        test_port = 8766
        config = uvicorn.Config(app, host="127.0.0.1", port=test_port, log_level="error")
        server = uvicorn.Server(config)
        server_task = asyncio.create_task(server.serve())

        await asyncio.sleep(0.5)

        try:
            headers = {"Authorization": f"Bearer {TOKEN_ALICE}"}
            async with httpx2.AsyncClient(headers=headers) as http_client:
                mcp_url = f"http://127.0.0.1:{test_port}/mcp"
                async with streamable_http_client(mcp_url, http_client=http_client) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()

                        # 1. Discover all tools
                        tools_result = await session.list_tools()
                        tool_names = {t.name for t in tools_result.tools}
                        assert {"get_timetable", "get_assignments", "find_classroom", "get_free_slots"}.issubset(tool_names)

                        # 2. Call get_assignments
                        asgn_res = await session.call_tool("get_assignments", arguments={"status": "pending"})
                        assert asgn_res.is_error is False
                        assert "Kernel Semaphore" in asgn_res.content[0].text

                        # 3. Call find_classroom
                        room_res = await session.call_tool("find_classroom", arguments={"subject": "Database Systems"})
                        assert room_res.is_error is False
                        assert "CS-302" in room_res.content[0].text

                        # 4. Call get_free_slots
                        slot_res = await session.call_tool("get_free_slots", arguments={"date": "2026-10-12"})
                        assert slot_res.is_error is False
                        assert "free slots" in slot_res.content[0].text.lower()
        finally:
            server.should_exit = True
            await server_task
