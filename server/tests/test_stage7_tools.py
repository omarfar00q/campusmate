"""Stage 7 tests: exams, attendance, facilities, and confirmed write tool (add_study_block)."""

from datetime import date
import pytest
import uvicorn
import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from campusmate.data.seed_data import TOKEN_ALICE, TOKEN_BOB, seed_database
from campusmate.server.app import auth
from campusmate.server.app.main import create_app
from campusmate.server.app.tools.attendance import (
    calculate_attendance_metrics,
    execute_get_attendance,
)
from campusmate.server.app.tools.exams import execute_get_exams
from campusmate.server.app.tools.facilities import execute_get_facility_info
from campusmate.server.app.tools.study_block import execute_add_study_block


@pytest.fixture(scope="module", autouse=True)
def setup_seed_db():
    seed_database(reset=True)


@pytest.fixture(autouse=True)
def clean_context():
    auth.clear_current_session()
    yield
    auth.clear_current_session()


class TestExamsTool:
    def test_unauthenticated_call_fails_gracefully(self):
        res = execute_get_exams()
        assert res["is_error"] is True
        assert "Authentication required" in res["error"]

    def test_alice_exams_retrieval_and_isolation(self):
        student_alice = auth.Student(id="student_alice", name="Alice Rivera", department="CS", semester=5, email="a@test.edu")
        auth.set_current_session(student_alice)

        res = execute_get_exams()
        assert res["is_error"] is False
        assert res["exam_count"] >= 1
        subjects = [e["subject"] for e in res["exams"]]
        assert "Database Systems" in subjects
        assert "speech_summary" in res

    def test_bob_exams_isolation(self):
        student_bob = auth.Student(id="student_bob", name="Bob Chen", department="EE", semester=3, email="b@test.edu")
        auth.set_current_session(student_bob)

        res = execute_get_exams()
        assert res["is_error"] is False
        subjects = [e["subject"] for e in res["exams"]]
        assert "Circuit Analysis" in subjects
        assert "Database Systems" not in subjects


class TestAttendanceTool:
    def test_attendance_metric_calculations(self):
        # 1. High attendance: 18 / 20 = 90% (Can still miss 4 classes without dropping below 75%)
        m_high = calculate_attendance_metrics(attended=18, total=20, min_threshold_pct=75.0)
        assert m_high["percentage"] == 90.0
        assert m_high["classes_can_still_miss"] == 4
        assert m_high["is_below_threshold"] is False
        assert m_high["is_on_borderline"] is False

        # 2. Borderline attendance: 15 / 20 = 75.0% (Cannot miss any class)
        m_borderline = calculate_attendance_metrics(attended=15, total=20, min_threshold_pct=75.0)
        assert m_borderline["percentage"] == 75.0
        assert m_borderline["classes_can_still_miss"] == 0
        assert m_borderline["is_on_borderline"] is True
        assert m_borderline["is_below_threshold"] is False

        # 3. Below threshold: 14 / 20 = 70.0% (Needs to attend 4 classes to recover)
        m_low = calculate_attendance_metrics(attended=14, total=20, min_threshold_pct=75.0)
        assert m_low["percentage"] == 70.0
        assert m_low["classes_can_still_miss"] == 0
        assert m_low["is_below_threshold"] is True
        assert m_low["classes_needed_to_reach_threshold"] == 4

    def test_alice_borderline_os_warning(self):
        student_alice = auth.Student(id="student_alice", name="Alice Rivera", department="CS", semester=5, email="a@test.edu")
        auth.set_current_session(student_alice)

        res = execute_get_attendance(subject="Operating Systems")
        assert res["is_error"] is False
        rec = res["records"][0]
        assert rec["status"] == "borderline"
        assert rec["classes_can_still_miss"] == 0
        assert "cannot miss any more" in res["speech_summary"].lower()

    def test_bob_below_threshold_alert(self):
        student_bob = auth.Student(id="student_bob", name="Bob Chen", department="EE", semester=3, email="b@test.edu")
        auth.set_current_session(student_bob)

        res = execute_get_attendance(subject="Electromagnetics")
        assert res["is_error"] is False
        rec = res["records"][0]
        assert rec["status"] == "below_threshold"
        assert rec["classes_needed_to_recover"] > 0
        assert "below the 75" in res["speech_summary"].lower()


