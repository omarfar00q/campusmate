"""Free slots calculation tool for CampusMate MCP Server.

Implements get_free_slots(date, day_start, day_end, min_minutes):
- Determines open intervals between classes within a working day window
- Scoped to the authenticated student
- Filters out slots smaller than min_minutes
- Generates natural spoken speech summary
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from campusmate.server.app.auth import AuthenticationError, get_current_student
from campusmate.server.app.database import get_db_session
from campusmate.server.app.models import TimetableEntry


class FreeSlotsInput(BaseModel):
    date: str = Field(
        ...,
        description="The date to check free slots for in YYYY-MM-DD format (e.g. '2026-10-12').",
    )
    day_start: Optional[str] = Field(
        default="08:00",
        description="Start time of the working day window in HH:MM format (default: '08:00').",
    )
    day_end: Optional[str] = Field(
        default="18:00",
        description="End time of the working day window in HH:MM format (default: '18:00').",
    )
    min_minutes: Optional[int] = Field(
        default=30,
        description="Minimum duration in minutes for an interval to be considered a free slot (default: 30).",
    )


def time_to_minutes(t_str: str) -> int:
    """Convert 'HH:MM' string to minutes from midnight."""
    parts = t_str.strip().split(":")
    return int(parts[0]) * 60 + int(parts[1])


def minutes_to_time(m: int) -> str:
    """Convert minutes from midnight to 'HH:MM' string."""
    hours = m // 60
    mins = m % 60
    return f"{hours:02d}:{mins:02d}"


def calculate_free_intervals(
    busy_intervals: List[Tuple[int, int]],
    window_start: int,
    window_end: int,
    min_minutes: int = 30,
) -> List[Dict[str, Any]]:
    """Compute free intervals given busy intervals sorted by start time."""
    # Merge overlapping or touching busy intervals
    merged_busy: List[Tuple[int, int]] = []
    for start, end in sorted(busy_intervals):
        if not merged_busy:
            merged_busy.append((start, end))
        else:
            prev_start, prev_end = merged_busy[-1]
            if start <= prev_end:
                merged_busy[-1] = (prev_start, max(prev_end, end))
            else:
                merged_busy.append((start, end))

    free_slots: List[Dict[str, Any]] = []
    current_cursor = window_start

    for b_start, b_end in merged_busy:
        if b_start > current_cursor:
            gap_duration = b_start - current_cursor
            if gap_duration >= min_minutes:
                free_slots.append({
                    "start": minutes_to_time(current_cursor),
                    "end": minutes_to_time(b_start),
                    "duration_minutes": gap_duration,
                })
        current_cursor = max(current_cursor, b_end)

    if current_cursor < window_end:
        gap_duration = window_end - current_cursor
        if gap_duration >= min_minutes:
            free_slots.append({
                "start": minutes_to_time(current_cursor),
                "end": minutes_to_time(window_end),
                "duration_minutes": gap_duration,
            })

    return free_slots


def execute_get_free_slots(
    date: str,
    day_start: Optional[str] = "08:00",
    day_end: Optional[str] = "18:00",
    min_minutes: Optional[int] = 30,
) -> Dict[str, Any]:
    """Calculate free time slots for the authenticated student on a date."""
    # 1. Resolve student
    try:
        student = get_current_student()
    except AuthenticationError:
        return {
            "error": "Authentication required. Valid bearer token must be provided.",
            "is_error": True,
            "free_slots": [],
            "speech_summary": "I couldn't check your free slots because your session is not authenticated.",
        }

    # 2. Validate date
    clean_date = date.strip() if date else ""
    try:
        parsed_date = datetime.strptime(clean_date, "%Y-%m-%d").date()
    except ValueError:
        return {
            "error": f"Invalid date format '{clean_date}'. Expected YYYY-MM-DD.",
            "is_error": True,
            "free_slots": [],
            "speech_summary": f"'{clean_date}' is not a valid date format.",
        }

    # 3. Validate window times
    start_str = day_start or "08:00"
    end_str = day_end or "18:00"
    min_mins = min_minutes if min_minutes is not None and min_minutes > 0 else 30

    try:
        w_start = time_to_minutes(start_str)
        w_end = time_to_minutes(end_str)
        if w_start >= w_end:
            raise ValueError("Start time must be before end time.")
    except Exception as e:
        return {
            "error": f"Invalid working window: {e}",
            "is_error": True,
            "free_slots": [],
            "speech_summary": "Please provide a valid start and end time for your day.",
        }

    # 4. Query student's classes on that date
    with get_db_session() as session:
        classes = (
            session.query(TimetableEntry)
            .filter_by(student_id=student.id, class_date=clean_date)
            .order_by(TimetableEntry.start_time.asc())
            .all()
        )

        busy_intervals = [
            (time_to_minutes(c.start_time), time_to_minutes(c.end_time))
            for c in classes
        ]

    # 5. Compute free slots
    free_slots = calculate_free_intervals(
        busy_intervals=busy_intervals,
        window_start=w_start,
        window_end=w_end,
        min_minutes=min_mins,
    )

    total_free_minutes = sum(s["duration_minutes"] for s in free_slots)
    hours = total_free_minutes // 60
    remaining_mins = total_free_minutes % 60
    time_str = f"{hours} hours" if remaining_mins == 0 else f"{hours} hours and {remaining_mins} minutes"
    day_name = parsed_date.strftime("%A")

    # Generate speech summary
    if not free_slots:
        speech = f"You have no free slots of at least {min_mins} minutes on {day_name} between {start_str} and {end_str}."
    elif len(free_slots) == 1:
        slot = free_slots[0]
        speech = f"You have one free slot on {day_name}: {slot['duration_minutes']} minutes from {slot['start']} to {slot['end']}."
    else:
        first = free_slots[0]
        speech = (
            f"You have {len(free_slots)} free slots on {day_name} totaling {time_str}. "
            f"The first slot is {first['duration_minutes']} minutes from {first['start']} to {first['end']}."
        )

    return {
        "date": clean_date,
        "day_of_week": day_name,
        "student_name": student.name,
        "working_window": {"start": start_str, "end": end_str},
        "min_minutes_filter": min_mins,
        "slot_count": len(free_slots),
        "total_free_minutes": total_free_minutes,
        "free_slots": free_slots,
        "speech_summary": speech,
        "is_error": False,
    }
