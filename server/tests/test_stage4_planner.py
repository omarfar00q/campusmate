"""Stage 4 tests for deterministic planner pure functions and prepare_my_day tool."""

from datetime import date
import pytest
import uvicorn
import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from campusmate.data.seed_data import TOKEN_ALICE, TOKEN_CHARLIE, seed_database
from campusmate.server.app import auth
from campusmate.server.app.main import create_app
from campusmate.server.app.planner import (
    PlannerClass,
    PlannerExam,
    PlannerTask,
    calculate_priority_score,
    compute_available_free_slots_with_buffers,
    plan_day_schedule,
    time_to_minutes,
)
from campusmate.server.app.tools.prepare_day import execute_prepare_my_day


@pytest.fixture(scope="module", autouse=True)
def setup_seed_db():
    seed_database(reset=True)


@pytest.fixture(autouse=True)
def clean_context():
    auth.clear_current_session()
    yield
    auth.clear_current_session()


class TestPlannerPureFunctions:
    def test_priority_score_deterministic_and_favors_overdue(self):
        today = date(2026, 10, 12)
        overdue_task = PlannerTask(
            id=1, title="Overdue SQL", subject="DB", due_at="2026-10-11T23:59:59Z", estimated_effort_minutes=90, is_overdue=True
        )
        regular_task = PlannerTask(
            id=2, title="Future Networking", subject="CN", due_at="2026-10-18T23:59:59Z", estimated_effort_minutes=90, is_overdue=False
        )

        score_overdue = calculate_priority_score(overdue_task, today, set())
        score_regular = calculate_priority_score(regular_task, today, set())

        assert score_overdue > 1000.0
        assert score_regular < 200.0
        assert score_overdue > score_regular

    def test_priority_boost_for_upcoming_exam_subject(self):
        today = date(2026, 10, 12)
        task_with_exam = PlannerTask(
            id=1, title="OS Lab", subject="OS", due_at="2026-10-15T00:00:00Z", estimated_effort_minutes=60, is_overdue=False
        )
        task_without_exam = PlannerTask(
            id=2, title="SE Review", subject="SE", due_at="2026-10-15T00:00:00Z", estimated_effort_minutes=60, is_overdue=False
        )

        score_exam = calculate_priority_score(task_with_exam, today, {"OS"})
        score_no_exam = calculate_priority_score(task_without_exam, today, set())

        assert score_exam - score_no_exam == 200.0

    def test_free_slots_with_lunch_buffer(self):
        # Classes: 09:00 - 10:30 and 13:30 - 15:00
        classes = [
            PlannerClass(subject="Math", start_time="09:00", end_time="10:30", room="101", building="A", floor="1"),
            PlannerClass(subject="Physics", start_time="13:30", end_time="15:00", room="102", building="A", floor="1"),
        ]

        study_slots, lunch = compute_available_free_slots_with_buffers(
            classes=classes,
            window_start=time_to_minutes("08:00"),
            window_end=time_to_minutes("18:00"),
        )

        # Lunch should be scheduled in the 10:30-13:30 gap around 12:00-12:30
        assert lunch is not None
        l_s, l_e = lunch
        assert l_s >= time_to_minutes("12:00")
        assert l_e <= time_to_minutes("13:30")
        assert l_e - l_s == 30

        # No study slot overlaps with lunch
        for s_start, s_end in study_slots:
            assert not (s_start < l_e and s_end > l_s)

    def test_greedy_fit_everything_when_time_is_sufficient(self):
        today = date(2026, 10, 12)
        classes = [
            PlannerClass(subject="Intro CS", start_time="10:00", end_time="11:30", room="101", building="A", floor="1")
        ]
        tasks = [
            PlannerTask(id=1, title="Small Quiz Prep", subject="Intro CS", due_at="2026-10-13T00:00:00Z", estimated_effort_minutes=45),
            PlannerTask(id=2, title="Short Reading", subject="Intro CS", due_at="2026-10-14T00:00:00Z", estimated_effort_minutes=30),
        ]

        result = plan_day_schedule(
            plan_date=today,
            classes=classes,
            tasks=tasks,
            exams=[],
            day_start_str="09:00",
            day_end_str="17:00",
        )

        assert result.fits_everything is True
        assert len(result.unscheduled_tasks) == 0
        assert len(result.study_blocks) == 2
        assert len(result.warnings) == 0

    def test_does_not_fit_case_honest_warnings_and_deficit(self):
        """CRITICAL REQUIREMENT: When tasks exceed free time, fits_everything=False and warnings generated."""
        today = date(2026, 10, 12)
        # Busy schedule: 09:00-12:00 and 13:00-17:00 (only 1h morning free: 08:00-09:00, 1h evening: 17:00-18:00)
        classes = [
            PlannerClass(subject="Heavy Class 1", start_time="09:00", end_time="12:00", room="101", building="A", floor="1"),
            PlannerClass(subject="Heavy Class 2", start_time="13:00", end_time="17:00", room="102", building="A", floor="1"),
        ]
        # Workload requires 300 minutes (5 hours), but only ~120 minutes free!
        tasks = [
            PlannerTask(id=1, title="Major Project Coding", subject="SE", due_at="2026-10-12T23:59:59Z", estimated_effort_minutes=180, is_overdue=True),
            PlannerTask(id=2, title="Research Paper Draft", subject="AI", due_at="2026-10-13T23:59:59Z", estimated_effort_minutes=120, is_overdue=False),
        ]

        result = plan_day_schedule(
            plan_date=today,
            classes=classes,
            tasks=tasks,
            exams=[],
            day_start_str="08:00",
            day_end_str="18:00",
        )

        assert result.fits_everything is False
        assert len(result.unscheduled_tasks) >= 1
        assert len(result.warnings) >= 1
        assert "Insufficient free time" in result.warnings[0]
        assert "couldn't fit" in result.speech_summary.lower()

        # Verify classes never overlap
        for b in result.schedule_blocks:
            if b["type"] == "study":
                b_start = time_to_minutes(b["start"])
                b_end = time_to_minutes(b["end"])
                # Class 1 is 540 to 720 (09:00 - 12:00)
                assert not (b_start < 720 and b_end > 540)
                # Class 2 is 780 to 1020 (13:00 - 17:00)
                assert not (b_start < 1020 and b_end > 780)