class TestFacilitiesTool:
    def test_facility_open_and_closed_times(self):
        student_alice = auth.Student(id="student_alice", name="Alice Rivera", department="CS", semester=5, email="a@test.edu")
        auth.set_current_session(student_alice)

        # Library at 14:00 (Open)
        res_open = execute_get_facility_info(name="Library", at_time="14:00")
        assert res_open["is_error"] is False
        assert res_open["facilities"][0]["open_now"] is True
        assert "currently open" in res_open["speech_summary"]

        # Library at 23:30 (Closed)
        res_closed = execute_get_facility_info(name="Library", at_time="23:30")
        assert res_closed["is_error"] is False
        assert res_closed["facilities"][0]["open_now"] is False
        assert "currently closed" in res_closed["speech_summary"]


class TestConfirmedWriteStudyBlockTool:
    def test_phase_1_unconfirmed_proposes_block(self):
        student_alice = auth.Student(id="student_alice", name="Alice Rivera", department="CS", semester=5, email="a@test.edu")
        auth.set_current_session(student_alice)

        # Unconfirmed request
        res = execute_add_study_block(
            subject="Database Systems",
            date="2026-10-12",
            start_time="12:30",
            end_time="13:30",
            title="Midterm SQL Practice",
            confirmed=False,
        )
        assert res["is_error"] is False
        assert res["status"] == "proposed"
        assert res["confirmed"] is False
        assert "proposed a 60-minute" in res["speech_summary"].lower()

    def test_conflict_detection_prevents_overlap_with_classes(self):
        student_alice = auth.Student(id="student_alice", name="Alice Rivera", department="CS", semester=5, email="a@test.edu")
        auth.set_current_session(student_alice)

        # Alice has Database Systems class from 09:00 to 10:30 on 2026-10-12!
        res = execute_add_study_block(
            subject="Algorithms",
            date="2026-10-12",
            start_time="09:30",
            end_time="10:30",
            title="Greedy Algorithm Practice",
            confirmed=True,
        )
        assert res["is_error"] is True
        assert res["status"] == "conflict_detected"
        assert len(res["conflicting_classes"]) >= 1
        assert "Database Systems" in res["speech_summary"]

    def test_phase_2_confirmed_execution_succeeds(self):
        student_alice = auth.Student(id="student_alice", name="Alice Rivera", department="CS", semester=5, email="a@test.edu")
        auth.set_current_session(student_alice)

        # Confirmed execution during free window
        res = execute_add_study_block(
            subject="Database Systems",
            date="2026-10-12",
            start_time="12:30",
            end_time="13:30",
            title="Midterm SQL Practice",
            confirmed=True,
        )
        assert res["is_error"] is False
        assert res["status"] == "executed"
        assert res["confirmed"] is True
        assert "confirmed!" in res["speech_summary"].lower()


class TestMcpProtocolStage7Tools:
    @pytest.mark.asyncio
    async def test_all_tools_discovered_and_executable_via_mcp_client(self):
        import asyncio
        app = create_app()
        test_port = 8792
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

                        tools_res = await session.list_tools()
                        tool_names = {t.name for t in tools_res.tools}
                        expected = {
                            "get_timetable",
                            "get_assignments",
                            "find_classroom",
                            "get_free_slots",
                            "prepare_my_day",
                            "get_exams",
                            "get_attendance",
                            "get_facility_info",
                            "add_study_block",
                        }
                        assert expected.issubset(tool_names)

                        # Call get_exams
                        e_res = await session.call_tool("get_exams", arguments={})
                        assert e_res.is_error is False
                        assert "Database Systems" in e_res.content[0].text

                        # Call get_attendance
                        a_res = await session.call_tool("get_attendance", arguments={"subject": "Operating Systems"})
                        assert a_res.is_error is False
                        assert "75" in a_res.content[0].text

                        # Call get_facility_info
                        f_res = await session.call_tool("get_facility_info", arguments={"name": "Library"})
                        assert f_res.is_error is False
                        assert "Library" in f_res.content[0].text

                        # Call add_study_block
                        w_res = await session.call_tool(
                            "add_study_block",
                            arguments={
                                "subject": "Database Systems",
                                "date": "2026-10-12",
                                "start_time": "12:30",
                                "end_time": "13:30",
                                "title": "MCP Protocol Study Block",
                                "confirmed": False,
                            }
                        )
                        assert w_res.is_error is False
                        assert "proposed" in w_res.content[0].text
        finally:
            server.should_exit = True
            await server_task
