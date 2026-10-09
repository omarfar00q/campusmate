"""Classrooms and navigation tool for CampusMate MCP Server.

Implements find_classroom(subject, date?):
- Locates the student's classroom for a given subject
- Retrieves detailed walking directions from the classrooms database
- Scoped to authenticated student timetable
- Generates natural spoken directions summary
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from campusmate.server.app import clock
from campusmate.server.app.auth import AuthenticationError, get_current_student
from campusmate.server.app.database import get_db_session
from campusmate.server.app.models import Classroom, TimetableEntry


class ClassroomInput(BaseModel):
    subject: str = Field(
        ...,
        description="The subject or course name to find the classroom for (e.g., 'Database Systems' or 'Operating Systems').",
    )
    date: Optional[str] = Field(
        default=None,
        description="Optional date (YYYY-MM-DD) to look up the classroom for. If omitted, finds the nearest upcoming class.",
    )


def execute_find_classroom(subject: str, date: Optional[str] = None) -> Dict[str, Any]:
    """Find classroom details and walking directions for a subject."""
    # 1. Resolve authenticated student
    try:
        student = get_current_student()
    except AuthenticationError:
        return {
            "error": "Authentication required. Valid bearer token must be provided.",
            "is_error": True,
            "speech_summary": "I couldn't locate your classroom because your session is not authenticated.",
        }

    clean_subj = subject.strip() if subject else ""
    if not clean_subj:
        return {
            "error": "Subject cannot be empty.",
            "is_error": True,
            "speech_summary": "Please specify a subject name so I can find your classroom.",
        }

    with get_db_session() as session:
        # Search timetable entries matching subject for this student
        query = session.query(TimetableEntry).filter(
            TimetableEntry.student_id == student.id,
            TimetableEntry.subject.ilike(f"%{clean_subj}%"),
        )

        if date and date.strip():
            query = query.filter(TimetableEntry.class_date == date.strip())
        else:
            # Look on or after today if possible
            current_date_str = clock.get_current_date().isoformat()
            upcoming_entries = query.filter(TimetableEntry.class_date >= current_date_str).order_by(
                TimetableEntry.class_date.asc(), TimetableEntry.start_time.asc()
            ).all()
            if upcoming_entries:
                entry = upcoming_entries[0]
            else:
                entry = query.order_by(TimetableEntry.class_date.asc(), TimetableEntry.start_time.asc()).first()
        if date and date.strip():
            entry = query.order_by(TimetableEntry.start_time.asc()).first()

        if not entry:
            # Also check if user passed a room number directly (e.g., 'CS-302')
            classroom_record = session.query(Classroom).filter(
                Classroom.room_number.ilike(clean_subj)
            ).first()
            if classroom_record:
                speech = (
                    f"Room {classroom_record.room_number} is in {classroom_record.building} on the {classroom_record.floor}. "
                    f"Directions: {classroom_record.directions}"
                )
                return {
                    "room_number": classroom_record.room_number,
                    "building": classroom_record.building,
                    "floor": classroom_record.floor,
                    "directions": classroom_record.directions,
                    "speech_summary": speech,
                    "is_error": False,
                }

            return {
                "error": f"No classroom found for subject '{clean_subj}'.",
                "is_error": False,
                "classroom": None,
                "speech_summary": f"I couldn't find any scheduled class for {clean_subj} in your timetable.",
            }

        # Look up directions in Classroom table
        directions = "Follow signs in the building corridor."
        classroom_record = session.query(Classroom).filter(
            Classroom.room_number == entry.room
        ).first()
        if classroom_record and classroom_record.directions:
            directions = classroom_record.directions

        speech = (
            f"Your {entry.subject} class is in {entry.building}, Room {entry.room} on the {entry.floor}. "
            f"{directions}"
        )

        return {
            "subject": entry.subject,
            "class_date": entry.class_date,
            "start_time": entry.start_time,
            "end_time": entry.end_time,
            "room_number": entry.room,
            "building": entry.building,
            "floor": entry.floor,
            "directions": directions,
            "speech_summary": speech,
            "is_error": False,
        }
