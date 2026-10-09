"""'Prepare My Day' composite planning tool for CampusMate MCP Server.

Implements prepare_my_day(date, mode):
- Standout hackathon feature combining timetable, assignments, exams into a personalised plan
- Calls deterministic planner pure functions
- Scoped to authenticated student
- Formats structured plan and natural speech summary
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from campusmate.server.app import clock
from campusmate.server.app.auth import AuthenticationError, get_current_student
from campusmate.server.app.database import get_db_session
from campusmate.server.app.models import Assignment, Exam, TimetableEntry
from campusmate.server.app.planner import (
    PlannerClass,
    PlannerExam,
    PlannerTask,
    plan_day_schedule,
)


class PrepareDayInput(BaseModel):
    date: str = Field(
        ...,
        description="Date to plan the day for in YYYY-MM-DD format (e.g., '2026-10-12').",
    )
    mode: Optional[str] = Field(
        default="today",
        description="Planning mode: 'today' or 'tomorrow_preview' (default: 'today').",
    )


def execute_prepare_my_day(
    date: str,
    mode: Optional[str] = "today",
) -> Dict[str, Any]:
    """Execute personalised day planning for the authenticated student."""
    # 1. Resolve authenticated student
    try:
        student = get_current_student()
    except AuthenticationError:
        return {
            "error": "Authentication required. Valid bearer token must be provided.",
            "is_error": True,
            "fits_everything": False,
            "schedule_blocks": [],
            "study_blocks": [],
            "unscheduled_tasks": [],
            "warnings": ["Authentication missing."],
            "speech_summary": "I couldn't prepare your day because your session is not authenticated.",
        }

    # 2. Validate date
    clean_date = date.strip() if date else ""
    try:
        parsed_date = datetime.strptime(clean_date, "%Y-%m-%d").date()
    except ValueError:
        return {
            "error": f"Invalid date format '{clean_date}'. Expected format YYYY-MM-DD.",
            "is_error": True,
            "fits_everything": False,
            "schedule_blocks": [],
            "study_blocks": [],
            "unscheduled_tasks": [],
            "warnings": ["Invalid date format."],
            "speech_summary": f"I couldn't plan your day because '{clean_date}' is not a valid date.",
        }

    clean_mode = (mode or "today").strip().lower()
    if clean_mode not in ("today", "tomorrow_preview"):
        clean_mode = "today"

    current_now = clock.now()

    # 3. Retrieve student's classes, assignments, and exams from DB
    with get_db_session() as session:
        # Classes for date
        class_records = (
            session.query(TimetableEntry)
            .filter_by(student_id=student.id, class_date=clean_date)
            .order_by(TimetableEntry.start_time.asc())
            .all()
        )
        classes = [
            PlannerClass(
                subject=c.subject,
                start_time=c.start_time,
                end_time=c.end_time,
                room=c.room,
                building=c.building,
                floor=c.floor,
            )
            for c in class_records
        ]

        # Pending or overdue assignments
        asgn_records = (
            session.query(Assignment)
            .filter(
                Assignment.student_id == student.id,
                Assignment.status.in_(["pending", "overdue"]),
            )
            .all()
        )
        tasks = []
        for a in asgn_records:
            try:
                due_dt = datetime.fromisoformat(a.due_at)
                if due_dt.tzinfo is None:
                    due_dt = due_dt.replace(tzinfo=current_now.tzinfo)
                is_overdue = due_dt < current_now or a.status == "overdue"
            except Exception:
                is_overdue = a.status == "overdue"

            tasks.append(
                PlannerTask(
                    id=a.id,
                    title=a.title,
                    subject=a.subject,
                    due_at=a.due_at,
                    estimated_effort_minutes=a.estimated_effort_minutes,
                    is_overdue=is_overdue,
                )
            )

        # Upcoming exams
        exam_records = session.query(Exam).filter_by(student_id=student.id).all()
        planner_exams = []
        for e in exam_records:
            try:
                e_dt = datetime.fromisoformat(e.exam_datetime)
                days_rem = (e_dt.date() - parsed_date).days
            except Exception:
                days_rem = 14
            planner_exams.append(
                PlannerExam(
                    subject=e.subject,
                    exam_datetime=e.exam_datetime,
                    days_remaining=days_rem,
                )
            )

    # 4. Run deterministic planner pure function
    plan_result = plan_day_schedule(
        plan_date=parsed_date,
        classes=classes,
        tasks=tasks,
        exams=planner_exams,
    )

    prefix_summary = "Here is your plan for tomorrow: " if clean_mode == "tomorrow_preview" else ""

    return {
        "date": plan_result.date,
        "mode": clean_mode,
        "student_name": student.name,
        "fits_everything": plan_result.fits_everything,
        "total_free_minutes": plan_result.total_free_minutes,
        "total_task_minutes_needed": plan_result.total_task_minutes_needed,
        "schedule_blocks": plan_result.schedule_blocks,
        "study_blocks": plan_result.study_blocks,
        "unscheduled_tasks": plan_result.unscheduled_tasks,
        "warnings": plan_result.warnings,
        "speech_summary": prefix_summary + plan_result.speech_summary,
        "is_error": False,
    }
