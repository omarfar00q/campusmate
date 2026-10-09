"""Timetable tool for CampusMate MCP Server.

Implements get_timetable(date):
- Filters strictly by authenticated student from session context
- Validates date format (YYYY-MM-DD)
- Returns structured class details with natural speech summary
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict
from pydantic import BaseModel, Field

from campusmate.server.app.auth import AuthenticationError, get_current_student
from campusmate.server.app.database import get_db_session
from campusmate.server.app.models import TimetableEntry


class TimetableInput(BaseModel):
    date: str = Field(
        ...,
        description="The date to check the timetable for in YYYY-MM-DD format (e.g., '2026-10-12').",
        examples=["2026-10-12"]
    )


def execute_get_timetable(date: str) -> Dict[str, Any]:
    """Execute timetable lookup for the authenticated student on a given date."""
    # 1. Resolve authenticated student from context
    try:
        student = get_current_student()
    except AuthenticationError as e:
        return {
            "error": "Authentication required. Valid bearer token must be provided.",
            "is_error": True,
            "classes": [],
            "speech_summary": "I couldn't retrieve your schedule because your session is not authenticated."
        }

    # 2. Validate date input
    clean_date = date.strip() if date else ""
    try:
        parsed_date = datetime.strptime(clean_date, "%Y-%m-%d").date()
    except ValueError:
        return {
            "error": f"Invalid date format '{clean_date}'. Expected format is YYYY-MM-DD (e.g. '2026-10-12').",
            "is_error": True,
            "classes": [],
            "speech_summary": f"I couldn't check your schedule because '{clean_date}' is not a valid date."
        }

    # 3. Query timetable strictly for the authenticated student
    with get_db_session() as session:
        entries = (
            session.query(TimetableEntry)
            .filter_by(student_id=student.id, class_date=clean_date)
            .order_by(TimetableEntry.start_time.asc())
            .all()
        )

        formatted_classes = [
            {
                "subject": entry.subject,
                "start": entry.start_time,
                "end": entry.end_time,
                "room": entry.room,
                "building": entry.building,
                "floor": entry.floor,
            }
            for entry in entries
        ]

    # 4. Generate natural speech summary
    day_name = parsed_date.strftime("%A")
    date_formatted = parsed_date.strftime("%B %d")
    count = len(formatted_classes)

    if count == 0:
        speech = f"You have no classes scheduled for {day_name}, {date_formatted}."
    elif count == 1:
        first = formatted_classes[0]
        speech = (
            f"You have one class on {day_name}: {first['subject']} at {first['start']} "
            f"in {first['building']} room {first['room']}."
        )
    else:
        first = formatted_classes[0]
        speech = (
            f"You have {count} classes on {day_name}, starting with {first['subject']} at {first['start']} "
            f"in room {first['room']}."
        )

    return {
        "date": clean_date,
        "day_of_week": day_name,
        "student_name": student.name,
        "class_count": count,
        "classes": formatted_classes,
        "speech_summary": speech,
        "is_error": False,
    }
