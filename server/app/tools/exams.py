"""Exams tool for CampusMate MCP Server.

Implements get_exams(from_date, to_date):
- Retrieves student's upcoming exams
- Scoped to authenticated student
- Calculates days remaining against current clock
- Formats structured details and natural spoken speech summary
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from campusmate.server.app import clock
from campusmate.server.app.auth import AuthenticationError, get_current_student
from campusmate.server.app.database import get_db_session
from campusmate.server.app.models import Exam


class ExamsInput(BaseModel):
    from_date: Optional[str] = Field(
        default=None,
        description="Optional filter for exams on or after this date (YYYY-MM-DD).",
    )
    to_date: Optional[str] = Field(
        default=None,
        description="Optional filter for exams on or before this date (YYYY-MM-DD).",
    )


def execute_get_exams(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieve exams for the authenticated student."""
    try:
        student = get_current_student()
    except AuthenticationError:
        return {
            "error": "Authentication required. Valid bearer token must be provided.",
            "is_error": True,
            "exams": [],
            "speech_summary": "I couldn't retrieve your exams because your session is not authenticated.",
        }

    current_date = clock.get_current_date()

    with get_db_session() as session:
        query = session.query(Exam).filter_by(student_id=student.id).order_by(Exam.exam_datetime.asc())
        records = query.all()

        formatted_exams: List[Dict[str, Any]] = []
        for r in records:
            try:
                exam_dt = datetime.fromisoformat(r.exam_datetime)
                exam_date_str = exam_dt.strftime("%Y-%m-%d")
                exam_time_str = exam_dt.strftime("%H:%M")
                days_rem = (exam_dt.date() - current_date).days
            except Exception:
                exam_date_str = r.exam_datetime
                exam_time_str = "TBD"
                days_rem = 0

            # Optional date range filtering
            if from_date and exam_date_str < from_date.strip():
                continue
            if to_date and exam_date_str > to_date.strip():
                continue

            formatted_exams.append({
                "id": r.id,
                "subject": r.subject,
                "datetime": r.exam_datetime,
                "date": exam_date_str,
                "time": exam_time_str,
                "room": r.room,
                "building": r.building,
                "days_remaining": days_rem,
            })

    count = len(formatted_exams)
    if count == 0:
        speech = "You have no upcoming exams scheduled."
    elif count == 1:
        e = formatted_exams[0]
        speech = f"You have 1 upcoming exam: {e['subject']} in {e['days_remaining']} days on {e['date']} in room {e['room']}."
    else:
        first = formatted_exams[0]
        speech = (
            f"You have {count} upcoming exams. The nearest is {first['subject']} in {first['days_remaining']} days "
            f"on {first['date']} in {first['building']} room {first['room']}."
        )

    return {
        "student_name": student.name,
        "exam_count": count,
        "exams": formatted_exams,
        "speech_summary": speech,
        "is_error": False,
    }
