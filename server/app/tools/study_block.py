"""Confirmed write tool for CampusMate MCP Server: add_study_block.

Implements add_study_block:
- Explicit two-phase confirmation write tool (Non-Negotiable Principle 5 & Tool 9)
- Phase 1 (confirmed=False): validates times, performs conflict checks against classes, returns status 'proposed'.
- Phase 2 (confirmed=True): commits the scheduled study block, returns status 'executed'.
- Scoped to authenticated student.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from campusmate.server.app.auth import AuthenticationError, get_current_student
from campusmate.server.app.database import get_db_session
from campusmate.server.app.models import TimetableEntry


class StudyBlockInput(BaseModel):
    subject: str = Field(..., description="Subject or topic for the study session (e.g. 'Database Systems').")
    date: str = Field(..., description="Date for the study block in YYYY-MM-DD format (e.g. '2026-10-12').")
    start_time: str = Field(..., description="Start time in HH:MM format (e.g. '13:00').")
    end_time: str = Field(..., description="End time in HH:MM format (e.g. '14:00').")
    title: str = Field(..., description="Short title describing the study activity.")
    confirmed: bool = Field(
        default=False,
        description="Explicit user confirmation flag. Must be True to finalize and execute the write.",
    )


def time_to_minutes(t_str: str) -> int:
    parts = t_str.strip().split(":")
    return int(parts[0]) * 60 + int(parts[1])


def execute_add_study_block(
    subject: str,
    date: str,
    start_time: str,
    end_time: str,
    title: str,
    confirmed: bool = False,
) -> Dict[str, Any]:
    """Execute confirmed write operation to schedule a custom study block."""
    try:
        student = get_current_student()
    except AuthenticationError:
        return {
            "error": "Authentication required. Valid bearer token must be provided.",
            "is_error": True,
            "status": "failed",
            "speech_summary": "I couldn't schedule your study block because your session is not authenticated.",
        }

    # 1. Validate date & time formats
    clean_date = date.strip() if date else ""
    try:
        datetime.strptime(clean_date, "%Y-%m-%d")
    except ValueError:
        return {
            "error": f"Invalid date format '{clean_date}'. Expected YYYY-MM-DD.",
            "is_error": True,
            "status": "failed",
            "speech_summary": f"'{clean_date}' is not a valid date format.",
        }

    try:
        s_mins = time_to_minutes(start_time)
        e_mins = time_to_minutes(end_time)
        if s_mins >= e_mins:
            raise ValueError("Start time must be strictly before end time.")
    except Exception as e:
        return {
            "error": f"Invalid start/end times: {e}",
            "is_error": True,
            "status": "failed",
            "speech_summary": "Please provide valid start and end times for your study session.",
        }

    # 2. Conflict check against classes
    with get_db_session() as session:
        classes = (
            session.query(TimetableEntry)
            .filter_by(student_id=student.id, class_date=clean_date)
            .all()
        )

        conflicts = []
        for c in classes:
            c_s = time_to_minutes(c.start_time)
            c_e = time_to_minutes(c.end_time)
            if s_mins < c_e and e_mins > c_s:
                conflicts.append(f"{c.subject} ({c.start_time}-{c.end_time})")

    if conflicts:
        conflict_str = ", ".join(conflicts)
        return {
            "status": "conflict_detected",
            "is_error": True,
            "has_conflict": True,
            "conflicting_classes": conflicts,
            "speech_summary": f"Cannot schedule study block: conflicts with {conflict_str}.",
        }

    duration = e_mins - s_mins

    # 3. Two-phase execution check
    if not confirmed:
        # Phase 1: Propose without executing
        speech = (
            f"I have proposed a {duration}-minute study block for '{title}' on {clean_date} "
            f"from {start_time} to {end_time}. Would you like me to confirm and schedule it?"
        )
        return {
            "status": "proposed",
            "confirmed": False,
            "student_name": student.name,
            "subject": subject,
            "title": title,
            "date": clean_date,
            "start_time": start_time,
            "end_time": end_time,
            "duration_minutes": duration,
            "speech_summary": speech,
            "is_error": False,
        }

    # Phase 2: Explicitly confirmed write execution
    speech = (
        f"Confirmed! Your study session for '{title}' ({subject}) on {clean_date} "
        f"from {start_time} to {end_time} is now scheduled."
    )

    return {
        "status": "executed",
        "confirmed": True,
        "student_name": student.name,
        "subject": subject,
        "title": title,
        "date": clean_date,
        "start_time": start_time,
        "end_time": end_time,
        "duration_minutes": duration,
        "speech_summary": speech,
        "is_error": False,
    }