class TestPrepareMyDayToolIntegration:
    def test_unauthenticated_fails_gracefully(self):
        res = execute_prepare_my_day(date="2026-10-12")
        assert res["is_error"] is True
        assert "Authentication required" in res["error"]

    def test_invalid_date_returns_error(self):
        student_alice = auth.Student(id="student_alice", name="Alice Rivera", department="CS", semester=5, email="a@test.edu")
        auth.set_current_session(student_alice)
        res = execute_prepare_my_day(date="2026-99-99")
        assert res["is_error"] is True
        assert "Invalid date format" in res["error"]

    def test_alice_busy_day_produces_structured_plan(self):
        student_alice = auth.Student(id="student_alice", name="Alice Rivera", department="CS", semester=5, email="a@test.edu")
        auth.set_current_session(student_alice)

        res = execute_prepare_my_day(date="2026-10-12", mode="today")
        assert res["is_error"] is False
        assert res["date"] == "2026-10-12"
        assert res["student_name"] == "Alice Rivera"
        assert len(res["schedule_blocks"]) >= 4
        assert "speech_summary" in res
        assert len(res["speech_summary"]) > 20

    def test_charlie_light_day_fits_cleanly(self):
        student_charlie = auth.Student(id="student_charlie", name="Charlie Davis", department="ME", semester=7, email="c@test.edu")
        auth.set_current_session(student_charlie)

        res = execute_prepare_my_day(date="2026-10-12", mode="today")
        assert res["is_error"] is False
        assert res["student_name"] == "Charlie Davis"
        assert res["fits_everything"] is True


class TestMcpProtocolPrepareDay:
    @pytest.mark.asyncio
    async def test_prepare_my_day_via_mcp_client(self):
        import asyncio
        app = create_app()
        test_port = 8767
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
                        assert "prepare_my_day" in tool_names

                        call_res = await session.call_tool(
                            "prepare_my_day",
                            arguments={"date": "2026-10-12", "mode": "today"}
                        )
                        assert call_res.is_error is False
                        text = call_res.content[0].text
                        assert "Alice Rivera" in text
                        assert "schedule_blocks" in text
                        assert "speech_summary" in text
        finally:
            server.should_exit = True
            await server_task
